import logging
from typing import List
from fastapi import APIRouter, Depends

from ..models import User, OutboundCreate, OutboundResponse
from ..dependencies import get_current_user, require_admin
from ..services import outbound_service, queries

logger = logging.getLogger("backend.routers.outbound")

router = APIRouter(prefix="/outbound", tags=["outbound"])


@router.post("", response_model=OutboundResponse)
async def create_outbound(
    item: OutboundCreate,
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} scanning item: {item.content}")
    db_item = await outbound_service.create_outbound_item(
        content=item.content,
        owner_username=current_user.username,
        tags_in=item.tags if item.tags is not None else [],
    )
    logger.info(f"Item {db_item.id} saved for user {current_user.username}")

    return OutboundResponse(
        id=db_item.id,
        content=db_item.content or "",
        tags=db_item.tags,
        created_at=db_item.created_at,
        owner_user=db_item.owner_user,
        closed=db_item.closed,
        closed_at=db_item.closed_at,
    )


@router.get("", response_model=List[OutboundResponse])
def read_outbounds(current_user: User = Depends(get_current_user)):
    logger.info(f"User {current_user.username} fetching outbound history")
    if current_user.scope == "admin":
        items = queries.get_all_outbound_data()
    else:
        items = queries.get_outbounds_data(current_user.username)
    logger.debug(f"Fetched {len(items)} items for user {current_user.username}")
    return items


@router.post("/close")
async def close_outbound_period(
    contents: List[str],
    current_user: User = Depends(require_admin),
):
    result = await outbound_service.close_outbound_items(
        contents=contents,
        admin_username=current_user.username,
    )

    return result
