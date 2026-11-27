import logging
from typing import List, Optional
from datetime import datetime, UTC
from sqlalchemy import delete, func, or_, select, union, update

from ...models import OutboundItem, ShopeeOrder, ShopeeOrderInfo
from .engine import get_db
from .history import NO_FILTER, HistoryFilter, outbound_conditions

logger = logging.getLogger("backend.services.queries.outbound")

# Left the shop, as Shopee reports it (V2_ORDERS_DELTA Q51).
SHIPPED_ORDER_STATUSES = ("SHIPPED", "TO_CONFIRM_RECEIVE", "COMPLETED")


def get_outbounds_data(username: str) -> List[OutboundItem]:
    with get_db() as db:
        query = (
            select(OutboundItem)
            .filter(OutboundItem.owner_user == username, OutboundItem.closed == False)  # noqa: E712
            .order_by(OutboundItem.created_at.desc())
        )
        return list(db.execute(query).scalars().unique().all())


def get_all_outbound_data() -> List[OutboundItem]:
    with get_db() as db:
        query = (
            select(OutboundItem)
            .filter(OutboundItem.closed == False)  # noqa: E712
            .order_by(OutboundItem.created_at.desc())
        )
        return list(db.execute(query).scalars().unique().all())


def get_outbound_history(
    limit: Optional[int] = None, offset: int = 0, f: HistoryFilter = NO_FILTER
) -> tuple[List[OutboundItem], int]:
    """Closed scans, newest first, one page at a time (T5.2). Returns ``(page, total)``.

    ``f`` narrows by close time and search on the server (Delta 9, Q40).
    """
    conditions = outbound_conditions(f)
    with get_db() as db:
        total = db.execute(
            select(func.count()).select_from(OutboundItem).filter(*conditions)
        ).scalar_one()
        query = (
            select(OutboundItem)
            .filter(*conditions)
            .order_by(OutboundItem.created_at.desc(), OutboundItem.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.execute(query).scalars().unique().all()), total


def create_outbound_item(content: str, owner_username: str, tags_in: List[str]) -> OutboundItem:
    content_clean = content.strip()
    with get_db() as db:
        existing = (
            db.execute(
                select(OutboundItem).filter(
                    OutboundItem.owner_user == owner_username,
                    OutboundItem.content == content_clean,
                    OutboundItem.closed == False,  # noqa: E712
                )
            )
            .scalars()
            .unique()
            .first()
        )

        if existing:
            logger.warning(
                "duplicate_outbound_scan",
                extra={"event": "outbound.scan.duplicate", "username": owner_username},
            )
            raise ValueError("Duplicate scan detected")

        matched_order = (
            db.execute(
                select(ShopeeOrder)
                .outerjoin(ShopeeOrderInfo, ShopeeOrder.order_sn == ShopeeOrderInfo.order_sn)
                .filter(
                    or_(
                        ShopeeOrder.order_sn == content_clean,
                        ShopeeOrderInfo.tracking_number == content_clean,
                    )
                )
            )
            .scalars()
            .first()
        )

        tags = list(tags_in) if tags_in else []
        if matched_order and matched_order.shipping_carrier:
            if matched_order.shipping_carrier not in tags:
                tags.append(matched_order.shipping_carrier)

        db_item = OutboundItem(
            content=content_clean,
            owner_user=owner_username,
            tags=tags,
        )
        db.add(db_item)
        db.commit()
        db.refresh(db_item)
        return db_item


def _owners(done_rows) -> List[str]:
    """Who claimed the orders a close completed: their lists are stale (V2_PICKING_DELTA Q81)."""
    return sorted({row.owner_user for row in done_rows if row.owner_user})


def close_outbound_items(contents: List[str], admin_username: str) -> dict:
    logger.info(f"Admin {admin_username} closing period for {len(contents)} items")
    now = datetime.now(UTC)
    clean_contents = list(dict.fromkeys(c.strip() for c in contents if c and c.strip()))
    if not clean_contents:
        return {"outbound": 0, "unknown": 0, "orders_done": 0, "owners": []}

    # Labels match exactly, after trimming (V2_ORDERS_DELTA Q57, which replaces Q44).
    with get_db() as db:
        result_outbound = db.execute(
            update(OutboundItem)
            .where(
                OutboundItem.content.in_(clean_contents),
                OutboundItem.closed == False,  # noqa: E712
            )
            .values(closed=True, closed_at=now)
            .returning(OutboundItem.content)
        )
        closed_contents = [row.content for row in result_outbound.all()]
        outbound_count = len(closed_contents)
        # Several scans (e.g. two operators) can share one label: count *inputs* that
        # matched nothing, not rows, so the number never goes negative (F-M1).
        unknown_count = len(set(clean_contents) - set(closed_contents))

        matched_order_sns: set[str] = set(
            db.execute(
                select(ShopeeOrder.order_sn).filter(ShopeeOrder.order_sn.in_(clean_contents))
            )
            .scalars()
            .all()
        )

        remaining = [c for c in clean_contents if c not in matched_order_sns]
        if remaining:
            tracking_matches = (
                db.execute(
                    select(ShopeeOrderInfo.order_sn).filter(
                        ShopeeOrderInfo.tracking_number.in_(remaining),
                        ShopeeOrderInfo.tracking_number.isnot(None),
                    )
                )
                .scalars()
                .all()
            )
            matched_order_sns.update(tracking_matches)

        done: list = []
        if matched_order_sns:
            done = db.execute(
                update(ShopeeOrder)
                .where(
                    ShopeeOrder.order_sn.in_(list(matched_order_sns)),
                    ShopeeOrder.done == False,  # noqa: E712
                )
                .values(done=True, done_at=now)
                .returning(ShopeeOrder.order_sn, ShopeeOrder.owner_user)
            ).all()

        db.commit()
        logger.info(
            f"Closed period: {outbound_count} outbound, {unknown_count} unknown, "
            f"{len(done)} orders done"
        )
        return {
            "outbound": outbound_count,
            "unknown": unknown_count,
            "orders_done": len(done),
            "owners": _owners(done),
        }


def close_shipped_outbound() -> dict:
    """Close open scans whose order has left on Shopee, and complete those orders
    (V2_ORDERS_DELTA C1, Q51, Q52). Matches the whole database, not one sync's batch: an order
    may have shipped in a sync that ran before its label was scanned. Labels match exactly.
    Orders without an open scan are left alone, as are cancelled and returned ones."""
    now = datetime.now(UTC)
    open_scans = OutboundItem.closed == False  # noqa: E712
    left = ShopeeOrder.status.in_(SHIPPED_ORDER_STATUSES)
    pair = select(OutboundItem.id, ShopeeOrder.order_sn).select_from(OutboundItem)
    # Two joins, not one OR: each uses its index, and this runs with every sync.
    shipped = union(
        pair.join(ShopeeOrder, ShopeeOrder.order_sn == OutboundItem.content).where(
            open_scans, left
        ),
        pair.join(ShopeeOrderInfo, ShopeeOrderInfo.tracking_number == OutboundItem.content)
        .join(ShopeeOrder, ShopeeOrder.order_sn == ShopeeOrderInfo.order_sn)
        .where(open_scans, left),
    )
    with get_db() as db:
        pairs = db.execute(shipped).all()
        if not pairs:
            return {"outbound": 0, "orders_done": 0, "owners": []}
        closed = db.execute(
            update(OutboundItem)
            .where(
                OutboundItem.id.in_({scan_id for scan_id, _ in pairs}),
                OutboundItem.closed == False,  # noqa: E712
            )
            .values(closed=True, closed_at=now)
            .returning(OutboundItem.id)
        ).all()
        done = db.execute(
            update(ShopeeOrder)
            .where(
                ShopeeOrder.order_sn.in_({sn for _, sn in pairs}),
                ShopeeOrder.done == False,  # noqa: E712
            )
            .values(done=True, done_at=now)
            .returning(ShopeeOrder.order_sn, ShopeeOrder.owner_user)
        ).all()
        db.commit()
    result = {"outbound": len(closed), "orders_done": len(done)}
    logger.info("outbound_auto_closed", extra={"event": "outbound.auto_closed", **result})
    return {**result, "owners": _owners(done)}


def clear_all_outbound_items() -> int:
    with get_db() as db:
        result = db.execute(delete(OutboundItem).returning(OutboundItem.id))
        count = len(result.all())
        db.commit()
        return count
