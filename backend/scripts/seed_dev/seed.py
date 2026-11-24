"""Synthetic data set. Prefixes keep it separable from anything else in a dev database:
SKUs ``Z90_*``, order numbers ``DEV*``, users ``dev_*``, Shopee ids ``9000000xx``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select

from src import config
from src.models import (
    BOMDetail,
    BOMDetailMarketplace,
    BOMHeader,
    BOMHeaderMarketplace,
    OutboundItem,
    PickItemEntry,
    RefreshToken,
    ShopeeOrder,
    ShopeeOrderInfo,
    ShopeeOrderItemList,
    ShopeeOrderRecipientAddress,
    Stock,
    User,
    WarehouseItem,
)
from src.services.queries.engine import get_db

SKU_PREFIX = "Z90_"
ORDER_PREFIX = "DEV"
USER_PREFIX = "dev_"
DEV_PASSWORD = "dev-password"  # development only; production refuses this script

ITEMS = [
    # sku, name, supplier barcode
    ("Z90_001", "Synthetic flour 1 kg", "SUP9001-A"),
    ("Z90_002", "Synthetic sugar 1 kg", None),
    ("Z90_003", "Synthetic butter 500 g", None),
    ("Z90_010", "Synthetic cookie kit", None),  # standard BOM: 2x Z90_001 + 1x Z90_002
    ("Z90_011", "Synthetic gift box", None),  # nested: 1x Z90_010 + 1x Z90_003
]
STANDARD_BOMS = {
    "Z90_010": [("Z90_001", 2), ("Z90_002", 1)],
    "Z90_011": [("Z90_010", 1), ("Z90_003", 1)],
}
MARKETPLACE_BOMS = {
    900000001: ("Cookie kit listing", "Default", [("Z90_010", 1)]),
    900000002: ("Butter twin pack", "2 pcs", [("Z90_003", 2)]),
    900000003: ("Gift box listing", "Large", [("Z90_011", 1)]),
}
STOCK = {
    # multi: several bins, Z90_003 deliberately missing (shortfall); single: one bin each
    "multi": [("Z90_001", "A-01", 20), ("Z90_001", "B-02", 5), ("Z90_002", "A-02", 3)],
    "single": [("Z90_001", "A-01", 25), ("Z90_002", "A-02", 3)],
}


class SeedRefused(RuntimeError):
    pass


def _guard() -> None:
    if config.PRODUCTION_RULES:
        raise SeedRefused(
            f"APP_ENV={config.APP_ENV}: synthetic seeding runs only with APP_ENV=development"
        )


def _orders(now: datetime):
    day = timedelta(days=1)
    # sn, status, owner, ship_by, done_at, split, packages(tracking), items(shopee_id, qty)
    return [
        (
            "DEV0001",
            "READY_TO_SHIP",
            None,
            now + day,
            None,
            False,
            ["DEVTRK0001"],
            [(900000001, 1)],
        ),
        (
            "DEV0002",
            "PROCESSED",
            "dev_op1",
            now + 2 * day,
            None,
            False,
            ["DEVTRK0002"],
            [(900000002, 1)],
        ),
        (
            "DEV0003",
            "READY_TO_SHIP",
            None,
            now + day,
            None,
            True,
            ["DEVTRK0003A", "DEVTRK0003B"],
            [(900000001, 1), (900000003, 1)],
        ),
        (
            "DEV0004",
            "SHIPPED",
            "dev_op2",
            now - day,
            now - day,
            False,
            ["DEVTRK0004"],
            [(900000002, 2)],
        ),
        (
            "DEV0005",
            "RETRY_SHIP",
            None,
            now + timedelta(hours=3),
            None,
            False,
            [None],
            [(900000003, 1)],
        ),
        (
            "DEV0006",
            "READY_TO_SHIP",
            None,
            now - 2 * day,
            None,
            False,
            ["DEVTRK0006"],
            [(900000001, 1)],
        ),  # past ship-by: late, still ongoing (V2_ORDERS_DELTA F4)
        ("DEV0007", "CANCELLED", None, now + day, None, False, [None], [(900000001, 1)]),
        (
            "DEV0008",
            "COMPLETED",
            "dev_op1",
            now - 40 * day,
            now - 40 * day,
            False,
            ["DEVTRK0008"],
            [(900000002, 1)],
        ),  # past retention
    ]


def seed(stock_mode: str = "multi", now: datetime | None = None) -> dict[str, int]:
    _guard()
    from src.services.auth_service import get_password_hash

    now = now or datetime.now(UTC)
    counts = {"users": 0, "items": 0, "boms": 0, "stocks": 0, "orders": 0}
    password_hash = get_password_hash(DEV_PASSWORD)
    with get_db() as db:
        for username in ("dev_op1", "dev_op2"):
            if db.get(User, username) is None:
                db.add(User(username=username, password_hash=password_hash, scope="client"))
                counts["users"] += 1
        for sku, name, barcode in ITEMS:
            if db.get(WarehouseItem, sku) is None:
                db.add(WarehouseItem(sku=sku, item_name=name, supplier_barcode=barcode, uom="pcs"))
                counts["items"] += 1
        db.flush()

        for parent, children in STANDARD_BOMS.items():
            if db.execute(select(BOMHeader).filter_by(sku=parent)).scalar_one_or_none() is None:
                header = BOMHeader(sku=parent, quantity_standard=1)
                db.add(header)
                db.flush()
                for child, qty in children:
                    db.add(
                        BOMDetail(
                            bom_header_id=header.id, component_sku=child, quantity_standard=qty
                        )
                    )
                counts["boms"] += 1
        for shopee_id, (item_name, model_name, children) in MARKETPLACE_BOMS.items():
            if db.get(BOMHeaderMarketplace, shopee_id) is None:
                db.add(
                    BOMHeaderMarketplace(
                        shopee_id=shopee_id,
                        item_name=item_name,
                        model_name=model_name,
                        quantity_standard=1,
                        marketplace="shopee",
                        created_date=now.replace(tzinfo=None),
                    )
                )
                db.flush()
                for child, qty in children:
                    db.add(
                        BOMDetailMarketplace(
                            shopee_id=shopee_id, component_sku=child, quantity_standard=qty
                        )
                    )
                counts["boms"] += 1

        if not db.execute(select(Stock).where(Stock.sku.like(f"{SKU_PREFIX}%"))).first():
            for sku, location, qty in STOCK[stock_mode]:
                db.add(Stock(sku=sku, location=location, stock=qty))
                counts["stocks"] += 1

        for sn, status, owner, ship_by, done_at, split, tracking, items in _orders(now):
            if db.get(ShopeeOrder, sn) is not None:
                continue
            db.add(
                ShopeeOrder(
                    order_sn=sn,
                    split_up=split,
                    ship_by=ship_by,
                    owner_user=owner,
                    status=status,
                    shipping_carrier="Synthetic Express",
                    done=done_at is not None,
                    done_at=done_at,
                )
            )
            db.flush()
            for i, trk in enumerate(tracking, start=1):
                db.add(
                    ShopeeOrderInfo(
                        order_sn=sn,
                        package_number=f"PKG-{sn}-{i}",
                        logistics_status="LOGISTICS_READY" if trk else "LOGISTICS_NOT_START",
                        tracking_number=trk,
                        note="Synthetic buyer note" if i == 1 else None,
                    )
                )
            db.add(
                ShopeeOrderRecipientAddress(order_sn=sn, name="Synthetic Buyer", city="Sample City")
            )
            for shopee_id, qty in items:
                item_name, model_name, _ = MARKETPLACE_BOMS[shopee_id]
                db.add(
                    ShopeeOrderItemList(
                        order_sn=sn,
                        item_id=shopee_id,
                        item_name=item_name,
                        model_id=shopee_id,
                        model_name=model_name,
                        model_quantity_purchased=qty,
                    )
                )
            counts["orders"] += 1
        db.commit()
    return counts


def remove_seed() -> dict[str, int]:
    _guard()
    removed: dict[str, int] = {}
    with get_db() as db:
        sns = select(ShopeeOrder.order_sn).where(ShopeeOrder.order_sn.like(f"{ORDER_PREFIX}%"))
        users = select(User.username).where(User.username.like(f"{USER_PREFIX}%"))
        steps = [
            (
                "pick_entries",
                delete(PickItemEntry).where(
                    or_(
                        PickItemEntry.order_sn.in_(sns),
                        PickItemEntry.owner_user.in_(users),
                        PickItemEntry.sku.like(f"{SKU_PREFIX}%"),
                    )
                ),
            ),
            ("outbound", delete(OutboundItem).where(OutboundItem.owner_user.in_(users))),
            (
                "order_items",
                delete(ShopeeOrderItemList).where(ShopeeOrderItemList.order_sn.in_(sns)),
            ),
            ("order_info", delete(ShopeeOrderInfo).where(ShopeeOrderInfo.order_sn.in_(sns))),
            (
                "recipients",
                delete(ShopeeOrderRecipientAddress).where(
                    ShopeeOrderRecipientAddress.order_sn.in_(sns)
                ),
            ),
            ("orders", delete(ShopeeOrder).where(ShopeeOrder.order_sn.like(f"{ORDER_PREFIX}%"))),
            (
                "refresh_tokens",
                delete(RefreshToken).where(RefreshToken.username.like(f"{USER_PREFIX}%")),
            ),
            ("users", delete(User).where(User.username.like(f"{USER_PREFIX}%"))),
            ("stocks", delete(Stock).where(Stock.sku.like(f"{SKU_PREFIX}%"))),
            (
                "bom_details_marketplace",
                delete(BOMDetailMarketplace).where(
                    BOMDetailMarketplace.shopee_id.in_(list(MARKETPLACE_BOMS))
                ),
            ),
            (
                "bom_headers_marketplace",
                delete(BOMHeaderMarketplace).where(
                    BOMHeaderMarketplace.shopee_id.in_(list(MARKETPLACE_BOMS))
                ),
            ),
            (
                "bom_details",
                delete(BOMDetail).where(
                    BOMDetail.bom_header_id.in_(
                        select(BOMHeader.id).where(BOMHeader.sku.like(f"{SKU_PREFIX}%"))
                    )
                ),
            ),
            ("bom_headers", delete(BOMHeader).where(BOMHeader.sku.like(f"{SKU_PREFIX}%"))),
            ("items", delete(WarehouseItem).where(WarehouseItem.sku.like(f"{SKU_PREFIX}%"))),
        ]
        for name, stmt in steps:
            removed[name] = db.execute(stmt).rowcount or 0
        db.commit()
    return removed
