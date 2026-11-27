"""Tasks: work an admin hands to a worker (V2_TASKS_SPEC, V2_TASKS_DELTA, IMPLEMENTATION_PLAN T9.1).

Two types in round 1 (T5):

* **count**: one SKU, and its bin in ``multi`` mode. The worker's count runs
  ``apply_stock_update(set)`` referenced to the task; in ``single`` mode without a location,
  so a count never merges stock from elsewhere (P-29, R1.5). The count completes the task.
* **pick**: lines of internal SKUs (bundles allowed). The BOM leaves are snapshotted at
  creation (P-28) as ``leaf`` lines; picks go through the pick engine (``deduct_for_pick``,
  ``restore_pick_quantity``) as pick entries linked to their leaf line. The task is done once
  every leaf is picked exactly (``is_picked``, the R4.3 rule).

Statuses (P-31): ``open`` → ``done`` (implicit), ``open`` → ``blocked`` (the worker can't finish),
``open``/``blocked`` → ``cancelled`` (admin, returning or keeping picked stock, T9), ``blocked`` →
``done`` (admin "close as picked", T8), and a reassign (``open``/``blocked`` → ``open`` for another
worker; picks move with the task, T12). Only the assigned worker works a task. Claimed orders
are tasks too, but derived in the routes, never stored here (P-30).

Every public function is one transaction. Lock order: the task, its pick entries, their
allocations, then stock rows (as queries/pick_items.py, with the task in the order's place).
Stock log rows of a task's changes carry ``ref_type="task"`` and its id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...config import stock_location_mode
from ...models import PickItemEntry, StocksLog, Task, TaskLine, User, WarehouseItem
from ..order_payload import expand_lines
from .engine import get_db
from .pick_items import PickQuantityError
from .stocks import (
    _clean,
    apply_stock_update,
    deduct_for_pick,
    pick_ref,
    restore_for_pick,
    restore_pick_quantity,
)
from .warehouse import resolve_barcode_to_item

logger = logging.getLogger("backend.services.queries.tasks")

WORKABLE = ("open",)
ADMIN_CLOSABLE = ("open", "blocked")


class TaskStateError(ValueError):
    """The task is not in a state that allows this (HTTP 409)."""


class TaskScanError(ValueError):
    """The scanned item or location is not the task's (HTTP 409); nothing changes."""


@dataclass
class PickResult:
    """What a pick task has of one leaf after a pick or unassign."""

    task_id: int
    sku: str
    qty: int  # picked now
    required: int
    item_name: Optional[str]
    status: str


# --------------------------------------------------------------------------- helpers
def is_picked(required: dict[str, int], picked: dict[str, int]) -> bool:
    """R4.3: every required SKU picked exactly, and nothing else picked."""
    wanted = {sku: qty for sku, qty in required.items() if qty}
    have = {sku: qty for sku, qty in picked.items() if qty}
    return bool(wanted) and wanted == have


def _now() -> datetime:
    return datetime.now(UTC)


def _worker(db: Session, username: str) -> User:
    user = db.get(User, username)
    if user is None or user.scope == "admin":
        raise LookupError(f"Worker '{username}' not found")
    return user


def _item(db: Session, sku: str) -> WarehouseItem:
    item = db.get(WarehouseItem, (sku or "").strip())
    if item is None:
        raise LookupError(f"Item '{sku}' not found")
    return item


def _locked_task(db: Session, task_id: int) -> Task:
    task = db.execute(select(Task).where(Task.id == task_id).with_for_update()).scalar_one_or_none()
    if task is None:
        raise LookupError("Task not found")
    return task


def _worker_task(db: Session, task_id: int, username: str, task_type: str) -> Task:
    """The caller's open task of ``task_type``, locked. Another worker's task is 'not found'."""
    task = _locked_task(db, task_id)
    if task.assigned_to != username:
        raise LookupError("Task not found or not assigned to you")
    if task.type != task_type:
        raise TaskStateError(f"Task {task_id} is a {task.type} task")
    if task.status not in WORKABLE:
        raise TaskStateError(f"Task is {task.status}")
    return task


