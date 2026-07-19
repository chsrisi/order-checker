import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PickItemEntry

logger = logging.getLogger("backend.services.pick_item")


def merge_or_create_pie(
    db: Session,
    username: str,
    sku: str,
    qty: int,
    order_sn: Optional[str] = None,
) -> PickItemEntry:
    """
    Finds an existing PickItemEntry for the same SKU and order, or creates a new one.
    Sums quantities if merging.
    """
    existing = (
        db.execute(
            select(PickItemEntry).filter(
                PickItemEntry.owner_user == username,
                PickItemEntry.sku == sku,
                PickItemEntry.order_sn == order_sn,
            )
        )
        .scalars()
        .first()
    )

    if existing:
        existing.qty = (existing.qty or 0) + qty
        db.add(existing)
        logger.info(
            f"Merged {qty} into existing PickItemEntry {existing.id} (Total: {existing.qty}) for SKU {sku}"
        )
        return existing

    new_entry = PickItemEntry(
        sku=sku,
        qty=qty,
        order_sn=order_sn,
        owner_user=username,
    )
    db.add(new_entry)
    db.flush()  # To get the ID
    logger.info(
        f"Created new PickItemEntry {new_entry.id} for SKU {sku} (Order: {order_sn})"
    )
    return new_entry
