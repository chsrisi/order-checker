import logging
from typing import List, Optional
from datetime import datetime, UTC
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import selectinload

from ...models import (
    ShopeeOrder,
    ShopeeOrderInfo,
    ShopeeOrderRecipientAddress,
    ShopeeOrderItemList,
    BOMHeader,
)
from .engine import get_db
from .bom import get_marketplace_bom_node, get_standard_bom_node_internal

logger = logging.getLogger("backend.services.queries.orders")

ACTIVE_ORDER_STATUSES = ("READY_TO_SHIP", "PROCESSED", "RETRY_SHIP")


def active_orders_query(now: Optional[datetime] = None):
    """Orders operators can still work on.

    Built per call: the ship-by cutoff must be evaluated at query time, not at import time
    (it used to be a module-level query, which froze "now" at server start).
    """
    cutoff = now or datetime.now(UTC)
    return (
        select(ShopeeOrder)
        .outerjoin(ShopeeOrderInfo, ShopeeOrder.order_sn == ShopeeOrderInfo.order_sn)
        .filter(
            ShopeeOrder.done == False,  # noqa: E712
            ShopeeOrder.status.in_(ACTIVE_ORDER_STATUSES),
            ShopeeOrder.ship_by >= cutoff,
        )
        .order_by(ShopeeOrder.ship_by.desc())
    )


def resolve_shopee_order_bom_tree(
    shopee_id: Optional[int], sku: Optional[str], qty: int
) -> Optional[dict]:
    if shopee_id:
        node = get_marketplace_bom_node(shopee_id, qty)
        if node:
            return node
    if sku:
        with get_db() as db:
            hdr = db.execute(select(BOMHeader).filter(BOMHeader.sku == sku)).scalar_one_or_none()
            if hdr:
                return get_standard_bom_node_internal(sku, qty, False, db)
    return None


def get_shopee_order_data(username: str) -> List[ShopeeOrder]:
    with get_db() as db:
        query = (
            active_orders_query()
            .filter(ShopeeOrder.owner_user == username)
            .options(
                selectinload(ShopeeOrder.info),
                selectinload(ShopeeOrder.item_list),
                selectinload(ShopeeOrder.recipient_address),
            )
        )
        return list(db.execute(query).scalars().all())


def get_all_shopee_order_data() -> List[ShopeeOrder]:
    with get_db() as db:
        query = active_orders_query().options(
            selectinload(ShopeeOrder.info),
            selectinload(ShopeeOrder.item_list),
            selectinload(ShopeeOrder.recipient_address),
        )
        return list(db.execute(query).scalars().all())


def get_shopee_orders_history() -> List[ShopeeOrder]:
    with get_db() as db:
        query = (
            select(ShopeeOrder)
            .filter(ShopeeOrder.done == True)  # noqa: E712
            .order_by(ShopeeOrder.ship_by.desc())
            .options(
                selectinload(ShopeeOrder.info),
                selectinload(ShopeeOrder.item_list),
                selectinload(ShopeeOrder.recipient_address),
            )
        )
        return list(db.execute(query).scalars().all())


def acquire_order(order_sn: str, username: str) -> bool:
    """Claim an order for ``username`` atomically (F-H4).

    A single conditional ``UPDATE`` decides the winner, so two operators claiming at the same
    time can never both succeed. Returns ``False`` when the order does not exist; raises
    ``ValueError`` (mapped to 409) when another operator owns it or it is already completed.
    """
    with get_db() as db:
        claimed = db.execute(
            update(ShopeeOrder)
            .where(
                ShopeeOrder.order_sn == order_sn,
                or_(ShopeeOrder.owner_user.is_(None), ShopeeOrder.owner_user == username),
                ShopeeOrder.done == False,  # noqa: E712
            )
            .values(owner_user=username)
            .returning(ShopeeOrder.order_sn)
        ).first()
        db.commit()
        if claimed:
            return True

        current = db.execute(
            select(ShopeeOrder.owner_user, ShopeeOrder.done).filter(
                ShopeeOrder.order_sn == order_sn
            )
        ).first()
        if current is None:
            return False
        if current.done:
            raise ValueError("Order already completed")
        raise ValueError("Order is already assigned to another operator")


