import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

from ..models import User
from ..dependencies import require_admin
from ..services import queries
from ..services.bom_service import get_standard_bom_node, get_marketplace_bom_node

logger = logging.getLogger("backend.routers.bom")

bom_router = APIRouter(prefix="/bom", tags=["bom"])


@bom_router.get("/headers")
def get_bom_headers(current_user: User = Depends(require_admin)):

    return {
        "standard": queries.get_bom_headers(),
        "marketplace": queries.get_marketplace_bom_headers(),
    }


@bom_router.get("/tree")
def get_bom_tree(
    sku: Optional[str] = None,
    shopee_id: Optional[int] = None,
    current_user: User = Depends(require_admin),
):

    if sku is not None:
        sku = sku.strip()
        return get_standard_bom_node(sku, 1, False)
    elif shopee_id is not None:
        node = get_marketplace_bom_node(shopee_id)
        if not node:
            raise HTTPException(status_code=404, detail="Marketplace BOM not found")
        return node
    else:
        raise HTTPException(
            status_code=400, detail="Must provide either 'sku' or 'shopee_id'"
        )
