"""Admin task routes (IMPLEMENTATION_PLAN T9.2, V2_TASKS_SPEC §6): create, list, detail, cancel,
reassign, close as picked; claimed orders as read-only order-tasks. Mounted under ``/admin``."""

from __future__ import annotations

import asyncio
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Path, Query

from ..dependencies import require_admin
from ..models import (
    AdminTaskDetailResponse,
    OrderTaskResponse,
    TaskCancelRequest,
    TaskCountCreate,
    TaskPickCreate,
    TaskReassignRequest,
    TaskResponse,
    TaskStatus,
    TaskType,
    User,
)
from ..services import task_service

tasks_router = APIRouter(tags=["admin · tasks"])

ADMIN = {403: {"description": "Admin scope required"}}
NOT_FOUND = {404: {"description": "Task not found"}}
STATE = {409: {"description": "The task's status does not allow this"}}
TaskId = Annotated[int, Path(ge=1)]


@tasks_router.get(
    "/tasks",
    response_model=List[TaskResponse],
    summary="List tasks",
    description=(
        "Oldest first. Without `status`: open and blocked tasks, plus those done or cancelled "
        "in the last 7 days (the same list `tasks_update` carries to admins). With `status` "
        "(repeatable): exactly those, with no time limit."
    ),
    responses=ADMIN,
)
async def list_tasks(
    assigned_to: Optional[str] = Query(None, max_length=64),
    type: Optional[TaskType] = Query(None),
    status: Optional[List[TaskStatus]] = Query(None),
    current_user: User = Depends(require_admin),
):
    return await asyncio.to_thread(task_service.admin_tasks, assigned_to, type, status)


@tasks_router.post(
    "/tasks/count",
    response_model=TaskResponse,
    summary="Create a count task",
    description=(
        "Assigns a blind count of one item to a worker. In `multi` mode `location` (the bin) "
        "is required; in `single` mode it is refused, and the count sets the item where it is."
    ),
    responses={
        **ADMIN,
        400: {"description": "Location missing (`multi`) or given (`single`)"},
        404: {"description": "Item or worker not found"},
    },
)
async def create_count_task(body: TaskCountCreate, current_user: User = Depends(require_admin)):
    return await task_service.create_count(
        body.sku, body.assigned_to, current_user.username, body.location, body.note
    )


@tasks_router.post(
    "/tasks/pick",
    response_model=TaskResponse,
    summary="Create a manual picking task",
    description=(
        "Lines of internal SKUs and quantities; a bundle is expanded by the standard BOM now, "
        "and the expansion is stored with the task. Done when every leaf is picked exactly."
    ),
    responses={
        **ADMIN,
        400: {"description": "The lines expand to nothing to pick"},
        404: {"description": "Item or worker not found"},
    },
)
async def create_pick_task(body: TaskPickCreate, current_user: User = Depends(require_admin)):
    return await task_service.create_pick(
        [(line.sku, line.qty) for line in body.lines],
        body.assigned_to,
        current_user.username,
        body.reference,
        body.note,
    )


@tasks_router.get(
    "/tasks/{task_id}",
    response_model=AdminTaskDetailResponse,
    summary="A task with its stock log",
    description=(
        "Lines, what was picked, every stock log row the task caused, and for a done count "
        "the recorded quantity it replaced and the difference."
    ),
    responses={**ADMIN, **NOT_FOUND},
)
async def get_task(task_id: TaskId, current_user: User = Depends(require_admin)):
    return await asyncio.to_thread(task_service.task_detail, task_id)


@tasks_router.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskResponse,
    summary="Cancel a task",
    description=(
        "Open or blocked tasks. Picked stock is returned by default; with "
        "`return_stock: false` it stays deducted (the goods already left). Logged either way."
    ),
    responses={**ADMIN, **NOT_FOUND, **STATE},
)
async def cancel_task(
    task_id: TaskId, body: TaskCancelRequest, current_user: User = Depends(require_admin)
):
    return await task_service.cancel(task_id, current_user.username, body.return_stock)


@tasks_router.post(
    "/tasks/{task_id}/reassign",
    response_model=TaskResponse,
    summary="Give a task to another worker",
    description="Open or blocked tasks; the task becomes open, and its picks move with it.",
    responses={**ADMIN, 404: {"description": "Task or worker not found"}, **STATE},
)
async def reassign_task(
    task_id: TaskId, body: TaskReassignRequest, current_user: User = Depends(require_admin)
):
    return await task_service.reassign(task_id, body.assigned_to, current_user.username)


@tasks_router.post(
    "/tasks/{task_id}/close",
    response_model=TaskResponse,
    summary="Close a blocked pick task as picked",
    description="Done with what was picked; the picks stay deducted.",
    responses={**ADMIN, **NOT_FOUND, **STATE},
)
async def close_task(task_id: TaskId, current_user: User = Depends(require_admin)):
    return await task_service.close_as_picked(task_id, current_user.username)


@tasks_router.get(
    "/order-tasks",
    response_model=List[OrderTaskResponse],
    summary="Claimed orders not yet picked, per worker",
    description=(
        "Read-only: each worker's claimed active orders that are not *Picked* yet, with "
        "progress (SKUs picked exactly of required). Derived, never stored."
    ),
    responses=ADMIN,
)
async def list_order_tasks(
    assigned_to: Optional[str] = Query(None, max_length=64),
    current_user: User = Depends(require_admin),
):
    return await asyncio.to_thread(task_service.order_tasks, assigned_to)
