import logging
from datetime import datetime, UTC
from typing import List
from fastapi import HTTPException
from sqlalchemy import select, or_, update
from sqlalchemy.orm import Session

from ..models import OutboundItem, ShopeeOrder, ShopeeOrderInfo
from ..cache import shopee_cache

logger = logging.getLogger("backend.services.outbound")


def create_outbound_item(
    db: Session, content: str, owner_username: str, tags_in: List[str]
) -> OutboundItem:
    content_clean = content.strip()

    # Duplicate detection (same user, same content)
    existing = (
        db.execute(
            select(OutboundItem).filter(
                OutboundItem.content == content,
                OutboundItem.owner_user == owner_username,
                OutboundItem.closed == False,  # noqa: E712
            )
        )
        .scalars()
        .unique()
        .first()
    )

    if existing:
        logger.warning(
            "Duplicate scan detected for user %s: %s",
            owner_username,
            content,
        )
        raise HTTPException(status_code=409, detail="Duplicate scan detected")

    matched_order = (
        db.execute(
            select(ShopeeOrder)
            .outerjoin(
                ShopeeOrderInfo, ShopeeOrder.order_sn == ShopeeOrderInfo.order_sn
            )
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
        content=content,
        owner_user=owner_username,
        tags=tags,
    )
    db.add(db_item)
    db.flush()
    return db_item


def close_outbound_items(db: Session, contents: List[str], admin_username: str) -> dict:
    logger.info(f"Admin {admin_username} closing period for {len(contents)} items")

    now = datetime.now(UTC)

    # Mark outbounds as closed
    result = db.execute(
        update(OutboundItem)
        .filter(OutboundItem.content.in_(contents), OutboundItem.closed == False)  # noqa: E712
        .values(closed=True, closed_at=now)
        .returning(OutboundItem.id)
    )

    outbound_count = len(result.all())
    unknown_count = len(contents) - outbound_count

    # Mark matched ShopeeOrders as done
    # Batch 1: match content as order_sn
    matched_order_sns: set[str] = set(
        db.execute(
            select(ShopeeOrder.order_sn).filter(ShopeeOrder.order_sn.in_(contents))
        )
        .scalars()
        .all()
    )

    # Batch 2: remaining content strings — try as tracking_number
    remaining = [c for c in contents if c not in matched_order_sns]
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
            .filter(
                ShopeeOrder.order_sn.in_(list(matched_order_sns)),
                ShopeeOrder.done == False,  # noqa: E712
            )
            .values(done=True, done_at=now)
            .returning(ShopeeOrder.order_sn)
        )
        orders_done_count = len(result_orders.all())

    db.commit()
    shopee_cache.invalidate()

    logger.info(
        f"Closed period: {outbound_count} outbound, {unknown_count} unknown, "
        f"{orders_done_count} orders done"
    )

    return {
        "outbound": outbound_count,
        "unknown": unknown_count,
        "orders_done": orders_done_count,
    }
