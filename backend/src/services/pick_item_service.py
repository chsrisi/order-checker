import logging
from typing import Optional

from .managers import conn_mgr
from . import queries
from ..models import PickItemEntry, WSMessageType
from ..exceptions import DomainException

logger = logging.getLogger("backend.services.pick_item")


async def create_pick_item_entry(
    sku: str, qty: int, username: str, order_sn: Optional[str] = None
) -> PickItemEntry:
    try:
        pie = queries.create_pick_item_entry(
            sku=sku, qty=qty, username=username, order_sn=order_sn
        )
    except LookupError as e:
        raise DomainException(status_code=404, detail=str(e))

    await conn_mgr.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, username=username
    )
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, scope="admin")
    return pie


async def assign_pick_item_entry(
    entry_id: int, order_sn: str, qty: Optional[int], username: str
) -> PickItemEntry:
    try:
        pie = queries.assign_pick_item_entry(
            entry_id=entry_id, order_sn=order_sn, qty=qty, username=username
        )
    except LookupError as e:
        raise DomainException(status_code=404, detail=str(e))
    except ValueError as e:
        raise DomainException(status_code=400, detail=str(e))

    await conn_mgr.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, username=username
    )
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, scope="admin")
    return pie


async def unassign_pick_item_entry(
    order_sn: str, sku: str, qty: int, username: str
) -> bool:
    try:
        res = queries.unassign_pick_item_entry(
            order_sn=order_sn, sku=sku, qty=qty, username=username
        )
    except LookupError as e:
        raise DomainException(status_code=404, detail=str(e))

    await conn_mgr.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, username=username
    )
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, scope="admin")
    return res


async def delete_pie(pie_id: int, username: str, is_admin: bool = False) -> bool:
    res = queries.delete_pie(pie_id=pie_id, username=username, is_admin=is_admin)
    if not res:
        raise DomainException(status_code=404, detail="Entry not found or unauthorized")

    await conn_mgr.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, username=username
    )
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, scope="admin")
    return res

def merge_or_create_pie(
    username: str,
    sku: str,
    qty: int,
    order_sn: Optional[str] = None,
) -> PickItemEntry:
    return queries.merge_or_create_pie(sku=sku, qty=qty, order_sn=order_sn, username=username)
