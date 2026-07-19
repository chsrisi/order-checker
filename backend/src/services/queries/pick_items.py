import logging
from typing import List, Optional
from datetime import datetime, UTC
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...models import PickItemEntry, ShopeeOrder
from .engine import get_db
from .warehouse import resolve_barcode_to_item

logger = logging.getLogger("backend.services.queries.pick_items")

def merge_or_create_pie(
    sku: str, qty: int, order_sn: Optional[str], username: str
) -> PickItemEntry:
    with get_db() as db:
        existing = (
            db.execute(
                select(PickItemEntry).filter(
                    PickItemEntry.sku == sku,
                    PickItemEntry.order_sn == order_sn,
                    PickItemEntry.owner_user == username,
                )
            )
            .scalars()
            .first()
        )

        if existing:
            existing.qty += qty
            existing.timestamp = datetime.now(UTC)
            db.commit()
            db.refresh(existing)
            return existing

        db_pie = PickItemEntry(
            sku=sku,
            qty=qty,
            order_sn=order_sn,
            owner_user=username,
            timestamp=datetime.now(UTC),
        )
        db.add(db_pie)
        db.commit()
        db.refresh(db_pie)
        return db_pie

def get_pie_data(
    username: Optional[str] = None,
    sku: Optional[str] = None,
    order_sn: Optional[str] = None,
    entry_id: Optional[int] = None,
    db: Optional[Session] = None,
) -> List[PickItemEntry]:
    query = select(PickItemEntry)
    if username is not None:
        query = query.filter(PickItemEntry.owner_user == username)
    if sku is not None:
        query = query.filter(PickItemEntry.sku == sku)
    if order_sn is not None:
        query = query.filter(PickItemEntry.order_sn == order_sn)
    if entry_id is not None:
        query = query.filter(PickItemEntry.id == entry_id)
    query = query.order_by(PickItemEntry.timestamp.desc())

    if db is not None:
        return list(db.execute(query).scalars().all())
    with get_db() as db_session:
        return list(db_session.execute(query).scalars().all())

def create_pick_item_entry(
    sku: str,
    qty: int,
    username: str,
    order_sn: Optional[str] = None,
) -> PickItemEntry:
    item = resolve_barcode_to_item(sku)
    if not item:
        raise LookupError(f"Item with SKU or barcode '{sku}' not found")
    resolved_sku = item.sku

    return merge_or_create_pie(
        sku=resolved_sku, qty=qty, order_sn=order_sn, username=username
    )

def assign_pick_item_entry(
    entry_id: int, order_sn: str, qty: Optional[int], username: str
) -> PickItemEntry:
    with get_db() as db:
        entries = get_pie_data(username=username, entry_id=entry_id, db=db)
        entry = entries[0] if entries else None

        order = (
            db.execute(
                select(ShopeeOrder).filter(
                    ShopeeOrder.order_sn == order_sn,
                    ShopeeOrder.owner_user == username,
                )
            )
            .scalars()
            .first()
        )

        if not entry or not order:
            raise LookupError("Entry or Order not found")

        sku = entry.sku
        total_qty = entry.qty or 0

        assign_qty = qty if qty is not None else total_qty
        assign_qty = min(assign_qty, total_qty)

        if assign_qty <= 0:
            raise ValueError("Invalid quantity")

        if assign_qty >= total_qty:
            db.delete(entry)
        else:
            entry.qty -= assign_qty

        db.commit()

    return merge_or_create_pie(
        sku=sku, qty=assign_qty, order_sn=order_sn, username=username
    )

def unassign_pick_item_entry(order_sn: str, sku: str, qty: int, username: str) -> bool:
    with get_db() as db:
        entries = get_pie_data(username=username, sku=sku, order_sn=order_sn, db=db)
        entry = entries[0] if entries else None

        if not entry:
            raise LookupError("Entry not found")

        take_qty = min(qty, entry.qty or 0)
        entry.qty = (entry.qty or 0) - take_qty
        if entry.qty <= 0:
            db.delete(entry)

        db.commit()

    merge_or_create_pie(sku=sku, qty=take_qty, order_sn=None, username=username)
    return True

def delete_pie(pie_id: int, username: str, is_admin: bool = False) -> bool:
    with get_db() as db:
        query = select(PickItemEntry).filter(PickItemEntry.id == pie_id)
        if not is_admin:
            query = query.filter(PickItemEntry.owner_user == username)

        pie = db.execute(query).scalars().first()
        if not pie:
            return False

        db.delete(pie)
        db.commit()
        return True