def _entries(db: Session, task: Task) -> list[PickItemEntry]:
    """The task's pick entries, locked, in lock order (sku, id)."""
    line_ids = [line.id for line in task.lines if line.kind == "leaf"]
    if not line_ids:
        return []
    return list(
        db.execute(
            select(PickItemEntry)
            .options(selectinload(PickItemEntry.allocations))
            .where(PickItemEntry.task_line_id.in_(line_ids))
            .order_by(PickItemEntry.sku, PickItemEntry.id)
            .with_for_update(of=PickItemEntry)
        )
        .scalars()
        .all()
    )


def _required(task: Task) -> dict[str, int]:
    return {line.sku: line.qty or 0 for line in task.lines if line.kind == "leaf"}


def _close(task: Task, status: str, actor: str) -> None:
    task.status = status
    task.closed_at = _now()
    task.closed_by = actor


def _commit(db: Session, task: Task) -> Task:
    db.commit()
    db.refresh(task)
    _ = task.lines  # loaded while bound; callers use the detached record
    return task


# --------------------------------------------------------------------------- create
def create_count_task(
    sku: str,
    assigned_to: str,
    created_by: str,
    location: Optional[str] = None,
    note: Optional[str] = None,
) -> Task:
    """In ``multi`` mode the bin is required; in ``single`` mode none is taken (P-29)."""
    location = _clean(location)
    single = stock_location_mode() == "single"
    if single and location is not None:
        raise ValueError("In single location mode a count takes the item only, no location")
    if not single and location is None:
        raise ValueError("A count needs a location in multi location mode")
    with get_db() as db:
        worker = _worker(db, assigned_to)
        item = _item(db, sku)
        task = Task(
            type="count",
            status="open",
            assigned_to=worker.username,
            assigned_name=worker.username,
            created_by=created_by,
            note=note,
        )
        task.lines.append(TaskLine(kind="count", sku=item.sku, location=location))
        db.add(task)
        return _commit(db, task)


def create_pick_task(
    lines: Iterable[tuple[str, int]],
    assigned_to: str,
    created_by: str,
    reference: Optional[str] = None,
    note: Optional[str] = None,
) -> Task:
    """``lines`` are internal SKUs (a bundle is expanded by the standard BOM) and quantities.
    The leaves are stored now, so a later BOM change does not change the task (P-28)."""
    lines = list(lines)
    if not lines:
        raise ValueError("A pick task needs at least one line")
    if any(qty <= 0 for _, qty in lines):
        raise ValueError("Quantities must be positive")
    with get_db() as db:
        worker = _worker(db, assigned_to)
        entered = [(_item(db, sku).sku, qty) for sku, qty in lines]
        leaves = [(sku, qty) for sku, qty in expand_lines(db, entered) if qty > 0]
        if not leaves:
            raise ValueError("The lines expand to nothing to pick")
        task = Task(
            type="pick",
            status="open",
            assigned_to=worker.username,
            assigned_name=worker.username,
            created_by=created_by,
            reference=reference,
            note=note,
        )
        for sku, qty in entered:
            task.lines.append(TaskLine(kind="entered", sku=sku, qty=qty))
        for sku, qty in leaves:
            task.lines.append(TaskLine(kind="leaf", sku=sku, qty=qty))
        db.add(task)
        return _commit(db, task)


# ----------------------------------------------------------------------------- read
def list_tasks(
    assigned_to: Optional[str] = None,
    task_type: Optional[str] = None,
    statuses: Optional[Iterable[str]] = None,
) -> list[Task]:
    """Oldest first (T11)."""
    query = select(Task).order_by(Task.created_at, Task.id)
    if assigned_to is not None:
        query = query.where(Task.assigned_to == assigned_to)
    if task_type is not None:
        query = query.where(Task.type == task_type)
    if statuses is not None:
        query = query.where(Task.status.in_(list(statuses)))
    with get_db() as db:
        return list(db.execute(query).scalars().all())


def get_task(task_id: int) -> Optional[Task]:
    with get_db() as db:
        return db.get(Task, task_id)


