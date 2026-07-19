import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

from ..models import User
from ..dependencies import require_admin
from ..services import queries
from ..services.bom_service import get_standard_bom_node, get_marketplace_bom_node

logger = logging.getLogger("backend.routers.bom")

bom_router = APIRouter(prefix="/bom", tags=["BOM"])


@bom_router.get(
    "/headers",
    summary="List BOM roots",
    description="Returns standard warehouse BOM headers and Shopee marketplace BOM headers.",
    responses={403: {"description": "Admin scope required"}},
)
def get_bom_headers(current_user: User = Depends(require_admin)):

    return {
        "standard": queries.get_bom_headers(),
        "marketplace": queries.get_marketplace_bom_headers(),
    }


@bom_router.get(
    "/tree",
    summary="Resolve a BOM tree",
    description="Provide exactly one of `sku` or `shopee_id` to recursively resolve a standard or marketplace BOM.",
    responses={
        400: {"description": "No selector supplied"},
        403: {"description": "Admin scope required"},
        404: {"description": "BOM not found"},
    },
)
def get_bom_tree(
    sku: Optional[str] = None,
    shopee_id: Optional[int] = None,
    current_user: User = Depends(require_admin),
):
    if (sku is None) == (shopee_id is None):
        raise HTTPException(status_code=400, detail="Provide exactly one of 'sku' or 'shopee_id'")
    if sku is not None:
        sku = sku.strip()
        return get_standard_bom_node(sku, 1, False)
    if shopee_id is not None:
        node = get_marketplace_bom_node(shopee_id)
        if not node:
            raise HTTPException(status_code=404, detail="Marketplace BOM not found")
        return node
    raise HTTPException(status_code=400, detail="Invalid BOM selector")
