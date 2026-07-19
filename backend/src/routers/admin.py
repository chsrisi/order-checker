import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from .bom import bom_router
from .admin_shopee import shopee_config_router
from ..models import (
    DeleteCountResponse,
    MessageResponse,
    OutboundResponse,
    ShopeeOrderResponse,
    User,
    UserResponse,
)
from ..dependencies import require_admin
from ..services import queries, auth_service, outbound_service, shopee_service

logger = logging.getLogger("backend.routers.admin")

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(bom_router)
router.include_router(shopee_config_router)


@router.get(
    "/users",
    response_model=List[UserResponse],
    summary="List operator accounts",
    description="Returns usernames and scopes for all client accounts. Password hashes are never serialized.",
    responses={403: {"description": "Admin scope required"}},
)
def get_users(current_user: User = Depends(require_admin)):
    users = queries.get_all_user_data()
    logger.info(f"Admin {current_user.username} fetched {len(users)} client users")
    return users


@router.delete(
    "/users",
    response_model=MessageResponse,
    summary="Delete an operator account",
    description="Deletes a client account and its refresh tokens, pick entries, and outbound scans.",
    responses={
        403: {"description": "Admin scope required"},
        404: {"description": "Client account not found"},
    },
)
async def delete_user(
    username: str = Query(...),
    current_user: User = Depends(require_admin),
):
    await auth_service.delete_user(username)
    logger.info(f"Admin {current_user.username} deleted user {username}")
    return {"message": "User and associated data deleted successfully"}


@router.get(
    "/history/outbound",
    response_model=List[OutboundResponse],
    summary="Get closed outbound history",
    description="Returns only scans that have been closed by an administrator.",
    responses={403: {"description": "Admin scope required"}},
)
def get_outbound_history(current_user: User = Depends(require_admin)):
    return queries.get_outbound_history()


@router.get(
    "/history/shopee/orders",
    response_model=List[ShopeeOrderResponse],
    summary="Get completed Shopee order history",
    description="Returns only orders marked complete by outbound period closure.",
    responses={403: {"description": "Admin scope required"}},
)
def get_shopee_orders_history(current_user: User = Depends(require_admin)):
    orders = queries.get_shopee_orders_history()
    return [shopee_service.build_shopee_order_response(o) for o in orders]


@router.get(
    "/export/scans",
    summary="Export open scans as CSV",
    description="Streams the current outbound scan set as a timestamped CSV file.",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}}, 403: {"description": "Admin scope required"}},
)
def export_scanned_items(current_user: User = Depends(require_admin)):
    csv_data = queries.get_export_scans_csv()
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=scanned_items_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )


@router.get(
    "/export/stocks",
    summary="Export inventory as CSV",
    description="Streams stock quantities, locations, and item names as a timestamped CSV file.",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}}, 403: {"description": "Admin scope required"}},
)
def export_stocks(current_user: User = Depends(require_admin)):
    csv_data = queries.get_export_stocks_csv()
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=inventory_stocks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )


@router.delete(
    "/clear/outbound-items",
    response_model=DeleteCountResponse,
    summary="Clear every outbound scan",
    description="Permanently deletes open and closed outbound scan records. Use only after exporting required history.",
    responses={403: {"description": "Admin scope required"}},
)
async def clear_outbound_items(current_user: User = Depends(require_admin)):
    count = await outbound_service.clear_outbound_items(current_user.username)
    return {"message": "Outbound scans cleared", "deleted": count}
