import logging
from typing import List

from .managers import cache_mgr, conn_mgr
from . import queries
from ..models import OutboundItem, WSMessageType
from ..exceptions import DomainException

logger = logging.getLogger("backend.services.outbound")


async def create_outbound_item(
    content: str, owner_username: str, tags_in: List[str]
) -> OutboundItem:
    try:
        db_item = queries.create_outbound_item(
            content=content, owner_username=owner_username, tags_in=tags_in
        )
    except ValueError as e:
        raise DomainException(status_code=409, detail=str(e))

    # Broadcast updates
    await conn_mgr.broadcast(WSMessageType.OUTBOUNDS, scope="admin")
    await conn_mgr.send_to_user(WSMessageType.OUTBOUNDS, username=owner_username)
    return db_item


async def close_outbound_items(contents: List[str], admin_username: str) -> dict:
    result = queries.close_outbound_items(contents=contents, admin_username=admin_username)
    cache_mgr.invalidate()

    # Broadcast updates
    await conn_mgr.broadcast(WSMessageType.OUTBOUNDS, scope="admin")
    await conn_mgr.broadcast(WSMessageType.SHOPEE_ORDERS, scope="admin")

    return result


async def clear_outbound_items(admin_username: str) -> int:
    """Delete all scan records and notify connected administrators."""

    count = queries.clear_all_outbound_items()
    logger.warning(
        "outbound_scans_cleared",
        extra={
            "event": "outbound.scans.cleared",
            "admin_username": admin_username,
            "deleted_count": count,
        },
    )
    await conn_mgr.broadcast(WSMessageType.OUTBOUNDS, scope="admin")
    return count
