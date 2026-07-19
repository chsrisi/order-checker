import logging
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import User, WarehouseItemResponse, WarehouseItem
from ..dependencies import get_db, get_current_user
from ..services.barcode_service import resolve_barcode_to_item

logger = logging.getLogger("backend.routers.items")

router = APIRouter(tags=["items"])


@router.get("/items/find", response_model=List[WarehouseItemResponse])
def find_warehouse_items(
    query: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} searching for: {query}")

    # Try to resolve barcode first
    resolved_item = resolve_barcode_to_item(query, db)
    if resolved_item:
        logger.debug(f"Resolved barcode '{query}' to item SKU '{resolved_item.sku}'")
        return [resolved_item]

    search = f"%{query}%"
    results = (
        db.execute(
            select(WarehouseItem)
            .filter(
                (WarehouseItem.sku.ilike(search))
                | (WarehouseItem.item_name.ilike(search))
            )
            .limit(50)
        )
        .scalars()
        .all()
    )
    logger.debug(f"Found {len(results)} matches for query '{query}'")
    return results
