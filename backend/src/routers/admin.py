import logging
import io
import csv
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, delete

from ..models import (
    User,
    OutboundItem,
    RefreshToken,
    OutboundResponse,
    ShopeeOrder,
    ShopeeOrderResponse,
    Stock,
    WarehouseItem,
)
from ..dependencies import get_db, get_current_user
from ..services.manager import conn_mgr
from ..services.bom_service import build_shopee_order_response

logger = logging.getLogger("backend.routers.admin")

router = APIRouter(tags=["admin"])


@router.get("/admin/users")
def get_users(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        logger.warning(
            f"Unauthorized access attempt to /admin/users by user: {current_user.username}"
        )
        raise HTTPException(status_code=403, detail="Not authorized")

    users = db.execute(select(User).filter(User.scope == "client")).scalars().all()
    logger.info(f"Admin {current_user.username} fetched {len(users)} client users")
    return users


@router.delete("/admin/users")
async def delete_user(
    username: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        logger.warning(
            f"Unauthorized delete attempt for user {username} by: {current_user.username}"
        )
        raise HTTPException(status_code=403, detail="Not authorized")

    user = (
        db.execute(
            select(User).filter(User.username == username, User.scope == "client")
        )
        .scalars()
        .first()
    )
    if not user:
        logger.warning(
            f"Admin {current_user.username} tried to delete non-existent user: {username}"
        )
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(f"Admin {current_user.username} deleting user {user.username}")
    # Delete associated items and tokens
    scans_result = (
        db.execute(delete(OutboundItem).filter(OutboundItem.owner_user == username))
        .scalars()
        .all()
    )
    tokens_result = (
        db.execute(delete(RefreshToken).filter(RefreshToken.username == username))
        .scalars()
        .all()
    )
    db.delete(user)
    db.commit()
    logger.info(
        "Deleted user %s, %s scans, and %s refresh tokens",
        user.username,
        len(scans_result),
        len(tokens_result),
    )
    from ..models import WSMessageType

    await conn_mgr.broadcast(WSMessageType.USERS, db, scope="admin")
    return {"message": "User and associated data deleted successfully"}


@router.get("/admin/history/outbound", response_model=List[OutboundResponse])
def get_outbound_history(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    items = (
        db.execute(
            select(OutboundItem)
            .filter(OutboundItem.closed == True)  # noqa: E712
            .order_by(OutboundItem.created_at.desc())
        )
        .scalars()
        .unique()
        .all()
    )
    return items


@router.get("/admin/history/shopee/orders", response_model=List[ShopeeOrderResponse])
def get_shopee_orders_history(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    orders = (
        db.execute(
            select(ShopeeOrder)
            .filter(ShopeeOrder.done == True)  # noqa: E712
            .order_by(ShopeeOrder.ship_by.desc())
        )
        .scalars()
        .all()
    )
    return [build_shopee_order_response(o, db) for o in orders]


@router.get("/admin/export/scans")
def export_scanned_items(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        logger.warning(f"Unauthorized export attempt by user: {current_user.username}")
        raise HTTPException(status_code=403, detail="Not authorized")

    items = (
        db.execute(
            select(OutboundItem)
            .filter(OutboundItem.closed == False)  # noqa: E712
            .order_by(OutboundItem.created_at.desc())
        )
        .scalars()
        .unique()
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Content", "Tags", "Created At", "Owner"])

    for item in items:
        writer.writerow(
            [
                item.id,
                item.content,
                ", ".join(item.tags),
                item.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                item.owner_user,
            ]
        )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=scanned_items_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )


@router.get("/admin/export/stocks")
def export_stocks(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        logger.warning(
            f"Unauthorized stock export attempt by user: {current_user.username}"
        )
        raise HTTPException(status_code=403, detail="Not authorized")

    # Join Stock with WarehouseItem to get item metadata.
    query = (
        select(Stock.sku, Stock.stock, WarehouseItem.item_name)
        .join(WarehouseItem, Stock.sku == WarehouseItem.sku)
        .order_by(Stock.sku)
    )
    results = db.execute(query).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["SKU", "Description", "Stock"])

    for r in results:
        writer.writerow(
            [
                r.sku,
                r.item_name or "",
                r.stock,
            ]
        )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=inventory_stocks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )
