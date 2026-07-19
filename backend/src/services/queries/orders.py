import logging
from typing import List, Optional
from datetime import datetime, UTC
from sqlalchemy import select
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

lection_query = (
    select(ShopeeOrder)
    .outerjoin(ShopeeOrderInfo, ShopeeOrder.order_sn == ShopeeOrderInfo.order_sn)
    .filter(
        ShopeeOrder.done == False,  # noqa: E712
        ShopeeOrder.status.in_(["READY_TO_SHIP", "PROCESSED", "RETRY_SHIP"]),
        ShopeeOrder.ship_by >= datetime.now(UTC),
    )
    .order_by(ShopeeOrder.ship_by.desc())
)


def resolve_shopee_order_bom_tree(
    shopee_id: Optional[int], sku: Optional[str], qty: int
) -> Optional[dict]:
    if shopee_id:
        node = get_marketplace_bom_node(shopee_id)
        if node:
            node["quantity"] = qty
            return node
    if sku:
        with get_db() as db:
            hdr = db.execute(select(BOMHeader).filter(BOMHeader.sku == sku)).scalar_one_or_none()
            if hdr:
                return get_standard_bom_node_internal(sku, qty, False, db)
    return None


def get_shopee_order_data(username: str) -> List[ShopeeOrder]:
    with get_db() as db:
        query = lection_query.filter(ShopeeOrder.owner_user == username).options(
            selectinload(ShopeeOrder.info),
            selectinload(ShopeeOrder.item_list),
            selectinload(ShopeeOrder.recipient_address),
        )
        return list(db.execute(query).scalars().all())


def get_all_shopee_order_data() -> List[ShopeeOrder]:
    with get_db() as db:
        query = lection_query.options(
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
    with get_db() as db:
        db_order = (
            db.execute(select(ShopeeOrder).filter(ShopeeOrder.order_sn == order_sn))
            .scalars()
            .first()
        )
        if not db_order:
            return False

        if db_order.owner_user not in (None, username):
            raise ValueError("Order is already assigned to another operator")

        db_order.owner_user = username
        db.commit()
        return True


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
