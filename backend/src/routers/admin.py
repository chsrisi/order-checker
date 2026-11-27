import asyncio
import logging
from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Path, Query, Response
from fastapi.responses import StreamingResponse

from .bom import bom_router
from .admin_shopee import shopee_config_router
from ..models import (
    AdminDayDetailResponse,
    AdminDayResponse,
    AdminLookupResponse,
    AdminLoginRequest,
    AdminDeviceResponse,
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
from ..timezone import business_time
from ..services import (
    auth_service,
    device_service,
    login_request_service,
    outbound_service,
    queries,
    shopee_service,
)
from ..services.managers import conn_mgr

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
        "Sets a new password, revokes all of the user's sessions (tokens stop working on the "
        "next request) and closes their WebSocket connections, so every device must log in "
        "again."
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


@router.get(
    "/devices",
    response_model=List[AdminDeviceResponse],
    summary="List v2 devices",
    description=(
        "Registered v2 operator devices, most recently seen first: status, current operator, "
        "model, Android version, app versionCode, last contact, and `online` (a session of the "
        "device has an open live-update socket right now)."
    ),
    responses={403: {"description": "Admin scope required"}},
)
def list_devices(_admin: User = Depends(require_admin)):
    online = queries.device_ids_for_sessions(conn_mgr.live_session_ids())
    return [
        AdminDeviceResponse.model_validate(d).model_copy(update={"online": d.id in online})
        for d in queries.list_devices()
    ]


DEVICE_ACTION_RESPONSES = {
    403: {"description": "Admin scope required"},
    404: {"description": "Device not found"},
    409: {"description": "Not allowed from the device's current status"},
}
DeviceId = Path(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


async def _device_action(device_id: str, status: str, admin: User) -> AdminDeviceResponse:
    device = await device_service.set_status(device_id, status, admin.username or "")
    online = await asyncio.to_thread(queries.device_ids_for_sessions, conn_mgr.live_session_ids())
    return AdminDeviceResponse.model_validate(device).model_copy(
        update={"online": device.id in online}
    )


@router.post(
    "/devices/{device_id}/approve",
    response_model=AdminDeviceResponse,
    summary="Approve a device",
    description=(
        "`pending` → `active`: the scanner is trusted (a direct worker switch needs it). "
        "Idempotent on an `active` device; a `revoked` device answers 409."
    ),
    responses=DEVICE_ACTION_RESPONSES,
)
async def approve_device(device_id: str = DeviceId, current_user: User = Depends(require_admin)):
    return await _device_action(device_id, "active", current_user)


@router.post(
    "/devices/{device_id}/revoke",
    response_model=AdminDeviceResponse,
    summary="Revoke a device",
    description=(
        "`pending` or `active` → `revoked`, final: every session on the device ends at once "
        "(its sockets close) and it can no longer log in, register or ask for a login. The "
        "workers stay logged in on their other devices. Idempotent on a `revoked` device."
    ),
    responses=DEVICE_ACTION_RESPONSES,
)
async def revoke_device(device_id: str = DeviceId, current_user: User = Depends(require_admin)):
    return await _device_action(device_id, "revoked", current_user)


@router.get(
    "/login-requests",
    response_model=List[AdminLoginRequest],
    summary="List pending login requests",
    description="Operators waiting on their login screen for an admin's approval, oldest first.",
    responses={403: {"description": "Admin scope required"}, 503: {"description": "Redis unavailable"}},
)
async def list_login_requests(_admin: User = Depends(require_admin)):
    return await login_request_service.pending()


DECIDE_RESPONSES = {
    403: {"description": "Admin scope required"},
    404: {"description": "Request expired, cancelled or unknown"},
    409: {"description": "Already decided"},
    503: {"description": "Redis unavailable"},
}
LoginRequestId = Path(..., pattern=r"^[0-9a-f]{32}$")


@router.post(
    "/login-requests/{request_id}/approve",
    response_model=MessageResponse,
    summary="Approve a login request",
    description="The device that asked can collect one session within a short window.",
    responses=DECIDE_RESPONSES,
)
async def approve_login_request(
    request_id: str = LoginRequestId, current_user: User = Depends(require_admin)
):
    await login_request_service.decide(request_id, "approved", current_user.username or "")
    return {"message": "Login approved"}


@router.post(
    "/login-requests/{request_id}/deny",
    response_model=MessageResponse,
    summary="Deny a login request",
    description="The waiting device is told and returns to its login screen.",
    responses=DECIDE_RESPONSES,
)
async def deny_login_request(
    request_id: str = LoginRequestId, current_user: User = Depends(require_admin)
):
    await login_request_service.decide(request_id, "denied", current_user.username or "")
    return {"message": "Login denied"}


@router.post(
    "/users/{username}/logout",
    response_model=MessageResponse,
    summary="Log an operator out everywhere",
    description=(
        "Revokes every session of a client account: its access and refresh tokens stop "
        "working on the next request and its WebSocket connections are closed. Each device "
        "returns to its login screen; the password is unchanged."
    ),
    responses={
        403: {"description": "Admin scope required"},
        404: {"description": "Client account not found"},
    },
)
async def logout_user_everywhere(
    username: str = Path(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$"),
    current_user: User = Depends(require_admin),
):
    count = await auth_service.admin_logout_user(username)
    logger.info(f"Admin {current_user.username} logged out {username} everywhere")
    return {"message": f"{count} session(s) revoked"}


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
# Delta 9 (Q40): server-side filters. Times are ISO 8601; without an offset they are UTC.
CLOSED_FROM = Query(None, description="Closed at or after this time (inclusive).")
CLOSED_TO = Query(None, description="Closed at or before this time (inclusive).")
# V2_ORDERS_DELTA Q53: business days, by scan time.
DAY_FROM = Query(None, description="On or after this business day (YYYY-MM-DD).")
DAY_TO = Query(None, description="On or before this business day (YYYY-MM-DD).")
SEARCH = Query(None, max_length=100, description="Case-insensitive substring search.")


def _history_filter(closed_from, closed_to, day_from, day_to, q) -> queries.HistoryFilter:
    return queries.HistoryFilter(
        closed_from=closed_from, closed_to=closed_to, day_from=day_from, day_to=day_to, q=q
    )


@router.get(
    "/history/outbound",
    response_model=List[OutboundResponse],
    summary="Get closed outbound history",
    description=(
        "Returns only scans that have been closed by an administrator. Optional filters: close "
        "time range, day range (scan time), and `q` over label, worker and tags."
    ),
    responses={403: {"description": "Admin scope required"}},
)
def get_outbound_history(
    response: Response,
    limit: int = HISTORY_LIMIT,
    offset: int = HISTORY_OFFSET,
    current_user: User = Depends(require_admin),
    closed_from: Optional[datetime] = CLOSED_FROM,
    closed_to: Optional[datetime] = CLOSED_TO,
    day_from: Optional[date] = DAY_FROM,
    day_to: Optional[date] = DAY_TO,
    q: Optional[str] = SEARCH,
):
    items, total = queries.get_outbound_history(
        limit=limit,
        offset=offset,
        f=_history_filter(closed_from, closed_to, day_from, day_to, q),
    )
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get(
    "/history/shopee/orders",
    response_model=List[ShopeeOrderResponse],
    summary="Get completed Shopee order history",
    description=(
        "Returns only orders marked complete by outbound period closure. Optional filters: "
        "completion (close) time range, day range, and `q` over order SN, worker, "
        "tracking number and pickup code."
    ),
    responses={403: {"description": "Admin scope required"}},
)
def get_shopee_orders_history(
    response: Response,
    limit: int = HISTORY_LIMIT,
    offset: int = HISTORY_OFFSET,
    current_user: User = Depends(require_admin),
    closed_from: Optional[datetime] = CLOSED_FROM,
    closed_to: Optional[datetime] = CLOSED_TO,
    day_from: Optional[date] = DAY_FROM,
    day_to: Optional[date] = DAY_TO,
    q: Optional[str] = SEARCH,
):
    orders, total = queries.get_shopee_orders_history(
        limit=limit,
        offset=offset,
        f=_history_filter(closed_from, closed_to, day_from, day_to, q),
    )
    response.headers["X-Total-Count"] = str(total)
    return shopee_service.build_shopee_order_responses(orders)


@router.get(
    "/history/days",
    response_model=List[AdminDayResponse],
    summary="List history days",
    description=(
        "One row per business day (`BUSINESS_UTC_OFFSET`), newest first: the closed scans made "
        "that day, the completed orders they belong to, and the scans' tags. Optional day range, "
        "and `q`: only days holding a scan or an order that matches (same fields as the two "
        "history lists)."
    ),
    responses={403: {"description": "Admin scope required"}},
)
def get_day_history(
    response: Response,
    limit: int = Query(50, ge=1, le=500, description="Page size (newest first)."),
    offset: int = HISTORY_OFFSET,
    _admin: User = Depends(require_admin),
    day_from: Optional[date] = DAY_FROM,
    day_to: Optional[date] = DAY_TO,
    q: Optional[str] = SEARCH,
):
    days, total = queries.get_day_history(
        limit=limit,
        offset=offset,
        f=queries.HistoryFilter(day_from=day_from, day_to=day_to, q=q),
    )
    response.headers["X-Total-Count"] = str(total)
    return days


@router.get(
    "/history/days/{day}",
    response_model=AdminDayDetailResponse,
    summary="Get one history day",
    description="All closed scans made on one business day and the completed orders of that day.",
    responses={403: {"description": "Admin scope required"}},
)
def get_day(day: date, _admin: User = Depends(require_admin)):
    found = queries.get_day(day)
    return {
        "day": day,
        "orders": shopee_service.build_shopee_order_responses(found["orders"]),
        "scans": found["scans"],
    }


@router.get(
    "/lookup",
    response_model=AdminLookupResponse,
    summary="Find an exact label",
    description=(
        'Answers "did it leave?" for an order SN, a tracking number or a scanned label: the '
        "orders it names (ongoing or done, with `done_at` = its close) and its scans, open or "
        "closed. Exact match after trimming."
    ),
    responses={403: {"description": "Admin scope required"}},
)
def lookup_label(
    label: str = Query(..., min_length=1, max_length=1024, description="The exact label."),
    _admin: User = Depends(require_admin),
):
    found = queries.lookup_label(label)
    return {
        "label": label,
        "orders": shopee_service.build_shopee_order_responses(found["orders"]),
        "scans": found["scans"],
        "day": found["day"],
    }


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
            "Content-Disposition": f"attachment; filename=scanned_items_{business_time().strftime('%Y%m%d_%H%M%S')}.csv"
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
            "Content-Disposition": f"attachment; filename=inventory_stocks_{business_time().strftime('%Y%m%d_%H%M%S')}.csv"
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
