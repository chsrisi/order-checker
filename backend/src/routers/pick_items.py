import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import (
    User,
    PickItemEntryCreate,
    PickItemEntryResponse,
    PickItemEntry,
    ShopeeOrder,
    WarehouseItem,
    WSMessageType,
)
from ..dependencies import get_db, get_current_user
from ..services.manager import conn_mgr
from ..services.barcode_service import resolve_barcode_to_item
from ..services.pick_item_service import merge_or_create_pie
from ..services import queries

logger = logging.getLogger("backend.routers.pick_items")

router = APIRouter(tags=["pick_items"])


@router.post("/pick-item", response_model=PickItemEntryResponse)
async def create_pie(
    entry_in: PickItemEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Resolve sku/barcode to a warehouse item first
    item = resolve_barcode_to_item(entry_in.sku, db)
    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Item with SKU or barcode '{entry_in.sku}' not found",
        )
    sku = item.sku

    # Using the merge logic
    entry = merge_or_create_pie(
        db,
        current_user.username,
        sku,
        entry_in.qty,
        order_sn=entry_in.order_sn,
    )

    db.commit()
    db.refresh(entry)

    await conn_mgr.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, db, username=current_user.username or ""
    )
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, db, scope="admin")

    item_name = db.execute(
        select(WarehouseItem.item_name).filter(WarehouseItem.sku == entry.sku)
    ).scalar()

    return PickItemEntryResponse(
        id=entry.id,
        sku=entry.sku or "",
        qty=entry.qty or 0,
        order_sn=entry.order_sn,
        timestamp=entry.timestamp,
        owner_user=entry.owner_user,
        item_name=item_name,
    )


@router.get("/pick-item", response_model=List[PickItemEntryResponse])
def read_pies(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    logger.info(f"User {current_user.username} fetching scan entries")
    return queries.get_pie_data(db, current_user.username)


@router.delete("/pick-item")
async def delete_pie(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} deleting scan entry {entry_id}")
    entry = (
        db.execute(
            select(PickItemEntry).filter(
                PickItemEntry.id == entry_id,
                PickItemEntry.owner_user == current_user.username,
            )
        )
        .scalars()
        .first()
    )
    if not entry:
        logger.warning(
            f"Scan entry {entry_id} not found for user {current_user.username}"
        )
        raise HTTPException(status_code=404, detail="Scan entry not found")

    db.delete(entry)
    logger.info(f"Scan entry {entry_id} deleted")

    db.commit()

    await conn_mgr.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, db, username=current_user.username
    )
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, db, scope="admin")
    return {"message": "PickItemEntry deleted"}


@router.post("/pick-item/assign", response_model=PickItemEntryResponse)
async def assign_pie(
    entry_id: int,
    order_sn: str,
    qty: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = (
        db.execute(
            select(PickItemEntry).filter(
                PickItemEntry.id == entry_id,
                PickItemEntry.owner_user == current_user.username,
            )
        )
        .scalars()
        .first()
    )
    order = (
        db.execute(
            select(ShopeeOrder).filter(
                ShopeeOrder.order_sn == order_sn,
                ShopeeOrder.owner_user == current_user.username,
            )
        )
        .scalars()
        .first()
    )

    if not entry or not order:
        raise HTTPException(status_code=404, detail="Entry or Order not found")

    sku = entry.sku
    total_qty = entry.qty

    assign_qty = qty if qty is not None else total_qty
    assign_qty = min(assign_qty, total_qty)

    if assign_qty <= 0:
        raise HTTPException(status_code=400, detail="Invalid quantity")

    if assign_qty >= total_qty:
        db.delete(entry)
    else:
        entry.qty -= assign_qty
        db.add(entry)

    new_entry = merge_or_create_pie(
        db,
        current_user.username,
        sku,
        assign_qty,
        order_sn=order_sn,
    )

    db.commit()
    db.refresh(new_entry)

    await conn_mgr.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, db, username=current_user.username
    )
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, db, scope="admin")

    item_name = db.execute(
        select(WarehouseItem.item_name).filter(WarehouseItem.sku == new_entry.sku)
    ).scalar()

    return PickItemEntryResponse(
        id=new_entry.id,
        sku=new_entry.sku,
        qty=new_entry.qty,
        order_sn=new_entry.order_sn,
        timestamp=new_entry.timestamp,
        owner_user=new_entry.owner_user,
        item_name=item_name,
    )


@router.post("/pick-item/unassign")
async def unassign_pie(
    order_sn: str,
    sku: str,
    qty: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Find entries for this SKU and Label
    entry = (
        db.execute(
            select(PickItemEntry).filter(
                PickItemEntry.owner_user == current_user.username,
                PickItemEntry.sku == sku,
                PickItemEntry.order_sn == order_sn,
            )
        )
        .scalars()
        .first()
    )

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    take_qty = min(qty, entry.qty or 0)

    # 1. Reduce from original
    entry.qty = (entry.qty or 0) - take_qty
    if entry.qty <= 0:
        db.delete(entry)
    else:
        db.add(entry)

    # 2. Merge/Create as unassigned
    merge_or_create_pie(
        db,
        current_user.username,
        sku,
        take_qty,
        order_sn=None,
    )

    db.commit()

    await conn_mgr.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, db, username=current_user.username
    )
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, db, scope="admin")

    return {"message": "SKU unassigned successfully"}
