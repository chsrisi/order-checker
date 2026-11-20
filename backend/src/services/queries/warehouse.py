import logging
import re
from typing import List, Optional
from sqlalchemy import func, select
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
    # Check for new format: {alphanum:"prefix"}:[original hypen part]:{alphanum:"suffix"}
    match = re.fullmatch(r"[a-zA-Z0-9]+:(.+):[a-zA-Z0-9]+", token)
    target = match.group(1) if match else token

    if re.fullmatch(r"[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+", target):
        return target
    parts = target.split("-")
    if len(parts) == 3:
        return f"{parts[1]}-{parts[2]}"
    if len(parts) == 2:
        return parts[1]
    return target


def _equals_ci(column, value: str):
    """Case-insensitive *exact* match. ``ilike`` would treat ``%`` and ``_`` in scanned
    input as wildcards (``A01_001`` would also match ``A01X001``), F-H3."""
    return func.lower(column) == value.lower()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def resolve_barcode_to_item(barcode: str) -> Optional[WarehouseItem]:
    token = _first_token(barcode)
    if not token:
        return None
    with get_db() as db:
        sku_candidate = _sku_candidate(token)
        if sku_candidate:
            item = (
                db.execute(
                    select(WarehouseItem).filter(_equals_ci(WarehouseItem.sku, sku_candidate))
                )
                .scalars()
                .first()
            )
            if item:
                return item
        supplier_barcode = _supplier_barcode(token)
        item = (
            db.execute(
                select(WarehouseItem).filter(
                    _equals_ci(WarehouseItem.supplier_barcode, supplier_barcode)
                )
            )
            .scalars()
            .first()
        )
        if item:
            return item
        return (
            db.execute(select(WarehouseItem).filter(_equals_ci(WarehouseItem.sku, token)))
            .scalars()
            .first()
        )


def find_warehouse_items(query_str: str) -> List[WarehouseItem]:
    resolved = resolve_barcode_to_item(query_str)
    if resolved:
        return [resolved]

    with get_db() as db:
        search = f"%{_escape_like(query_str)}%"
        return list(
            db.execute(
                select(WarehouseItem)
                .filter(
                    WarehouseItem.sku.ilike(search, escape="\\")
                    | WarehouseItem.item_name.ilike(search, escape="\\")
                )
                .limit(50)
            )
            .scalars()
            .all()
        )


def get_all_warehouse_items() -> List[WarehouseItem]:
    with get_db() as db:
        return list(db.execute(select(WarehouseItem)).scalars().all())
