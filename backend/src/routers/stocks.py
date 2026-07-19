import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import User, StockCreate, StockResponse, Stock, WSMessageType
from ..dependencies import get_db, get_current_user
from ..services.manager import conn_mgr
from ..services.barcode_service import resolve_barcode_to_item
from ..services.stock_service import get_or_merge_stock

logger = logging.getLogger("backend.routers.stocks")

router = APIRouter(tags=["stocks"])


@router.post("/stocks", response_model=StockResponse)
async def set_stock(
    stock_in: StockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Resolve barcode to a warehouse item first
    item = resolve_barcode_to_item(stock_in.sku, db)
    if not item:
        logger.warning(f"Stock update failed: SKU/barcode {stock_in.sku} not found")
        raise HTTPException(
            status_code=404,
            detail=f"Item with SKU or barcode '{stock_in.sku}' not found",
        )
    sku = item.sku

    location = stock_in.location if stock_in.location != "" else None
    move_to = stock_in.move_to if stock_in.move_to != "" else None

    logger.info(
        f"User {current_user.username} {stock_in.mode} stock for {sku} value {stock_in.stock} at {location} (move_to: {move_to})"
    )

    if move_to is not None:
        # Move operation
        if location == move_to:
            db_stock = get_or_merge_stock(db, sku, location)
            if not db_stock:
                db_stock = Stock(sku=sku, stock=0, location=location)
                db.add(db_stock)
                db.flush()
            db_stock_res = db_stock
        else:
            source_stock = get_or_merge_stock(db, sku, location)
            if not source_stock:
                source_stock = Stock(sku=sku, stock=0, location=location)
                db.add(source_stock)
                db.flush()

            dest_stock = get_or_merge_stock(db, sku, move_to)
            if not dest_stock:
                dest_stock = Stock(sku=sku, stock=0, location=move_to)
                db.add(dest_stock)
                db.flush()

            # Perform move
            source_stock.stock -= stock_in.stock
            dest_stock.stock += stock_in.stock

            # Clean up if source stock becomes <= 0
            if source_stock.stock <= 0:
                db.delete(source_stock)

            # Clean up if dest stock becomes <= 0
            if dest_stock.stock <= 0:
                db.delete(dest_stock)
                db_stock_res = Stock(id=0, sku=sku, stock=0, location=move_to)
            else:
                db_stock_res = dest_stock
    else:
        # Standard update/set operation
        db_stock = get_or_merge_stock(db, sku, location)
        if db_stock:
            if stock_in.mode == "add":
                db_stock.stock += stock_in.stock
            else:
                db_stock.stock = stock_in.stock
            logger.info(f"Updated existing stock record for {sku} at {location}")
        else:
            location_val = (
                location if "location" in stock_in.model_fields_set else item.location
            )
            db_stock = Stock(
                sku=sku,
                stock=stock_in.stock,
                location=location_val,
            )
            db.add(db_stock)
            db.flush()
            logger.info(f"Created new stock record for {sku} at {location_val}")

        # Clean up if stock becomes <= 0
        if db_stock.stock <= 0:
            db.delete(db_stock)
            db_stock_res = Stock(id=0, sku=sku, stock=0, location=location)
        else:
            db_stock_res = db_stock

    db.commit()

    if db_stock_res.id and db_stock_res.stock > 0:
        db.refresh(db_stock_res)

    # Broadcast update
    await conn_mgr.broadcast(WSMessageType.STOCKS, db)

    return StockResponse(
        id=db_stock_res.id if db_stock_res.id else 0,
        sku=db_stock_res.sku,
        stock=db_stock_res.stock,
        location=db_stock_res.location,
        item_name=item.item_name,
    )
