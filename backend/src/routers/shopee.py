import logging
from typing import List
from fastapi import APIRouter, Depends, Query

from ..models import User, ShopeeOrderResponse
from ..dependencies import get_current_user, require_admin
from ..services import shopee_service
from ..services.managers import cache_mgr

logger = logging.getLogger("backend.routers.shopee")

router = APIRouter(prefix="/shopee", tags=["shopee"])


@router.get("/orders", response_model=List[ShopeeOrderResponse])
async def get_shopee_orders(
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} requested Shopee synchronization.")
    
    return await shopee_service.sync_shopee_orders(
        refresh=refresh, username=current_user.username
    )


@router.post("/orders/acquire")
async def acquire_order(
    order_sn: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} acquiring order {order_sn}")
    
    await shopee_service.acquire_order(
        order_sn=order_sn, username=current_user.username
    )

    return {"message": "Order assigned successfully", "order_sn": order_sn}


@router.post("/reset-cache-state")
async def reset_shopee_cache_state(
    current_user: User = Depends(require_admin),
):

    logger.warning(f"Admin {current_user.username} resetting Shopee cache state")
    cache_mgr.set_token_fatal(False)
    cache_mgr.invalidate()
    return {"message": "Shopee cache state reset successfully"}
