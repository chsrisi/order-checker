import logging
from typing import Iterable, List, Optional
from datetime import datetime, timedelta, UTC
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import selectinload

from ...models import (
    ShopeeOrder,
    ShopeeOrderInfo,
    ShopeeOrderRecipientAddress,
    ShopeeOrderItemList,
    BOMHeader,
)
from ... import config
from .engine import get_db
from .history import NO_FILTER, HistoryFilter, order_conditions
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


def get_shopee_orders_history(
    limit: Optional[int] = None, offset: int = 0, f: HistoryFilter = NO_FILTER
) -> tuple[List[ShopeeOrder], int]:
    """Completed orders, most recently completed first, one page at a time (T5.2).

    ``f`` narrows by completion (close) time and search on the server (Delta 9, Q40).
    """
    conditions = order_conditions(f)
    with get_db() as db:
        total = db.execute(
            select(func.count()).select_from(ShopeeOrder).filter(*conditions)
        ).scalar_one()
        query = (
            select(ShopeeOrder)
            .filter(*conditions)
            .order_by(
                ShopeeOrder.done_at.desc().nulls_last(),
                ShopeeOrder.ship_by.desc(),
                ShopeeOrder.order_sn,
            )
            .offset(offset)
            .limit(limit)
            .options(
                selectinload(ShopeeOrder.info),
                selectinload(ShopeeOrder.item_list),
                selectinload(ShopeeOrder.recipient_address),
            )
        )
        return list(db.execute(query).scalars().all()), total


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


def _item_rows(order_detail) -> list[ShopeeOrderItemList]:
    rows = []
    for item in order_detail.item_list:
        if item.model_id == 0:
            item.model_id = item.model_name = item.model_sku = None
        rows.append(
            ShopeeOrderItemList(
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
        )
    return rows


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _past_retention(order: ShopeeOrder, cutoff: datetime) -> bool:
    """Same rule as purge_recipient_data: never re-store buyer data the purge removed."""
    if order.done_at is not None:
        return _naive_utc(order.done_at) < cutoff
    return not order.done and order.ship_by is not None and _naive_utc(order.ship_by) < cutoff


def sync_shopee_orders_to_db(chunk_results, now: Optional[datetime] = None) -> None:
    """Upsert order details from Shopee (T4.8 / F-M3).

    New orders are inserted with items, recipient and packages. Existing orders get their
    status, ship-by, split flag, carrier and items refreshed; their recipient row and buyer
    note are updated only while the order is inside the retention window (A-10b), and a
    purged recipient row is never recreated. Packages whose tracking lookup failed are
    skipped and keep their previous values.
    """
    cutoff = (now or datetime.now(UTC)).replace(tzinfo=None) - timedelta(
        days=config.RECIPIENT_RETENTION_DAYS
    )
    details = [d for chunk, _, _ in chunk_results for d in chunk]
    order_sns = [d.order_sn for d in details]
    all_package_nums = [
        pkg.package_number for d in details if d.package_list for pkg in d.package_list
    ]

    with get_db() as db:
        existing_orders = {
            o.order_sn: o
            for o in db.execute(
                select(ShopeeOrder)
                .filter(ShopeeOrder.order_sn.in_(order_sns))
                .options(selectinload(ShopeeOrder.recipient_address))
            ).scalars()
        }
        existing_infos = {
            info.package_number: info
            for info in db.execute(
                select(ShopeeOrderInfo).filter(ShopeeOrderInfo.package_number.in_(all_package_nums))
            ).scalars()
        }

        for order_details_list, tracking_map, fail_pkgs in chunk_results:
            for order_detail in order_details_list:
                db_order = existing_orders.get(order_detail.order_sn)
                carrier = (
                    order_detail.package_list[0].shipping_carrier
                    if order_detail.package_list
                    else None
                )
                keep_buyer_data = True

                if not db_order:
                    db_order = ShopeeOrder(order_sn=order_detail.order_sn, owner_user=None)
                    db.add(db_order)
                    if order_detail.recipient_address:
                        db.add(
                            ShopeeOrderRecipientAddress(
                                order_sn=order_detail.order_sn,
                                name=order_detail.recipient_address.name,
                                city=order_detail.recipient_address.city,
                            )
                        )
                else:
                    keep_buyer_data = not _past_retention(db_order, cutoff)
                    db.execute(
                        delete(ShopeeOrderItemList).where(
                            ShopeeOrderItemList.order_sn == order_detail.order_sn
                        )
                    )
                    recipient = db_order.recipient_address
                    if recipient and keep_buyer_data and order_detail.recipient_address:
                        recipient.name = order_detail.recipient_address.name
                        recipient.city = order_detail.recipient_address.city

                db_order.split_up = order_detail.split_up
                db_order.status = order_detail.order_status
                db_order.ship_by = order_detail.ship_by_date
                db_order.shipping_carrier = carrier
                db.add_all(_item_rows(order_detail))
                note = order_detail.note if keep_buyer_data else None

                for pkg in order_detail.package_list or []:
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
                        db.add(
                            ShopeeOrderInfo(
                                order_sn=order_detail.order_sn,
                                package_number=pkg.package_number,
                                logistics_status=pkg.logistics_status,
                                tracking_number=tracking_number,
                                pickup_code=pickup_code,
                                note=note,
                            )
                        )
                    else:
                        info.logistics_status = pkg.logistics_status
                        if order_detail.order_status != "READY_TO_SHIP":
                            info.tracking_number = tracking_number
                            info.pickup_code = pickup_code
                        info.note = note

        db.commit()


def local_active_order_sns(exclude: Iterable[str] = ()) -> list[str]:
    """Orders the database still treats as open, whatever their age (T4.8 / F-M2), so a
    sync can refresh them even when they fall outside the Shopee list window."""
    excluded = set(exclude)
    with get_db() as db:
        sns = db.execute(
            select(ShopeeOrder.order_sn).filter(
                ShopeeOrder.done == False,  # noqa: E712
                ShopeeOrder.status.in_(ACTIVE_ORDER_STATUSES),
            )
        ).scalars()
        return [sn for sn in sns if sn not in excluded]


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
