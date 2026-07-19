import logging
from typing import List
from fastapi import APIRouter, Depends

from ..models import OutboundCloseResponse, User, OutboundCreate, OutboundResponse
from ..dependencies import get_current_user, require_admin
from ..services import outbound_service, queries

logger = logging.getLogger("backend.routers.outbound")

router = APIRouter(prefix="/outbound", tags=["outbound"])


@router.post(
    "",
    response_model=OutboundResponse,
    summary="Record an outbound scan",
    description="Stores a trimmed label value, rejects a duplicate open scan for the same user, and adds a matched order's carrier tag.",
    responses={
        401: {"description": "Invalid bearer token"},
        409: {"description": "Duplicate open scan"},
    },
)
async def create_outbound(
    item: OutboundCreate,
    current_user: User = Depends(get_current_user),
):
    logger.info(
        "outbound_scan_received",
        extra={
            "event": "outbound.scan.received",
            "username": current_user.username,
            "content_length": len(item.content),
        },
    )
    db_item = await outbound_service.create_outbound_item(
        content=item.content,
        owner_username=current_user.username,
        tags_in=item.tags if item.tags is not None else [],
    )
    logger.info(
        "outbound_scan_saved",
        extra={
            "event": "outbound.scan.saved",
            "username": current_user.username,
            "outbound_id": db_item.id,
        },
    )

    return OutboundResponse(
        id=db_item.id,
        content=db_item.content or "",
        tags=db_item.tags,
        created_at=db_item.created_at,
        owner_user=db_item.owner_user,
        closed=db_item.closed,
        closed_at=db_item.closed_at,
    )


@router.get(
    "",
    response_model=List[OutboundResponse],
    summary="List open outbound scans",
    description="Operators see their own scans; administrators see all open scans.",
    responses={401: {"description": "Invalid bearer token"}},
)
def read_outbounds(current_user: User = Depends(get_current_user)):
    logger.info(f"User {current_user.username} fetching outbound history")
    if current_user.scope == "admin":
        items = queries.get_all_outbound_data()
    else:
        items = queries.get_outbounds_data(current_user.username)
    logger.debug(f"Fetched {len(items)} items for user {current_user.username}")
    return items


@router.post(
    "/close",
    response_model=OutboundCloseResponse,
    summary="Close an outbound period",
    description="Closes matching open scans and completes orders found by order or tracking number. Duplicate input values are counted once.",
    responses={403: {"description": "Admin scope required"}},
)
async def close_outbound_period(
    contents: List[str],
    current_user: User = Depends(require_admin),
):
    result = await outbound_service.close_outbound_items(
        contents=contents,
        admin_username=current_user.username,
    )

    return result