def sync_shopee_orders_to_db(chunk_results) -> None:
    order_sns = []
    for details, _, _ in chunk_results:
        for detail in details:
            order_sns.append(detail.order_sn)

    all_package_nums = [
        pkg.package_number
        for details, _, _ in chunk_results
        for detail in details
        if detail.package_list
        for pkg in detail.package_list
    ]

    with get_db() as db:
        existing_orders = {
            o.order_sn: o
            for o in db.execute(select(ShopeeOrder).filter(ShopeeOrder.order_sn.in_(order_sns)))
            .scalars()
            .all()
        }

        existing_infos = {
            info.package_number: info
            for info in db.execute(
                select(ShopeeOrderInfo).filter(ShopeeOrderInfo.package_number.in_(all_package_nums))
            )
            .scalars()
            .all()
        }

        for chunk_idx, (order_details_list, tracking_map, fail_pkgs) in enumerate(
            chunk_results, start=1
        ):
            for order_detail in order_details_list:
                db_order = existing_orders.get(order_detail.order_sn)

                if not db_order:
                    db_order = ShopeeOrder(order_sn=order_detail.order_sn, owner_user=None)
                    db_order.split_up = order_detail.split_up
                    db_order.status = order_detail.order_status
                    db_order.ship_by = order_detail.ship_by_date
                    db_order.shipping_carrier = (
                        order_detail.package_list[0].shipping_carrier
                        if order_detail.package_list
                        else None
                    )
                    db.add(db_order)

                    if order_detail.recipient_address:
                        addr = ShopeeOrderRecipientAddress(
                            order_sn=order_detail.order_sn,
                            name=order_detail.recipient_address.name,
                            city=order_detail.recipient_address.city,
                        )
                        db.add(addr)

                    for item in order_detail.item_list:
                        if item.model_id == 0:
                            item.model_id = item.model_name = item.model_sku = None
                        db_item = ShopeeOrderItemList(
                            order_sn=order_detail.order_sn,
                            item_id=item.item_id,
                            item_name=item.item_name,
                            item_sku=item.item_sku,
                            model_id=item.model_id,
                            model_name=item.model_name,
                            model_sku=item.model_sku,
                            model_quantity_purchased=item.model_quantity_purchased,
                            image_url=item.image_info.image_url if item.image_info else None,
                        )
                        db.add(db_item)
                else:
                    db_order.status = order_detail.order_status
                    db_order.shipping_carrier = (
                        order_detail.package_list[0].shipping_carrier
                        if order_detail.package_list
                        else None
                    )

                if order_detail.package_list:
                    for pkg in order_detail.package_list:
                        if pkg.package_number in fail_pkgs:
                            continue

                        info = existing_infos.get(pkg.package_number)
                        tracking_number = pickup_code = None

                        if (
                            order_detail.order_status != "READY_TO_SHIP"
                            and pkg.package_number in tracking_map
                        ):
                            tracking_number, pickup_code = tracking_map[pkg.package_number]

                        if not info:
                            info = ShopeeOrderInfo(
                                order_sn=order_detail.order_sn,
                                package_number=pkg.package_number,
                                logistics_status=pkg.logistics_status,
                                tracking_number=tracking_number,
                                pickup_code=pickup_code,
                                note=order_detail.note,
                            )
                            db.add(info)
                        else:
                            info.logistics_status = pkg.logistics_status
                            if order_detail.order_status != "READY_TO_SHIP":
                                info.tracking_number = tracking_number
                                info.pickup_code = pickup_code
                            info.note = order_detail.note

        db.commit()


def purge_recipient_data(cutoff: datetime) -> tuple[int, int]:
    """Delete recipient addresses and clear buyer notes of orders past retention (A-10b).

    An order is past retention when it was completed before ``cutoff``, or, if it was
    never completed, when its ship-by date is before ``cutoff``. Order numbers, items and
    tracking numbers are kept. Returns ``(addresses_deleted, notes_cleared)``.
    """
    expired = select(ShopeeOrder.order_sn).where(
        or_(
            ShopeeOrder.done_at < cutoff,
            and_(ShopeeOrder.done == False, ShopeeOrder.ship_by < cutoff),  # noqa: E712
        )
    )
    with get_db() as db:
        addresses = db.execute(
            delete(ShopeeOrderRecipientAddress)
            .where(ShopeeOrderRecipientAddress.order_sn.in_(expired))
            .returning(ShopeeOrderRecipientAddress.id)
        ).all()
        notes = db.execute(
            update(ShopeeOrderInfo)
            .where(ShopeeOrderInfo.order_sn.in_(expired), ShopeeOrderInfo.note.isnot(None))
            .values(note=None)
            .returning(ShopeeOrderInfo.id)
        ).all()
        db.commit()
        return len(addresses), len(notes)
