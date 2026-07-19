import logging
from typing import List
from fastapi import APIRouter, Depends
from ..models import (
    MessageResponse,
    PickItemEntryAssign,
    PickItemEntryCreate,
    PickItemEntryResponse,
    PickItemEntryUnassign,
    User,
)
from ..dependencies import get_current_user
from ..services import pick_item_service, queries

logger = logging.getLogger("backend.routers.pick_items")

router = APIRouter(prefix="/pick-items", tags=["pick items"])


@router.post(
    "",
    response_model=PickItemEntryResponse,
    summary="Add a pick-list entry",
    description="Resolves the SKU/barcode and merges the quantity into a matching user/order entry.",
    responses={404: {"description": "SKU/barcode not found"}},
)
async def create_pie(
    payload: PickItemEntryCreate,
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} adding item {payload.sku} to pick list")
    pie = await pick_item_service.create_pick_item_entry(
        sku=payload.sku,
        qty=payload.qty,
        username=current_user.username,
        order_sn=payload.order_sn,
    )

    item = queries.resolve_barcode_to_item(pie.sku or "")
    item_name = item.item_name if item else None

    return PickItemEntryResponse(
        id=pie.id,
        sku=pie.sku or "",
        qty=pie.qty or 0,
        order_sn=pie.order_sn,
        timestamp=pie.timestamp,
        owner_user=pie.owner_user,
        item_name=item_name,
    )


@router.get(
    "",
    response_model=List[PickItemEntryResponse],
    summary="List pick entries",
    description="Operators see their own entries; administrators see all entries.",
)
def get_pies(current_user: User = Depends(get_current_user)):
    username = None if current_user.scope == "admin" else current_user.username
    entries = queries.get_pie_data(username=username)

    results = []
    for entry in entries:
        item = queries.resolve_barcode_to_item(entry.sku or "")
        item_name = item.item_name if item else None
        results.append(
            PickItemEntryResponse(
                id=entry.id,
                sku=entry.sku or "",
                qty=entry.qty or 0,
                order_sn=entry.order_sn,
                timestamp=entry.timestamp,
                owner_user=entry.owner_user,
                item_name=item_name,
            )
        )
    return results


@router.post(
    "/{entry_id}/assign",
    response_model=PickItemEntryResponse,
    summary="Assign a pick entry to an order",
    description="Moves all or part of an unassigned entry to an order claimed by the authenticated operator.",
    responses={
        400: {"description": "Invalid quantity"},
        404: {"description": "Entry or claimed order not found"},
    },
)
async def assign_pie(
    entry_id: int,
    payload: PickItemEntryAssign,
    current_user: User = Depends(get_current_user),
):
    pie = await pick_item_service.assign_pick_item_entry(
        entry_id=entry_id,
        order_sn=payload.order_sn,
        qty=payload.qty,
        username=current_user.username,
    )

    item = queries.resolve_barcode_to_item(pie.sku or "")
    item_name = item.item_name if item else None

    return PickItemEntryResponse(
        id=pie.id,
        sku=pie.sku or "",
        qty=pie.qty or 0,
        order_sn=pie.order_sn,
        timestamp=pie.timestamp,
        owner_user=pie.owner_user,
        item_name=item_name,
    )


@router.delete(
    "/{entry_id}",
    response_model=MessageResponse,
    summary="Delete a pick entry",
    description="Operators may delete their own entries; administrators may delete any entry.",
    responses={404: {"description": "Entry not found or not owned by user"}},
)
async def delete_pie(
    entry_id: int,
    current_user: User = Depends(get_current_user),
):
    await pick_item_service.delete_pie(
        pie_id=entry_id,
        username=current_user.username,
        is_admin=current_user.scope == "admin",
    )
    return {"message": "ok"}


@router.post(
    "/unassign",
    response_model=MessageResponse,
    summary="Return picked quantity from an order",
    description="Moves up to the requested quantity from an order-specific entry back to the user's general pick list.",
    responses={404: {"description": "Assigned entry not found"}},
)
async def unassign_pie(
    payload: PickItemEntryUnassign,
    current_user: User = Depends(get_current_user),
):
    await pick_item_service.unassign_pick_item_entry(
        order_sn=payload.order_sn,
        sku=payload.sku,
        qty=payload.qty,
        username=current_user.username,
    )
    return {"message": "Pick quantity unassigned"}
