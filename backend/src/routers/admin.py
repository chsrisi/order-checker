import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, Path, Query, Response
from fastapi.responses import StreamingResponse

from .bom import bom_router
from .admin_shopee import shopee_config_router
from ..models import (
    AdminPasswordReset,
    AdminUserCreate,
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


@router.post(
    "/users",
    response_model=UserResponse,
    summary="Create an operator account",
    description=(
        "Creates a client-scope account. This is how operator accounts are created when "
        "self-registration is disabled (production)."
    ),
    responses={
        403: {"description": "Admin scope required"},
        409: {"description": "Username already exists"},
    },
)
async def create_user(body: AdminUserCreate, current_user: User = Depends(require_admin)):
    user = await auth_service.admin_create_user(body.username, body.password)
    logger.info(f"Admin {current_user.username} created user {body.username}")
    return user


@router.post(
    "/users/{username}/password",
    response_model=MessageResponse,
    summary="Reset an operator password",
    description=(
        "Sets a new password, revokes all of the user's refresh tokens and closes their "
        "WebSocket sessions, so every device must log in again."
    ),
    responses={
        403: {"description": "Admin scope required"},
        404: {"description": "Client account not found"},
    },
)
async def reset_user_password(
    body: AdminPasswordReset,
    username: str = Path(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$"),
    current_user: User = Depends(require_admin),
):
    await auth_service.admin_reset_password(username, body.password)
    logger.info(f"Admin {current_user.username} reset the password of {username}")
    return {"message": "Password reset; all sessions revoked"}


@router.delete(
    "/users",
    response_model=MessageResponse,
    summary="Delete an operator account",
    description=(
        "Deletes a client account and its refresh tokens and outbound scans. Its pick "
        "entries are deleted with their stock restored, and its claimed orders are released."
    ),
    responses={
        403: {"description": "Admin scope required"},
        404: {"description": "Client account not found"},
    },
)
async def delete_user(
    username: str = Query(...),
    current_user: User = Depends(require_admin),
):
    await auth_service.delete_user(username, actor=current_user.username)
    logger.info(f"Admin {current_user.username} deleted user {username}")
    return {"message": "User and associated data deleted successfully"}


# T5.2: history pages, newest first; X-Total-Count carries the full size.
HISTORY_LIMIT = Query(500, ge=1, le=2000, description="Page size (newest first).")
HISTORY_OFFSET = Query(0, ge=0, description="Rows to skip.")


@router.get(
    "/history/outbound",
    response_model=List[OutboundResponse],
    summary="Get closed outbound history",
    description="Returns only scans that have been closed by an administrator.",
    responses={403: {"description": "Admin scope required"}},
)
def get_outbound_history(
    response: Response,
    limit: int = HISTORY_LIMIT,
    offset: int = HISTORY_OFFSET,
    current_user: User = Depends(require_admin),
):
    items, total = queries.get_outbound_history(limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get(
    "/history/shopee/orders",
    response_model=List[ShopeeOrderResponse],
    summary="Get completed Shopee order history",
    description="Returns only orders marked complete by outbound period closure.",
    responses={403: {"description": "Admin scope required"}},
)
def get_shopee_orders_history(
    response: Response,
    limit: int = HISTORY_LIMIT,
    offset: int = HISTORY_OFFSET,
    current_user: User = Depends(require_admin),
):
    orders, total = queries.get_shopee_orders_history(limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return shopee_service.build_shopee_order_responses(orders)


@router.get(
    "/export/scans",
    summary="Export all outbound scans as CSV",
    description="Streams every outbound scan record, open and closed, newest first, as a timestamped CSV file.",
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
