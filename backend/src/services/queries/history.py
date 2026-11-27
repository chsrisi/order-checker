"""Admin history: filters, the list of days, one day, and the exact-label lookup.

A day is a business day (``timezone.BUSINESS_TZ``); a scan belongs to the day it was **made**,
not the day it was closed (V2_ORDERS_DELTA Q53).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.orm import selectinload

from ...models import (
    OutboundItem,
    OutboundTag,
    ShopeeOrder,
    ShopeeOrderInfo,
    ShopeeOrderRecipientAddress,
)
from ...timezone import BUSINESS_TZ, as_utc, business_time, day_start
from .engine import get_db


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class HistoryFilter:
    """Close-time range (inclusive), business-day range (inclusive, see the module) and a
    case-insensitive search."""

    closed_from: Optional[datetime] = None
    closed_to: Optional[datetime] = None
    day_from: Optional[date] = None
    day_to: Optional[date] = None
    q: Optional[str] = None

    def time_conditions(self, column) -> list:
        conditions = []
        if self.closed_from is not None:
            conditions.append(column >= as_utc(self.closed_from))
        if self.closed_to is not None:
            conditions.append(column <= as_utc(self.closed_to))
        return conditions

    @property
    def pattern(self) -> Optional[str]:
        text = (self.q or "").strip()
        return f"%{_escape_like(text)}%" if text else None


NO_FILTER = HistoryFilter()


def outbound_conditions(f: HistoryFilter) -> list:
    conditions = [OutboundItem.closed == True, *f.time_conditions(OutboundItem.closed_at)]  # noqa: E712
    if f.day_from is not None:
        conditions.append(OutboundItem.created_at >= day_start(f.day_from))
    if f.day_to is not None:
        conditions.append(OutboundItem.created_at < day_start(f.day_to + timedelta(days=1)))
    if f.pattern:
        conditions.append(
            or_(
                OutboundItem.content.ilike(f.pattern, escape="\\"),
                OutboundItem.owner_user.ilike(f.pattern, escape="\\"),
                OutboundItem.tags_rel.any(OutboundTag.content.ilike(f.pattern, escape="\\")),
            )
        )
    return conditions


def order_conditions(f: HistoryFilter) -> list:
    conditions = [ShopeeOrder.done == True, *f.time_conditions(ShopeeOrder.done_at)]  # noqa: E712
    if f.day_from is not None or f.day_to is not None:
        days = _order_days()
        conditions.append(
            ShopeeOrder.order_sn.in_(select(days.c.order_sn).where(*_in_days(days.c.day, f)))
        )
    if f.pattern:
        conditions.append(
            or_(
                ShopeeOrder.order_sn.ilike(f.pattern, escape="\\"),
                ShopeeOrder.owner_user.ilike(f.pattern, escape="\\"),
                ShopeeOrder.shipping_carrier.ilike(f.pattern, escape="\\"),
                # Buyer names exist only within RECIPIENT_RETENTION_DAYS (V2_ORDERS_DELTA F5).
                ShopeeOrder.recipient_address.has(
                    ShopeeOrderRecipientAddress.name.ilike(f.pattern, escape="\\")
                ),
                ShopeeOrder.info.any(
                    or_(
                        ShopeeOrderInfo.tracking_number.ilike(f.pattern, escape="\\"),
                        ShopeeOrderInfo.pickup_code.ilike(f.pattern, escape="\\"),
                    )
                ),
            )
        )
    return conditions


def _scan_day(column):
    """The business day of a timestamp column. The offset is fixed, so UTC plus it is exact."""
    return func.date(func.timezone("UTC", column) + BUSINESS_TZ.utcoffset(None))


def _order_days():
    """``(day, order_sn)`` of done orders: every day one of their closed scans was made, or the
    day they were done when they have none (V2_ORDERS_DELTA R4.2)."""
    labels = union_all(
        select(ShopeeOrder.order_sn.label("order_sn"), ShopeeOrder.order_sn.label("label")),
        select(ShopeeOrderInfo.order_sn, ShopeeOrderInfo.tracking_number),
    ).subquery()
    scanned = (
        select(
            _scan_day(OutboundItem.created_at).label("day"), ShopeeOrder.order_sn.label("order_sn")
        )
        .join(labels, labels.c.label == OutboundItem.content)
        .join(ShopeeOrder, ShopeeOrder.order_sn == labels.c.order_sn)
        .where(OutboundItem.closed == True, ShopeeOrder.done == True)  # noqa: E712
        .distinct()
        .cte("scanned_orders")
    )
    unscanned = select(_scan_day(ShopeeOrder.done_at), ShopeeOrder.order_sn).where(
        ShopeeOrder.done == True,  # noqa: E712
        ShopeeOrder.done_at.isnot(None),
        ShopeeOrder.order_sn.notin_(select(scanned.c.order_sn)),
    )
    return union_all(select(scanned.c.day, scanned.c.order_sn), unscanned).cte("order_days")


def _in_days(column, f: HistoryFilter) -> list:
    conditions = []
    if f.day_from is not None:
        conditions.append(column >= f.day_from)
    if f.day_to is not None:
        conditions.append(column <= f.day_to)
    return conditions


def get_day_history(
    limit: Optional[int] = None, offset: int = 0, f: HistoryFilter = NO_FILTER
) -> tuple[List[dict], int]:
    """History by business day, newest first (V2_ORDERS_DELTA C2, Q53): closed scans by the day
    they were made, done orders by ``_order_days``, and the scans' tags. With ``f.q``, only days
    holding a matching scan or order are listed, still with their full counts."""
    scan_day = _scan_day(OutboundItem.created_at)
    order_days = _order_days()
    rows = union_all(
        select(scan_day.label("day"), literal(1).label("outbound"), literal(0).label("orders_done"))
        .select_from(OutboundItem)
        .where(OutboundItem.closed == True),  # noqa: E712
        select(order_days.c.day, literal(0), literal(1)),
    ).subquery()
    grouped = (
        select(
            rows.c.day,
            func.sum(rows.c.outbound).label("outbound"),
            func.sum(rows.c.orders_done).label("orders_done"),
        )
        .where(*_in_days(rows.c.day, f))
        .group_by(rows.c.day)
    )
    if f.pattern:
        match = HistoryFilter(q=f.q)
        matched = union_all(
            select(scan_day.label("day")).where(*outbound_conditions(match)),
            select(order_days.c.day).where(
                order_days.c.order_sn.in_(
                    select(ShopeeOrder.order_sn).where(*order_conditions(match))
                )
            ),
        ).subquery()
        grouped = grouped.where(rows.c.day.in_(select(matched.c.day)))
    grouped = grouped.subquery()
    with get_db() as db:
        total = db.execute(select(func.count()).select_from(grouped)).scalar_one()
        page = db.execute(
            select(grouped).order_by(grouped.c.day.desc()).offset(offset).limit(limit)
        ).all()
        tags: dict[date, list[str]] = {row.day: [] for row in page}
        if page:
            for day, tag in db.execute(
                select(scan_day, OutboundTag.content)
                .join(OutboundTag, OutboundTag.outbound_id == OutboundItem.id)
                .where(OutboundItem.closed == True, scan_day.in_(list(tags)))  # noqa: E712
                .distinct()
                .order_by(OutboundTag.content)
            ).all():
                tags[day].append(tag)
    return [
        {
            "day": row.day,
            "outbound": int(row.outbound),
            "orders_done": int(row.orders_done),
            "tags": tags[row.day],
        }
        for row in page
    ], total


def get_day(day: date) -> dict:
    """Everything of one business day: its closed scans and done orders, unpaged (F12)."""
    f = HistoryFilter(day_from=day, day_to=day)
    with get_db() as db:
        scans = (
            db.execute(
                select(OutboundItem)
                .where(*outbound_conditions(f))
                .order_by(OutboundItem.created_at.desc(), OutboundItem.id.desc())
            )
            .scalars()
            .unique()
            .all()
        )
        orders = (
            db.execute(
                select(ShopeeOrder)
                .where(*order_conditions(f))
                .order_by(ShopeeOrder.done_at.desc().nulls_last(), ShopeeOrder.order_sn)
                .options(
                    selectinload(ShopeeOrder.info),
                    selectinload(ShopeeOrder.item_list),
                    selectinload(ShopeeOrder.recipient_address),
                )
            )
            .scalars()
            .all()
        )
        return {"orders": list(orders), "scans": list(scans)}


def lookup_label(label: str) -> dict:
    """Where an exact label is (V2_ORDERS_DELTA Q49): orders whose SN or a tracking number is
    ``label``, and scans of it, open or closed. Trimmed, then exact, like the close (Q57);
    a few rows at most, newest first. ``day`` is the History day it left on, if it left."""
    key = (label or "").strip()
    if not key:
        return {"orders": [], "scans": [], "day": None}
    with get_db() as db:
        orders = (
            db.execute(
                select(ShopeeOrder)
                .where(
                    or_(
                        ShopeeOrder.order_sn == key,
                        ShopeeOrder.info.any(ShopeeOrderInfo.tracking_number == key),
                    )
                )
                .order_by(ShopeeOrder.done_at.desc().nulls_first(), ShopeeOrder.order_sn)
                .limit(10)
                .options(
                    selectinload(ShopeeOrder.info),
                    selectinload(ShopeeOrder.item_list),
                    selectinload(ShopeeOrder.recipient_address),
                )
            )
            .scalars()
            .all()
        )
        scans = (
            db.execute(
                select(OutboundItem)
                .where(OutboundItem.content == key)
                .order_by(OutboundItem.created_at.desc(), OutboundItem.id.desc())
                .limit(20)
            )
            .scalars()
            .unique()
            .all()
        )
        day = None
        if orders and orders[0].done:
            order_days = _order_days()
            day = db.execute(
                select(func.max(order_days.c.day)).where(
                    order_days.c.order_sn == orders[0].order_sn
                )
            ).scalar_one()
        elif not orders and scans and scans[0].closed:
            day = business_time(scans[0].created_at).date()
        return {"orders": list(orders), "scans": list(scans), "day": day}
