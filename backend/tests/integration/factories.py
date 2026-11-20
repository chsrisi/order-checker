"""Small synthetic-data builders for PostgreSQL integration tests (no real data)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.models import (
    ShopeeOrder,
    ShopeeOrderInfo,
    ShopeeOrderRecipientAddress,
    Stock,
    User,
    WarehouseItem,
)


def add_user(db, username="operator", scope="client"):
    db.add(User(username=username, password_hash="x", scope=scope))
    db.flush()


def add_order(
    db,
    order_sn="260101TEST0001",
    *,
    owner=None,
    done=False,
    status="READY_TO_SHIP",
    ship_by=None,
    tracking=None,
    done_at=None,
    recipient=False,
    note=None,
):
    db.add(
        ShopeeOrder(
            order_sn=order_sn,
            split_up=False,
            ship_by=ship_by or datetime.now(UTC) + timedelta(days=1),
            owner_user=owner,
            status=status,
            done=done,
            done_at=done_at,
        )
    )
    db.flush()
    if tracking is not None or note is not None:
        db.add(
            ShopeeOrderInfo(
                order_sn=order_sn,
                package_number=f"PKG-{order_sn}",
                tracking_number=tracking,
                note=note,
            )
        )
    if recipient:
        db.add(ShopeeOrderRecipientAddress(order_sn=order_sn, name="Synthetic Name", city="Town"))
    db.flush()


def add_item(db, sku="A01_001", *, name="Item", supplier_barcode=None):
    """``WarehouseItem.location`` is derived from its stock rows; use add_stock for bins."""
    db.add(WarehouseItem(sku=sku, item_name=name, supplier_barcode=supplier_barcode))
    db.flush()


def add_stock(db, sku="A01_001", qty=10, location=None):
    db.add(Stock(sku=sku, stock=qty, location=location))
    db.flush()
