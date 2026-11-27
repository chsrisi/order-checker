"""Tasks over HTTP and WebSocket (IMPLEMENTATION_PLAN T9.2; queries/tasks.py holds the rules).

``tasks_update`` goes to the assigned worker's **v2** sockets and to admins; v1 operator sockets
never get it (V2_TASKS_SPEC §8). Its ``data`` is a snapshot, a list of task objects: a worker
gets their open and blocked tasks, admins the console's default list (open and blocked, plus
tasks closed in the last ``RECENT_CLOSED_DAYS``). Order-tasks are not in it: they follow the
order and pick events the apps already get, and ``GET /v2/tasks`` / ``GET /admin/order-tasks``
derive them on request (P-30).

Each query is one transaction; events are published after it committed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Iterable, Optional

from ..exceptions import DomainException
from ..models import (
    AdminTaskDetailResponse,
    OrderTaskResponse,
    Task,
    TaskLineResponse,
    TaskPickResponse,
    TaskResponse,
    TaskStockLogResponse,
    V2TaskListResponse,
    WSMessageType,
)
from . import queries
from .managers import conn_mgr
from .queries import tasks as task_queries
from .shopee_service import build_shopee_order_responses

logger = logging.getLogger("backend.services.task")

RECENT_CLOSED_DAYS = 7
WORKER_STATUSES = ("open", "blocked")

# ------------------------------------------------------------------------- payloads


def build_task_responses(tasks: list[Task]) -> list[TaskResponse]:
    picked = task_queries.picked_quantities(t.id for t in tasks if t.type == "pick")
    skus = {line.sku for t in tasks for line in t.lines}
    names = queries.item_names_for(skus)
    locations = _current_locations({t.lines[0].sku for t in tasks if t.type == "count"})
    responses = []
    for task in tasks:
        per_sku = picked.get(task.id, {})
        lines = [
            TaskLineResponse(
                id=line.id,
                kind=line.kind,
                sku=line.sku,
                item_name=names.get(line.sku),
                qty=line.qty,
                location=line.location,
                picked=per_sku.get(line.sku, 0) if line.kind == "leaf" else None,
                counted_qty=line.counted_qty,
            )
            for line in task.lines
        ]
        responses.append(
            TaskResponse(
                id=task.id,
                type=task.type,
                status=task.status,
                in_progress=any(per_sku.values()),
                assigned_to=task.assigned_to,
                assigned_name=task.assigned_name,
                created_by=task.created_by,
                created_at=task.created_at,
                note=task.note,
                reference=task.reference,
                blocked_reason=task.blocked_reason,
                closed_at=task.closed_at,
                closed_by=task.closed_by,
                current_location=(
                    locations.get(task.lines[0].sku) if task.type == "count" else None
                ),
                lines=lines,
            )
        )
    return responses


def _current_locations(skus: set[str]) -> dict[str, Optional[str]]:
    return {sku: item.location for sku in skus if (item := queries.resolve_barcode_to_item(sku))}


def worker_tasks(username: str) -> list[TaskResponse]:
    return build_task_responses(
        task_queries.list_tasks(assigned_to=username, statuses=WORKER_STATUSES)
    )


def admin_tasks(
    assigned_to: Optional[str] = None,
    task_type: Optional[str] = None,
    statuses: Optional[Iterable[str]] = None,
) -> list[TaskResponse]:
    """Without ``statuses``: open and blocked, plus those closed in the last week."""
    statuses = list(statuses) if statuses else None
    closed_since = None if statuses else datetime.now(UTC) - timedelta(days=RECENT_CLOSED_DAYS)
    return build_task_responses(
        task_queries.list_tasks(assigned_to, task_type, statuses, closed_since=closed_since)
    )


def task_detail(task_id: int) -> AdminTaskDetailResponse:
    task = task_queries.get_task(task_id)
    if task is None:
        raise DomainException(status_code=404, detail="Task not found")
    (base,) = build_task_responses([task])
    log = task_queries.task_stock_log(task_id)
    recorded = difference = None
    counted = next((r for r in log if r.reason == "adjust_set"), None)
    if task.type == "count" and counted is not None:
        recorded, difference = counted.before, (counted.after or 0) - (counted.before or 0)
    return AdminTaskDetailResponse(
        **base.model_dump(),
        stock_log=[TaskStockLogResponse.model_validate(r) for r in log],
        recorded_before=recorded,
        difference=difference,
    )


def order_tasks(username: Optional[str] = None) -> list[OrderTaskResponse]:
    """Claimed active orders not yet *Picked* (R4.3, as the apps compute it): every required
    SKU exact and none extra. ``username`` None: every worker's (the console)."""
    orders = (
        queries.get_shopee_order_data(username)
        if username is not None
        else [o for o in queries.get_all_shopee_order_data() if o.owner_user]
    )
    if not orders:
        return []
    picks: dict[str, dict[str, int]] = {}
    for entry in queries.get_pie_data(username=username):
        if entry.order_sn:
            per_order = picks.setdefault(entry.order_sn, {})
            per_order[entry.sku] = per_order.get(entry.sku, 0) + entry.qty
    result = []
    for order, payload in zip(orders, build_shopee_order_responses(orders)):
        required: dict[str, int] = {}
        for component in payload.item_list:
            sku = component.component_sku or "unknown"
            required[sku] = required.get(sku, 0) + component.quantity
        picked = picks.get(order.order_sn, {})
        done = sum(1 for sku, qty in required.items() if picked.get(sku, 0) == qty)
        extra = any(qty and sku not in required for sku, qty in picked.items())
        if not extra and picked and done == len(required):
            continue  # Picked: no longer a task
        state = "extra" if extra else ("not_started" if not picked else "partial")
        result.append(
            OrderTaskResponse(
                order_sn=order.order_sn,
                owner_user=order.owner_user,
                ship_by=order.ship_by,
                status=order.status,
                state=state,
                done_skus=done,
                required_skus=len(required),
            )
        )
    result.sort(key=lambda o: o.ship_by)
    return result


