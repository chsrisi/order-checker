import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from .bom import bom_router
from .admin_shopee import shopee_config_router
from ..models import User, OutboundResponse, ShopeeOrderResponse
from ..dependencies import require_admin
from ..services import queries, auth_service, shopee_service

logger = logging.getLogger("backend.routers.admin")

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(bom_router)
router.include_router(shopee_config_router)


@router.get("/users")
def get_users(current_user: User = Depends(require_admin)):
    users = queries.get_all_user_data()
    logger.info(f"Admin {current_user.username} fetched {len(users)} client users")
    return users


@router.delete("/users")
async def delete_user(
    username: str = Query(...),
    current_user: User = Depends(require_admin),
):
    await auth_service.delete_user(username)
    logger.info(f"Admin {current_user.username} deleted user {username}")
    return {"message": "User and associated data deleted successfully"}


@router.get("/history/outbound", response_model=List[OutboundResponse])
def get_outbound_history(current_user: User = Depends(require_admin)):
    return queries.get_outbound_history()


@router.get("/history/shopee/orders", response_model=List[ShopeeOrderResponse])
def get_shopee_orders_history(current_user: User = Depends(require_admin)):
    orders = queries.get_shopee_orders_history()
    return [shopee_service.build_shopee_order_response(o) for o in orders]


@router.get("/export/scans")
def export_scanned_items(current_user: User = Depends(require_admin)):
    csv_data = queries.get_export_scans_csv()
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=scanned_items_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )


@router.get("/export/stocks")
def export_stocks(current_user: User = Depends(require_admin)):
    csv_data = queries.get_export_stocks_csv()
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=inventory_stocks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )
