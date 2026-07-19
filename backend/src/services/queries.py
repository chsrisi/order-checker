import logging
from typing import Sequence, List
from datetime import datetime, UTC
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    User,
    OutboundItem,
    ShopeeOrder,
    ShopeeOrderInfo,
    PickItemEntry,
    PickItemEntryResponse,
    WarehouseItem,
    Stock,
)

logger = logging.getLogger("backend.services.queries")

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


def get_user_data(db: Session, username: str) -> User | None:
    return db.execute(select(User).filter(User.username == username)).scalars().first()


def get_all_user_data(db: Session) -> Sequence[User]:
    return db.execute(select(User).filter(User.scope == "client")).scalars().all()


def get_outbounds_data(db: Session, username: str) -> Sequence[OutboundItem]:
    query = (
        select(OutboundItem)
        .filter(OutboundItem.owner_user == username, OutboundItem.closed == False)  # noqa: E712
        .order_by(OutboundItem.created_at.desc())
    )
    return db.execute(query).scalars().unique().all()


def get_all_outbound_data(db: Session) -> Sequence[OutboundItem]:
    query = (
        select(OutboundItem)
        .filter(OutboundItem.closed == False)  # noqa: E712
        .order_by(OutboundItem.created_at.desc())
    )
    return db.execute(query).scalars().unique().all()


def get_shopee_order_data(db: Session, username: str) -> Sequence[ShopeeOrder]:
    return (
        db.execute(lection_query.filter(ShopeeOrder.owner_user == username))
        .scalars()
        .all()
    )


def get_all_shopee_order_data(db: Session) -> Sequence[ShopeeOrder]:
    return db.execute(lection_query).scalars().all()


def get_pie_data(db: Session, username: str) -> List[PickItemEntryResponse]:
    query = (
        select(
            PickItemEntry.id,
            PickItemEntry.sku,
            PickItemEntry.qty,
            PickItemEntry.order_sn,
            PickItemEntry.timestamp,
            PickItemEntry.owner_user,
            WarehouseItem.item_name,
        )
        .outerjoin(WarehouseItem, PickItemEntry.sku == WarehouseItem.sku)
        .filter(PickItemEntry.owner_user == username)
        .order_by(PickItemEntry.timestamp.desc())
    )
    results = db.execute(query).all()
    return [
        PickItemEntryResponse(
            id=r.id,
            sku=r.sku,
            qty=r.qty,
            order_sn=r.order_sn,
            timestamp=r.timestamp,
            owner_user=r.owner_user,
            item_name=r.item_name,
        )
        for r in results
    ]


def get_all_pie_data(db: Session) -> List[PickItemEntryResponse]:
    query = (
        select(
            PickItemEntry.id,
            PickItemEntry.sku,
            PickItemEntry.qty,
            PickItemEntry.order_sn,
            PickItemEntry.timestamp,
            PickItemEntry.owner_user,
            WarehouseItem.item_name,
        )
        .outerjoin(WarehouseItem, PickItemEntry.sku == WarehouseItem.sku)
        .order_by(PickItemEntry.timestamp.desc())
    )
    results = db.execute(query).all()
    return [
        PickItemEntryResponse(
            id=r.id,
            sku=r.sku,
            qty=r.qty,
            order_sn=r.order_sn,
            timestamp=r.timestamp,
            owner_user=r.owner_user,
            item_name=r.item_name,
        )
        for r in results
    ]


def get_stocks_data(db: Session, join_warehouse: bool = False):
    query = select(Stock)
    if join_warehouse:
        query = select(
            Stock.id, Stock.sku, Stock.stock, Stock.location, WarehouseItem.item_name
        ).join(WarehouseItem, Stock.sku == WarehouseItem.sku)
    results = db.execute(query)
    return results.all() if join_warehouse else results.scalars().all()


def get_all_stocks_data(db: Session, join_warehouse: bool = False):
    return get_stocks_data(db, join_warehouse=join_warehouse)
