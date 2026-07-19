import logging
from typing import List, Optional
from sqlalchemy import select
from ...models import WarehouseItem
from .engine import get_db

logger = logging.getLogger("backend.services.queries.warehouse")


def resolve_barcode_to_item(barcode: str) -> Optional[WarehouseItem]:
    with get_db() as db:
        item = db.execute(
            select(WarehouseItem).filter(WarehouseItem.supplier_barcode == barcode)
        ).scalar_one_or_none()
        if item:
            return item

        item = db.execute(
            select(WarehouseItem).filter(WarehouseItem.sku == barcode)
        ).scalar_one_or_none()
        return item


def find_warehouse_items(query_str: str) -> List[WarehouseItem]:
    resolved = resolve_barcode_to_item(query_str)
    if resolved:
        return [resolved]

    with get_db() as db:
        search = f"%{query_str}%"
        return list(
            db.execute(
                select(WarehouseItem)
                .filter((WarehouseItem.sku.ilike(search)) | (WarehouseItem.item_name.ilike(search)))
                .limit(50)
            )
            .scalars()
            .all()
        )


def get_all_warehouse_items() -> List[WarehouseItem]:
    with get_db() as db:
        return list(db.execute(select(WarehouseItem)).scalars().all())