def picked_quantities(task_ids: Iterable[int]) -> dict[int, dict[str, int]]:
    """``{task_id: {sku: picked}}`` for pick tasks (progress, the derived "in progress")."""
    task_ids = list(task_ids)
    if not task_ids:
        return {}
    with get_db() as db:
        rows = db.execute(
            select(TaskLine.task_id, PickItemEntry.sku, PickItemEntry.qty)
            .join(PickItemEntry, PickItemEntry.task_line_id == TaskLine.id)
            .where(TaskLine.task_id.in_(task_ids))
        ).all()
    result: dict[int, dict[str, int]] = {}
    for task_id, sku, qty in rows:
        per_task = result.setdefault(task_id, {})
        per_task[sku] = per_task.get(sku, 0) + qty
    return result


def task_stock_log(task_id: int) -> list[StocksLog]:
    """Every stock log row the task caused, oldest first (the console's detail)."""
    with get_db() as db:
        return list(
            db.execute(
                select(StocksLog)
                .where(StocksLog.ref_type == "task", StocksLog.ref_id == str(task_id))
                .order_by(StocksLog.id)
            )
            .scalars()
            .all()
        )


# --------------------------------------------------------------------------- worker
def count_task(
    task_id: int, username: str, item_scan: str, qty: int, location_scan: Optional[str] = None
) -> Task:
    """Record the worker's count: ``set`` the counted quantity and complete the task.

    The scanned item must be the task's SKU. The scanned location, when given, must be the
    task's bin (``multi``) or the item's current location (``single``, when it has one); in
    ``multi`` mode it is required."""
    if qty < 0:
        raise ValueError("Stock quantity cannot be negative")
    item = resolve_barcode_to_item(item_scan)
    with get_db() as db:
        task = _worker_task(db, task_id, username, "count")
        line = task.lines[0]
        if item is None or item.sku != line.sku:
            raise TaskScanError(f"Wrong item: this task counts {line.sku}")
        scanned = _clean(location_scan)
        if stock_location_mode() == "single":
            expected = item.location  # derived from the bins; one in single mode
            if scanned is not None and expected is not None and scanned != expected:
                raise TaskScanError(f"Wrong location: {line.sku} is at {expected}")
            location = None  # never merge into a scanned location (P-29)
        else:
            if scanned != line.location:
                raise TaskScanError(f"Wrong location: this task counts bin {line.location}")
            location = line.location
        apply_stock_update(
            db,
            line.sku,
            qty,
            username,
            mode="set",
            location=location,
            ref_type="task",
            ref_id=str(task.id),
        )
        line.counted_qty = qty
        _close(task, "done", username)
        return _commit(db, task)


def _leaf(task: Task, sku: str) -> TaskLine:
    for line in task.lines:
        if line.kind == "leaf" and line.sku == sku:
            return line
    raise TaskScanError(f"{sku} is not on this task")


def _result(task: Task, line: TaskLine, qty: int, item_name: Optional[str]) -> PickResult:
    return PickResult(task.id, line.sku, qty, line.qty or 0, item_name, task.status)


def pick_for_task(task_id: int, username: str, sku: str, qty: int) -> PickResult:
    """Pick ``qty`` of a scanned SKU or barcode into the task. Over-picking is allowed (the
    apps warn, as for orders), but then the task is not done until it is unassigned back."""
    if qty <= 0:
        raise ValueError("Invalid quantity")
    item = resolve_barcode_to_item(sku)
    if item is None:
        raise LookupError(f"Item with SKU or barcode '{sku}' not found")
    with get_db() as db:
        task = _worker_task(db, task_id, username, "pick")
        line = _leaf(task, item.sku)
        entries = _entries(db, task)
        entry = next((e for e in entries if e.task_line_id == line.id), None)
        if entry is None:
            entry = PickItemEntry(sku=line.sku, qty=0, owner_user=username, task_line_id=line.id)
            db.add(entry)
            db.flush()
        entry.qty += qty
        entry.owner_user = username
        entry.timestamp = _now()
        deduct_for_pick(db, entry, qty, actor=username)
        picked = {e.sku: e.qty for e in entries}
        picked[entry.sku] = entry.qty
        if is_picked(_required(task), picked):
            _close(task, "done", username)
        result = _result(task, line, entry.qty, item.item_name)
        db.commit()
        return result


