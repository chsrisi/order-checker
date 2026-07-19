import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import User, BOMHeader, WarehouseItem, BOMHeaderMarketplace
from ..dependencies import get_db, get_current_user
from ..services.bom_service import get_standard_bom_node, get_marketplace_bom_node

logger = logging.getLogger("backend.routers.bom")

router = APIRouter(tags=["bom"])


@router.get("/admin/bom/headers")
def get_bom_headers(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    # Standard BOM headers
    std_stmt = (
        select(
            BOMHeader.id,
            BOMHeader.sku,
            BOMHeader.quantity_standard,
            BOMHeader.factor_f5,
            WarehouseItem.item_name
        )
        .outerjoin(WarehouseItem, BOMHeader.sku == WarehouseItem.sku)
        .order_by(BOMHeader.sku)
    )
    std_results = db.execute(std_stmt).all()

    standard = []
    for r in std_results:
        standard.append({
            "id": r.id,
            "sku": r.sku,
            "quantity_standard": r.quantity_standard,
            "factor_f5": r.factor_f5,
            "item_name": r.item_name
        })

    # Marketplace BOM headers
    mp_stmt = (
        select(
            BOMHeaderMarketplace.shopee_id,
            BOMHeaderMarketplace.item_name,
            BOMHeaderMarketplace.model_name,
            BOMHeaderMarketplace.quantity_standard,
            BOMHeaderMarketplace.marketplace,
            BOMHeaderMarketplace.created_date
        )
        .order_by(BOMHeaderMarketplace.item_name)
    )
    mp_results = db.execute(mp_stmt).all()

    marketplace = []
    for r in mp_results:
        marketplace.append({
            "shopee_id": r.shopee_id,
            "item_name": r.item_name,
            "model_name": r.model_name,
            "quantity_standard": r.quantity_standard,
            "marketplace": r.marketplace,
            "created_date": r.created_date.isoformat() if r.created_date else None
        })

    return {
        "standard": standard,
        "marketplace": marketplace
    }


@router.get("/admin/bom/tree")
def get_bom_tree(
    sku: Optional[str] = None,
    shopee_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    if sku is not None:
        sku = sku.strip()
        return get_standard_bom_node(sku, 1, False, db)
    elif shopee_id is not None:
        node = get_marketplace_bom_node(shopee_id, db)
        if not node:
            raise HTTPException(status_code=404, detail="Marketplace BOM not found")
        return node
    else:
        raise HTTPException(status_code=400, detail="Must provide either 'sku' or 'shopee_id'")
