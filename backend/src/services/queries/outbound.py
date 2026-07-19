import logging
from typing import List
from datetime import datetime, UTC
from sqlalchemy import select, update, or_, delete

from ...models import OutboundItem, ShopeeOrder, ShopeeOrderInfo
from .engine import get_db

logger = logging.getLogger("backend.services.queries.outbound")


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


def get_outbound_history() -> List[OutboundItem]:
    with get_db() as db:
        query = (
            select(OutboundItem)
            .filter(OutboundItem.closed == True)  # noqa: E712
            .order_by(OutboundItem.created_at.desc())
        )
        return list(db.execute(query).scalars().unique().all())


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


def close_outbound_items(contents: List[str], admin_username: str) -> dict:
    logger.info(f"Admin {admin_username} closing period for {len(contents)} items")
    now = datetime.now(UTC)
    clean_contents = list(dict.fromkeys(c.strip() for c in contents if c and c.strip()))
    if not clean_contents:
        return {"outbound": 0, "unknown": 0, "orders_done": 0}

    with get_db() as db:
        result_outbound = db.execute(
            update(OutboundItem)
            .where(
                OutboundItem.content.in_(clean_contents),
                OutboundItem.closed == False,  # noqa: E712
            )
            .values(closed=True, closed_at=now)
            .returning(OutboundItem.id)
        )
        outbound_count = len(result_outbound.all())
        unknown_count = len(clean_contents) - outbound_count

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

        orders_done_count = 0
        if matched_order_sns:
            result_orders = db.execute(
                update(ShopeeOrder)
                .where(
                    ShopeeOrder.order_sn.in_(list(matched_order_sns)),
                    ShopeeOrder.done == False,  # noqa: E712
                )
                .values(done=True, done_at=now)
                .returning(ShopeeOrder.order_sn)
            )
            orders_done_count = len(result_orders.all())

        db.commit()
        logger.info(
            f"Closed period: {outbound_count} outbound, {unknown_count} unknown, "
            f"{orders_done_count} orders done"
        )
        return {
            "outbound": outbound_count,
            "unknown": unknown_count,
            "orders_done": orders_done_count,
        }


def clear_all_outbound_items() -> int:
    with get_db() as db:
        result = db.execute(delete(OutboundItem).returning(OutboundItem.id))
        count = len(result.all())
        db.commit()
        return count
