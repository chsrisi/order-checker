"""v2 worker tasks (IMPLEMENTATION_PLAN T9.2, V2_TASKS_SPEC §4–§6): the list (manual tasks plus
claimed orders as order-tasks), count, pick, unassign, can't finish. Only the assigned worker
works a task; admins are refused (Q75). Gated by the client version like the rest of /v2."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Path

from ...dependencies import require_operator
from ...models import (
    OrderPickRequest,
    TaskBlockRequest,
    TaskCountRequest,
    TaskPickResponse,
    TaskResponse,
    User,
    V2TaskListResponse,
)
from ...services import task_service
from . import GATE_RESPONSES, require_client_version

router = APIRouter(
    prefix="/v2/tasks",
    tags=["v2 · tasks"],
    dependencies=[Depends(require_client_version)],
)

TaskId = Annotated[int, Path(ge=1)]
RESPONSES = {**GATE_RESPONSES, 403: {"description": "Admin accounts cannot work on tasks"}}
NOT_YOURS = {404: {"description": "Task not found or not assigned to the caller"}}


@router.get(
    "",
    response_model=V2TaskListResponse,
    summary="My tasks",
    description=(
        "The caller's open and blocked tasks (oldest first), and their claimed orders that are "
        "not *Picked* yet. Live: `tasks_update` on `/v2/ws` carries the task list."
    ),
    responses=RESPONSES,
)
async def list_my_tasks(current_user: User = Depends(require_operator)):
    return await asyncio.to_thread(task_service.v2_task_list, current_user.username)


@router.post(
    "/{task_id}/count",
    response_model=TaskResponse,
    summary="Record a count",
    description=(
        "Sets the counted quantity (blind: the recorded stock is never shown) and completes "
        "the task. The scanned item must be the task's; in `multi` mode the scanned location "
        "must be its bin, in `single` mode a scanned location must be where the item is."
    ),
    responses={
        **RESPONSES,
        **NOT_YOURS,
        409: {"description": "Wrong item or location, or the task is not open"},
    },
)
async def count(
    task_id: TaskId, body: TaskCountRequest, current_user: User = Depends(require_operator)
):
    return await task_service.count(
        task_id, current_user.username, body.sku, body.qty, body.location
    )


@router.post(
    "/{task_id}/picks",
    response_model=TaskPickResponse,
    summary="Pick an item into a task",
    description=(
        "Resolves the SKU/barcode and deducts stock bin by bin, as for an order. The task is "
        "done when every line is picked exactly (`status`)."
    ),
    responses={
        **RESPONSES,
        404: {"description": "SKU/barcode not found, or task not assigned to the caller"},
        409: {
            "description": (
                "Item not on the task, task not open, or not enough stock (only with "
                "`STOCK_STRICT`)"
            )
        },
    },
)
async def pick(
    task_id: TaskId, body: OrderPickRequest, current_user: User = Depends(require_operator)
):
    return await task_service.pick(task_id, current_user.username, body.sku, body.qty)


@router.post(
    "/{task_id}/picks/unassign",
    response_model=TaskPickResponse,
    summary="Remove a picked quantity from a task",
    description="Returns the quantity to stock at once. `sku` is the stored SKU of the line.",
    responses={
        **RESPONSES,
        404: {"description": "Task not assigned to the caller, or nothing of the SKU picked"},
        409: {"description": "Task not open, or more than is picked; nothing changes"},
    },
)
async def unassign(
    task_id: TaskId, body: OrderPickRequest, current_user: User = Depends(require_operator)
):
    return await task_service.unassign(task_id, current_user.username, body.sku, body.qty)


@router.post(
    "/{task_id}/block",
    response_model=TaskResponse,
    summary="Can't finish",
    description="Marks an open task blocked, with a reason; an admin then decides.",
    responses={**RESPONSES, **NOT_YOURS, 409: {"description": "The task is not open"}},
)
async def block(
    task_id: TaskId, body: TaskBlockRequest, current_user: User = Depends(require_operator)
):
    return await task_service.block(task_id, current_user.username, body.reason)
