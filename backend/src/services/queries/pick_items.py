"""Pick entries on top of the inventory engine (T4.2 unit of work, T4.3 allocations).

Every public function is one transaction: it commits once at the end or changes nothing.
Lock order: the pick entry, then its allocations, then stock rows (see queries/stocks.py).
"""

import logging
from datetime import UTC, datetime
from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from ...models import PickItemEntry, PickStockAllocation, ShopeeOrder, StocksLog
from .engine import get_db
from .stocks import deduct_for_pick, move_pick_quantity, restore_for_pick
from .warehouse import resolve_barcode_to_item

logger = logging.getLogger("backend.services.queries.pick_items")


class OrderClosedError(ValueError):
    """The order exists and belongs to the caller but is already done (HTTP 409)."""


def _active_order(db: Session, order_sn: str, username: str) -> ShopeeOrder:
    """F-M8: picks may only target an existing, unfinished order owned by the caller."""
    order = db.execute(
        select(ShopeeOrder).filter(
            ShopeeOrder.order_sn == order_sn, ShopeeOrder.owner_user == username
        )
    ).scalar_one_or_none()
    if order is None:
        raise LookupError("Order not found or not claimed by you")
    if order.done:
        raise OrderClosedError("Order already completed")
    return order


def _locked_entry(db: Session, **filters) -> Optional[PickItemEntry]:
    query = select(PickItemEntry).options(selectinload(PickItemEntry.allocations))
    for column, value in filters.items():
        query = query.filter(getattr(PickItemEntry, column) == value)
    return (
        db.execute(query.order_by(PickItemEntry.id).with_for_update(of=PickItemEntry))
        .scalars()
        .first()
    )


def _entry_for(db: Session, sku: str, order_sn: Optional[str], username: str) -> PickItemEntry:
    entry = _locked_entry(db, sku=sku, order_sn=order_sn, owner_user=username)
    if entry is None:
        entry = PickItemEntry(sku=sku, qty=0, order_sn=order_sn, owner_user=username)
        db.add(entry)
        db.flush()
    entry.timestamp = datetime.now(UTC)
    return entry


def _commit(db: Session, entry: Optional[PickItemEntry] = None):
    db.commit()
    if entry is not None:
        db.refresh(entry)
        _ = entry.allocations  # load while bound; callers use the detached record
    return entry


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
    with get_db() as db:
        if order_sn is not None:
            _active_order(db, order_sn, username)
        entry = _entry_for(db, item.sku, order_sn, username)
        entry.qty += qty
        deduct_for_pick(db, entry, qty, actor=username)
        return _commit(db, entry)


def assign_pick_item_entry(
    entry_id: int, order_sn: str, qty: Optional[int], username: str
) -> PickItemEntry:
    with get_db() as db:
        entry = _locked_entry(db, id=entry_id, owner_user=username)
        if entry is None:
            raise LookupError("Entry or Order not found")
        _active_order(db, order_sn, username)

        total_qty = entry.qty or 0
        assign_qty = min(qty if qty is not None else total_qty, total_qty)
        if assign_qty <= 0:
            raise ValueError("Invalid quantity")
        if entry.order_sn == order_sn:
            return _commit(db, entry)

        target = _entry_for(db, entry.sku, order_sn, username)
        move_pick_quantity(db, entry, target, assign_qty)
        if entry.qty <= 0:
            db.delete(entry)
        return _commit(db, target)


def unassign_pick_item_entry(order_sn: str, sku: str, qty: int, username: str) -> bool:
    with get_db() as db:
        entry = _locked_entry(db, sku=sku, order_sn=order_sn, owner_user=username)
        if entry is None:
            raise LookupError("Entry not found")
        take_qty = min(qty, entry.qty or 0)
        target = _entry_for(db, sku, None, username)
        move_pick_quantity(db, entry, target, take_qty)
        if entry.qty <= 0:
            db.delete(entry)
        if target.qty <= 0:
            db.delete(target)
        _commit(db)
    return True


def delete_pie(pie_id: int, username: str, is_admin: bool = False) -> bool:
    """Delete an entry and return its allocated stock (D1.4.2). The actor is the deleting
    user, also when an admin deletes someone else's entry."""
    with get_db() as db:
        filters = {"id": pie_id} if is_admin else {"id": pie_id, "owner_user": username}
        entry = _locked_entry(db, **filters)
        if entry is None:
            return False
        restore_for_pick(db, entry, actor=username)
        db.delete(entry)
        _commit(db)
        return True


def clear_open_pick_entries(actor: str) -> int:
    """T4.4 / D5 cutover: delete all pick entries WITHOUT restoring stock."""
    with get_db() as db:
        count = db.execute(select(func.count()).select_from(PickItemEntry)).scalar_one()
        db.execute(delete(PickStockAllocation))
        db.execute(delete(PickItemEntry))
        db.add(
            StocksLog(
                message=f"cutover_clear: deleted {count} open pick entries without restoring stock",
                delta=0,
                reason="cutover_clear",
                actor=actor,
                ref_type="pick_entries",
                ref_id=str(count),
            )
        )
        db.commit()
        return count
