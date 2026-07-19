import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import User, OutboundCreate, OutboundResponse, OutboundItem, WSMessageType
from ..dependencies import get_db, get_current_user
from ..services import outbound_service
from ..services.manager import conn_mgr

logger = logging.getLogger("backend.routers.outbound")

router = APIRouter(tags=["outbound"])


@router.post("/outbound", response_model=OutboundResponse)
async def create_outbound(
    item: OutboundCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} scanning item: {item.content}")
    db_item = outbound_service.create_outbound_item(
        db=db,
        content=item.content,
        owner_username=current_user.username,
        tags_in=item.tags if item.tags is not None else [],
    )
    db.commit()
    db.refresh(db_item)
    logger.info(f"Item {db_item.id} saved for user {current_user.username}")

    # Broadcast updates
    await conn_mgr.broadcast(WSMessageType.OUTBOUNDS, db, scope="admin")
    await conn_mgr.send_to_user(
        WSMessageType.OUTBOUNDS, db, username=current_user.username
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


@router.get("/outbound", response_model=List[OutboundResponse])
def read_outbounds(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    logger.info(f"User {current_user.username} fetching outbound history")
    if current_user.scope == "admin":
        items = (
            db.execute(
                select(OutboundItem)
                .filter(OutboundItem.closed == False)  # noqa: E712
                .order_by(OutboundItem.created_at.desc())
            )
            .scalars()
            .unique()
            .all()
        )
    else:
        items = (
            db.execute(
                select(OutboundItem)
                .filter(
                    OutboundItem.owner_user == current_user.username,
                    OutboundItem.closed == False,  # noqa: E712
                )
                .order_by(OutboundItem.created_at.desc())
            )
            .scalars()
            .unique()
            .all()
        )
    logger.debug(f"Fetched {len(items)} items for user {current_user.username}")
    return items


@router.post("/outbound/close")
async def close_outbound_period(
    contents: List[str],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    result = outbound_service.close_outbound_items(
        db=db,
        contents=contents,
        admin_username=current_user.username,
    )

    # Broadcast updates
    await conn_mgr.broadcast(WSMessageType.OUTBOUNDS, db, scope="admin")
    await conn_mgr.broadcast(WSMessageType.SHOPEE_ORDERS, db, scope="admin")

    return result
