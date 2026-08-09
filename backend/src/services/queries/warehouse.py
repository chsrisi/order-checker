import logging
import re
from typing import List, Optional
from sqlalchemy import select
from ...models import WarehouseItem
from .engine import get_db

logger = logging.getLogger("backend.services.queries.warehouse")


def _first_token(barcode: str) -> Optional[str]:
    lines = [l.strip() for l in barcode.splitlines() if l.strip()]
    if not lines:
        return None
    tokens = lines[0].split()
    return tokens[0] if tokens else None


def _sku_candidate(token: str) -> Optional[str]:
    parts = token.split("*", 1)
    candidate = parts[0]
    return candidate if re.fullmatch(r"[a-zA-Z]\d{2}_\d{3}", candidate) else None


def _supplier_barcode(token: str) -> Optional[str]:
    if re.fullmatch(r"[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+", token):
        return token
    parts = token.split("-")
    if len(parts) == 3:
        return f"{parts[1]}-{parts[2]}"
    if len(parts) == 2:
        return parts[1]
    return token


def resolve_barcode_to_item(barcode: str) -> Optional[WarehouseItem]:
    token = _first_token(barcode)
    if not token:
        return None
    with get_db() as db:
        sku_candidate = _sku_candidate(token)
        if sku_candidate:
            item = db.execute(
                select(WarehouseItem).filter(WarehouseItem.sku.ilike(sku_candidate))
            ).scalars().first()
            if item:
                return item
        supplier_barcode = _supplier_barcode(token)
        item = db.execute(
            select(WarehouseItem).filter(WarehouseItem.supplier_barcode.ilike(supplier_barcode))
        ).scalars().first()
        if item:
            return item
        return db.execute(
            select(WarehouseItem).filter(WarehouseItem.sku.ilike(token))
        ).scalars().first()


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