def unassign_from_task(task_id: int, username: str, sku: str, qty: int) -> PickResult:
    """Take ``qty`` of a picked SKU off an open task and return it to stock. Undoing an
    over-pick down to the exact quantities completes the task."""
    with get_db() as db:
        task = _worker_task(db, task_id, username, "pick")
        line = _leaf(task, sku)
        entries = _entries(db, task)
        entry = next((e for e in entries if e.task_line_id == line.id), None)
        if entry is None:
            raise LookupError(f"Nothing of {sku} is picked for this task")
        if qty > entry.qty:
            raise PickQuantityError(f"Only {entry.qty} of {sku} picked, {qty} requested")
        left = entry.qty - qty
        entry.timestamp = _now()
        restore_pick_quantity(db, entry, qty, actor=username)
        picked = {e.sku: e.qty for e in entries}
        picked[sku] = left
        if is_picked(_required(task), picked):
            _close(task, "done", username)
        result = _result(task, line, left, None)
        db.commit()
    found = resolve_barcode_to_item(sku)
    result.item_name = found.item_name if found else None
    return result


def block_task(task_id: int, username: str, reason: str) -> Task:
    """The worker can't finish (T7): ``open`` → ``blocked`` with a reason."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reason is required")
    with get_db() as db:
        task = _locked_task(db, task_id)
        if task.assigned_to != username:
            raise LookupError("Task not found or not assigned to you")
        if task.status != "open":
            raise TaskStateError(f"Task is {task.status}")
        task.status = "blocked"
        task.blocked_reason = reason
        return _commit(db, task)


# ---------------------------------------------------------------------------- admin
def cancel_task(task_id: int, actor: str, return_stock: bool = True) -> Task:
    """Cancel an open or blocked task (T9). With ``return_stock`` its picks are returned and
    deleted, as unassigning would; without, they stay deducted (the goods already left) and
    a ``task_cancel_keep`` row records it. Logged either way."""
    with get_db() as db:
        task = _locked_task(db, task_id)
        if task.status not in ADMIN_CLOSABLE:
            raise TaskStateError(f"Task is {task.status}")
        entries = _entries(db, task)
        for entry in entries:
            if return_stock:
                restore_for_pick(db, entry, actor=actor)
                db.delete(entry)
            else:
                db.add(
                    StocksLog(
                        message=(
                            f"task_cancel_keep: sku={entry.sku}, qty={entry.qty}, "
                            f"task={task.id}, user={actor}"
                        ),
                        sku=entry.sku,
                        delta=0,
                        reason="task_cancel_keep",
                        actor=actor,
                        **pick_ref(db, entry),
                    )
                )
        _close(task, "cancelled", actor)
        return _commit(db, task)


def reassign_task(task_id: int, assigned_to: str, actor: str) -> Task:
    """Give an open or blocked task to another worker (or the same one again); it becomes
    ``open``. Its picks move with it (T12): the task owns them, not the worker."""
    with get_db() as db:
        task = _locked_task(db, task_id)
        if task.status not in ADMIN_CLOSABLE:
            raise TaskStateError(f"Task is {task.status}")
        worker = _worker(db, assigned_to)
        for entry in _entries(db, task):
            entry.owner_user = worker.username
        task.assigned_to = worker.username
        task.assigned_name = worker.username
        task.status = "open"
        task.blocked_reason = None
        logger.info(
            "task_reassigned", extra={"task_id": task.id, "to": worker.username, "actor": actor}
        )
        return _commit(db, task)


def close_as_picked(task_id: int, actor: str) -> Task:
    """T8: an admin closes a blocked pick task as done with what was picked."""
    with get_db() as db:
        task = _locked_task(db, task_id)
        if task.type != "pick":
            raise TaskStateError("Only a pick task can be closed as picked")
        if task.status != "blocked":
            raise TaskStateError(f"Task is {task.status}; only a blocked task can be closed")
        _entries(db, task)  # lock the picks it keeps
        _close(task, "done", actor)
        return _commit(db, task)