def v2_task_list(username: str) -> V2TaskListResponse:
    return V2TaskListResponse(tasks=worker_tasks(username), order_tasks=order_tasks(username))


# --------------------------------------------------------------------------- events
async def _notify(*workers: Optional[str], stocks: bool = False) -> None:
    for worker in dict.fromkeys(w for w in workers if w):
        await conn_mgr.send_to_user(WSMessageType.TASKS, username=worker, min_contract=2)
    await conn_mgr.broadcast(WSMessageType.TASKS, scope="admin")
    if stocks:
        await conn_mgr.broadcast(WSMessageType.STOCKS)


async def _run(query, *args, **kwargs):
    try:
        return await asyncio.to_thread(query, *args, **kwargs)
    except LookupError as e:
        raise DomainException(status_code=404, detail=str(e))
    except (
        task_queries.TaskStateError,
        task_queries.TaskScanError,
        queries.InsufficientStockError,
        queries.PickQuantityError,
    ) as e:
        raise DomainException(status_code=409, detail=str(e))
    except ValueError as e:
        raise DomainException(status_code=400, detail=str(e))


async def _one(task: Task) -> TaskResponse:
    return (await asyncio.to_thread(build_task_responses, [task]))[0]


# ---------------------------------------------------------------------------- admin
async def create_count(sku, assigned_to, actor, location=None, note=None) -> TaskResponse:
    task = await _run(task_queries.create_count_task, sku, assigned_to, actor, location, note)
    await _notify(task.assigned_to)
    return await _one(task)


async def create_pick(lines, assigned_to, actor, reference=None, note=None) -> TaskResponse:
    task = await _run(task_queries.create_pick_task, lines, assigned_to, actor, reference, note)
    await _notify(task.assigned_to)
    return await _one(task)


async def cancel(task_id: int, actor: str, return_stock: bool) -> TaskResponse:
    task = await _run(task_queries.cancel_task, task_id, actor, return_stock)
    await _notify(task.assigned_to, stocks=return_stock)
    return await _one(task)


async def reassign(task_id: int, assigned_to: str, actor: str) -> TaskResponse:
    before = await asyncio.to_thread(task_queries.get_task, task_id)
    task = await _run(task_queries.reassign_task, task_id, assigned_to, actor)
    await _notify(before.assigned_to if before else None, task.assigned_to)
    return await _one(task)


async def close_as_picked(task_id: int, actor: str) -> TaskResponse:
    task = await _run(task_queries.close_as_picked, task_id, actor)
    await _notify(task.assigned_to)
    return await _one(task)


# --------------------------------------------------------------------------- worker
async def count(task_id: int, username: str, sku: str, qty: int, location: Optional[str]):
    task = await _run(task_queries.count_task, task_id, username, sku, qty, location)
    await _notify(username, stocks=True)
    return await _one(task)


async def pick(task_id: int, username: str, sku: str, qty: int) -> TaskPickResponse:
    result = await _run(task_queries.pick_for_task, task_id, username, sku, qty)
    await _notify(username, stocks=True)
    return TaskPickResponse(**vars(result))


async def unassign(task_id: int, username: str, sku: str, qty: int) -> TaskPickResponse:
    result = await _run(task_queries.unassign_from_task, task_id, username, sku, qty)
    await _notify(username, stocks=True)
    return TaskPickResponse(**vars(result))


async def block(task_id: int, username: str, reason: str) -> TaskResponse:
    task = await _run(task_queries.block_task, task_id, username, reason)
    await _notify(username)
    return await _one(task)
