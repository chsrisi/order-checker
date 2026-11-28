"""Pick entries on top of the inventory engine (T4.2 unit of work, T4.3 allocations).

Every public function is one transaction: it commits once at the end or changes nothing.
Lock order: the order (contract v2 only), the pick entry, its allocations, then stock rows (see
queries/stocks.py).

Two models share the table until v1 retires (V2_PICKING_DELTA): contract v1 keeps a pool of
entries without an order (``create/assign/unassign_pick_item_entry``, ``delete_pie``); contract
v2 picks straight into an order and returns stock on unassign (``pick_for_order``,
``unassign_from_order``) and never writes ``order_sn = NULL``.

Task picks (``task_line_id`` set, queries/tasks.py) share the table and the stock engine but
none of these paths: every query here filters them out (``NOT_TASK``), so they are never
unassigned picks, never in a v1 or order payload and never released (V2_TASKS_SPEC §8).
"""

import logging
from datetime import UTC, datetime
from typing import List, NamedTuple, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from ...models import PickItemEntry, PickStockAllocation, ShopeeOrder, StocksLog
from .engine import get_db
from .orders import ACTIVE_ORDER_STATUSES
from .stocks import deduct_for_pick, move_pick_quantity, restore_for_pick, restore_pick_quantity
from .warehouse import resolve_barcode_to_item

logger = logging.getLogger("backend.services.queries.pick_items")

# Order and v1 picks only: task picks stay out of every path in this module.
NOT_TASK = PickItemEntry.task_line_id.is_(None)


class OrderLine(NamedTuple):
    """What an order has of one SKU after a v2 pick or unassign (``qty`` 0: nothing left)."""

    order_sn: str
    sku: str
    qty: int
    item_name: Optional[str]


class OrderClosedError(ValueError):
    """The order exists and belongs to the caller but is already done (HTTP 409)."""


class PickQuantityError(ValueError):
    """More than is picked was to be removed; nothing changes (HTTP 409)."""


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
    query = select(PickItemEntry).options(selectinload(PickItemEntry.allocations)).filter(NOT_TASK)
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
    query = select(PickItemEntry).filter(NOT_TASK)
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


# ----------------------------------------------------------------------- contract v2
def _lock_claimed_order(db: Session, order_sn: str, username: str) -> str:
    """Lock the caller's unfinished order and return its Shopee status. The lock serializes
    picks, unassigns and closes of one order, so a first pick cannot race into two entries and
    nothing changes behind a close. ``NO KEY UPDATE`` does not block foreign-key checks."""
    order = db.execute(
        select(ShopeeOrder.owner_user, ShopeeOrder.done, ShopeeOrder.status)
        .where(ShopeeOrder.order_sn == order_sn)
        .with_for_update(key_share=True)
    ).first()
    if order is None or order.owner_user != username:
        raise LookupError("Order not found or not claimed by you")
    if order.done:
        raise OrderClosedError("Order already completed")
    return order.status


def _order_line(db: Session, order_sn: str, sku: str, username: str) -> Optional[PickItemEntry]:
    """The order's entry for ``sku``, locked. v1 can have raced in a duplicate: merge it."""
    rows = (
        db.execute(
            select(PickItemEntry)
            .options(selectinload(PickItemEntry.allocations))
            .filter(
                PickItemEntry.order_sn == order_sn,
                PickItemEntry.sku == sku,
                PickItemEntry.owner_user == username,
                NOT_TASK,
            )
            .order_by(PickItemEntry.id)
            .with_for_update(of=PickItemEntry)
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    line = rows[0]
    for duplicate in rows[1:]:
        move_pick_quantity(db, duplicate, line, duplicate.qty)
        db.delete(duplicate)
    return line


def pick_for_order(order_sn: str, sku: str, qty: int, username: str) -> OrderLine:
    """Pick ``qty`` of a scanned SKU or barcode straight into an order."""
    item = resolve_barcode_to_item(sku)
    if not item:
        raise LookupError(f"Item with SKU or barcode '{sku}' not found")
    with get_db() as db:
        status = _lock_claimed_order(db, order_sn, username)
        if status not in ACTIVE_ORDER_STATUSES:
            raise OrderClosedError(f"Order is {status} on Shopee: picking is closed")
        line = _order_line(db, order_sn, item.sku, username) or _entry_for(
            db, item.sku, order_sn, username
        )
        line.qty += qty
        line.timestamp = datetime.now(UTC)
        deduct_for_pick(db, line, qty, actor=username)
        result = OrderLine(order_sn, item.sku, line.qty, item.item_name)
        db.commit()
        return result


def unassign_from_order(order_sn: str, sku: str, qty: int, username: str) -> OrderLine:
    """Take ``qty`` of a picked SKU off an order and return it to stock. Allowed on an order
    Shopee cancelled (its goods come back), not on a completed one."""
    with get_db() as db:
        _lock_claimed_order(db, order_sn, username)
        line = _order_line(db, order_sn, sku, username)
        if line is None:
            raise LookupError(f"Nothing of {sku} is picked for this order")
        if qty > line.qty:
            raise PickQuantityError(f"Only {line.qty} of {sku} picked, {qty} requested")
        left = line.qty - qty
        line.timestamp = datetime.now(UTC)
        restore_pick_quantity(db, line, qty, actor=username)
        db.commit()
    item = resolve_barcode_to_item(sku)
    return OrderLine(order_sn, sku, left, item.item_name if item else None)


# ------------------------------------------------------------------------ maintenance
def count_unassigned_picks() -> int:
    with get_db() as db:
        return db.execute(
            select(func.count())
            .select_from(PickItemEntry)
            .where(PickItemEntry.order_sn.is_(None), NOT_TASK)
        ).scalar_one()


def release_unassigned_picks(actor: str) -> int:
    """Delete every entry without an order and return its stock (V2_PICKING_SPEC §4.5)."""
    with get_db() as db:
        entries = (
            db.execute(
                select(PickItemEntry)
                .where(PickItemEntry.order_sn.is_(None), NOT_TASK)
                .order_by(PickItemEntry.sku, PickItemEntry.id)
                .with_for_update(of=PickItemEntry)
            )
            .scalars()
            .all()
        )
        for entry in entries:
            restore_for_pick(db, entry, actor=actor)
            db.delete(entry)
        db.commit()
        return len(entries)


def clear_open_pick_entries(actor: str) -> int:
    """T4.4 / D5 cutover: delete all order and v1 pick entries WITHOUT restoring stock. Task
    picks are kept: they belong to their task."""
    with get_db() as db:
        count = db.execute(
            select(func.count()).select_from(PickItemEntry).where(NOT_TASK)
        ).scalar_one()
        entry_ids = select(PickItemEntry.id).where(NOT_TASK)
        db.execute(
            delete(PickStockAllocation).where(PickStockAllocation.pick_entry_id.in_(entry_ids))
        )
        db.execute(delete(PickItemEntry).where(NOT_TASK))
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
