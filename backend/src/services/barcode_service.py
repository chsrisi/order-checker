import logging
import re
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import WarehouseItem

logger = logging.getLogger("backend.services.barcode")


def resolve_barcode_to_item(barcode: str, db: Session) -> Optional[WarehouseItem]:
    if not barcode:
        return None

    # Get the first non-empty line
    lines = [line.strip() for line in barcode.splitlines() if line.strip()]
    if not lines:
        return None
    first_line = lines[0]

    # Get the first token
    tokens = first_line.split()
    if not tokens:
        return None
    token = tokens[0]

    # Rule (a): {sku}**<some other meta * delimited>; extract sku, sku is the real sku in warehouse.items.
    # this sku is exclusively XNN_NNN, where x is alphabet and n is numeric
    sku_candidate = None
    if "*" in token:
        parts = token.split("*")
        sku_candidate = parts[0]
    else:
        # Check if the whole token matches XNN_NNN format directly as a candidate SKU
        sku_candidate = token

    # Check if sku_candidate matches exclusively XNN_NNN format
    # XNN_NNN means: alphabet character, followed by two digits, followed by underscore, followed by three digits.
    if sku_candidate and re.match(r"^[a-zA-Z]\d{2}_\d{3}$", sku_candidate):
        item = (
            db.execute(
                select(WarehouseItem).filter(WarehouseItem.sku.ilike(sku_candidate))
            )
            .scalars()
            .first()
        )
        if item:
            return item

    # If it was not resolved as SKU rule (a), look for supplier barcode matches
    supplier_barcode = None

    # Rule (f): regex x+-x+-x+-x+ where x is alphanum
    if re.match(r"^[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+$", token):
        supplier_barcode = token
    else:
        # Check number of parts separated by hyphens
        parts = token.split("-")
        if len(parts) == 3:
            # Rule (c): {batch}-{type}-{id}; extract {type}-{id}
            supplier_barcode = f"{parts[1]}-{parts[2]}"
        elif len(parts) == 2:
            # Rule (b): {batch}-{id}; extract id
            supplier_barcode = parts[1]
        else:
            # Rule (e): {id}; extract id (the whole token)
            supplier_barcode = token

    if supplier_barcode:
        item = (
            db.execute(
                select(WarehouseItem).filter(
                    WarehouseItem.barcode_supplier.ilike(supplier_barcode)
                )
            )
            .scalars()
            .first()
        )
        if item:
            return item

    # Fallback to direct SKU query using the cleaned token if no match found
    item = (
        db.execute(select(WarehouseItem).filter(WarehouseItem.sku.ilike(token)))
        .scalars()
        .first()
    )
    return item
