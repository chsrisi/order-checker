import logging
from typing import List
from fastapi import APIRouter, Depends, Query

from ..models import MessageResponse, ShopeeAcquireResponse, User, ShopeeOrderResponse
from ..dependencies import get_current_user, require_admin
from ..services import shopee_service
from ..services.managers import cache_mgr

logger = logging.getLogger("backend.routers.shopee")

router = APIRouter(prefix="/shopee", tags=["Shopee"])


@router.get(
    "/orders",
    response_model=List[ShopeeOrderResponse],
    summary="Synchronize active Shopee orders",
    description="Returns eligible active orders. `refresh=true` invalidates the two-minute in-process cache before synchronization.",
    responses={
        401: {"description": "Invalid bearer token"},
        502: {"description": "Shopee request failed"},
    },
)
async def get_shopee_orders(
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} requested Shopee synchronization.")

    return await shopee_service.sync_shopee_orders(refresh=refresh, username=current_user.username)


@router.post(
    "/orders/acquire",
    response_model=ShopeeAcquireResponse,
    summary="Claim a Shopee order",
    description="Assigns an existing synchronized order to the authenticated operator.",
    responses={
        404: {"description": "Order not found"},
        409: {"description": "Order assigned to another operator"},
    },
)
async def acquire_order(
    order_sn: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    logger.info(
        "shopee_order_acquire_requested",
        extra={"event": "shopee.order.acquire_requested", "username": current_user.username},
    )

    await shopee_service.acquire_order(order_sn=order_sn, username=current_user.username)

    return {"message": "Order assigned successfully", "order_sn": order_sn}


@router.post(
    "/reset-cache-state",
    response_model=MessageResponse,
    summary="Reset Shopee synchronization state",
    description="Admin-only recovery action that clears the token-fatal circuit state and invalidates the local cache.",
    responses={403: {"description": "Admin scope required"}},
)
async def reset_shopee_cache_state(
    current_user: User = Depends(require_admin),
):

    logger.warning(f"Admin {current_user.username} resetting Shopee cache state")
    cache_mgr.set_token_fatal(False)
    cache_mgr.invalidate()
    return {"message": "Shopee cache state reset successfully"}
