"""Admin history filters and the list of period closes (V2_DELTA Delta 9, Q40/Q42).

A period close stamps every scan it closes (``closed_at``) and every order it completes
(``done_at``) with the same instant, so one distinct timestamp is one close.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
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
from .engine import get_db


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Columns hold naive UTC; aware inputs are converted, naive ones are taken as UTC."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class HistoryFilter:
    """Close-time range (inclusive), one exact close, and a case-insensitive search."""

    closed_from: Optional[datetime] = None
    closed_to: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    q: Optional[str] = None

    def time_conditions(self, column) -> list:
        conditions = []
        if self.closed_at is not None:
            conditions.append(column == _naive_utc(self.closed_at))
        if self.closed_from is not None:
            conditions.append(column >= _naive_utc(self.closed_from))
        if self.closed_to is not None:
            conditions.append(column <= _naive_utc(self.closed_to))
        return conditions

    @property
    def pattern(self) -> Optional[str]:
        text = (self.q or "").strip()
        return f"%{_escape_like(text)}%" if text else None


NO_FILTER = HistoryFilter()


def outbound_conditions(f: HistoryFilter) -> list:
    conditions = [OutboundItem.closed == True, *f.time_conditions(OutboundItem.closed_at)]  # noqa: E712
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


def get_close_history(
    limit: Optional[int] = None, offset: int = 0, f: HistoryFilter = NO_FILTER
) -> tuple[List[dict], int]:
    """Period closes, newest first: ``closed_at``, scans closed, orders done, scan tags.

    Rows without a close time (closed before v0.4 stamped one) are not listed. With ``f.q``,
    only closes holding a matching scan or order are listed, still with their full counts
    (V2_ORDERS_DELTA Q49).
    """
    scans = (
        select(
            OutboundItem.closed_at.label("closed_at"),
            literal(1).label("outbound"),
            literal(0).label("orders_done"),
        )
        .where(OutboundItem.closed == True, OutboundItem.closed_at.isnot(None))  # noqa: E712
        .where(*f.time_conditions(OutboundItem.closed_at))
    )
    orders = (
        select(
            ShopeeOrder.done_at.label("closed_at"),
            literal(0).label("outbound"),
            literal(1).label("orders_done"),
        )
        .where(ShopeeOrder.done == True, ShopeeOrder.done_at.isnot(None))  # noqa: E712
        .where(*f.time_conditions(ShopeeOrder.done_at))
    )
    rows = union_all(scans, orders).subquery()
    grouped = select(
        rows.c.closed_at,
        func.sum(rows.c.outbound).label("outbound"),
        func.sum(rows.c.orders_done).label("orders_done"),
    ).group_by(rows.c.closed_at)
    if f.pattern:
        matched = union_all(
            select(OutboundItem.closed_at.label("t")).where(*outbound_conditions(f)),
            select(ShopeeOrder.done_at.label("t")).where(*order_conditions(f)),
        ).subquery()
        grouped = grouped.where(rows.c.closed_at.in_(select(matched.c.t)))
    grouped = grouped.subquery()
    with get_db() as db:
        total = db.execute(select(func.count()).select_from(grouped)).scalar_one()
        page = db.execute(
            select(grouped).order_by(grouped.c.closed_at.desc()).offset(offset).limit(limit)
        ).all()
        times = [row.closed_at for row in page]
        tags: dict[datetime, list[str]] = {t: [] for t in times}
        if times:
            for t, tag in db.execute(
                select(OutboundItem.closed_at, OutboundTag.content)
                .join(OutboundTag, OutboundTag.outbound_id == OutboundItem.id)
                .where(OutboundItem.closed_at.in_(times))
                .distinct()
                .order_by(OutboundTag.content)
            ).all():
                tags[t].append(tag)
    return [
        {
            "closed_at": row.closed_at,
            "outbound": int(row.outbound),
            "orders_done": int(row.orders_done),
            "tags": tags[row.closed_at],
        }
        for row in page
    ], total


def lookup_label(label: str) -> dict:
    """Where an exact label is (V2_ORDERS_DELTA Q49): orders whose SN or a tracking number is
    ``label``, and scans of it, open or closed. Trimmed and case-insensitive, like the close
    (Q44); a few rows at most, newest first."""
    key = (label or "").strip().lower()
    if not key:
        return {"orders": [], "scans": []}
    with get_db() as db:
        orders = (
            db.execute(
                select(ShopeeOrder)
                .where(
                    or_(
                        func.lower(ShopeeOrder.order_sn) == key,
                        ShopeeOrder.info.any(func.lower(ShopeeOrderInfo.tracking_number) == key),
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
                .where(func.lower(OutboundItem.content) == key)
                .order_by(OutboundItem.created_at.desc(), OutboundItem.id.desc())
                .limit(20)
            )
            .scalars()
            .unique()
            .all()
        )
        return {"orders": list(orders), "scans": list(scans)}
