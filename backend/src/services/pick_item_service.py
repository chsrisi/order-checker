import asyncio
import logging
from typing import Optional

from .managers import conn_mgr
from . import queries
from ..models import PickItemEntry, WSMessageType
from ..exceptions import DomainException

logger = logging.getLogger("backend.services.pick_item")

# Each query below is one transaction (T4.2); WS events are published only after it committed.


async def create_pick_item_entry(
    sku: str, qty: int, username: str, order_sn: Optional[str] = None
) -> PickItemEntry:
    try:
        pie = await asyncio.to_thread(
            queries.create_pick_item_entry, sku=sku, qty=qty, username=username, order_sn=order_sn
        )
    except LookupError as e:
        raise DomainException(status_code=404, detail=str(e))
    except queries.OrderClosedError as e:
        raise DomainException(status_code=409, detail=str(e))

    await conn_mgr.send_to_user(WSMessageType.PICK_ITEM_ENTRIES, username=username)
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, scope="admin")
    await conn_mgr.broadcast(WSMessageType.STOCKS)
    return pie


async def assign_pick_item_entry(
    entry_id: int, order_sn: str, qty: Optional[int], username: str
) -> PickItemEntry:
    try:
        pie = await asyncio.to_thread(
            queries.assign_pick_item_entry,
            entry_id=entry_id,
            order_sn=order_sn,
            qty=qty,
            username=username,
        )
    except LookupError as e:
        raise DomainException(status_code=404, detail=str(e))
    except queries.OrderClosedError as e:
        raise DomainException(status_code=409, detail=str(e))
    except ValueError as e:
        raise DomainException(status_code=400, detail=str(e))

    await conn_mgr.send_to_user(WSMessageType.PICK_ITEM_ENTRIES, username=username)
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, scope="admin")
    return pie


async def unassign_pick_item_entry(order_sn: str, sku: str, qty: int, username: str) -> bool:
    try:
        res = await asyncio.to_thread(
            queries.unassign_pick_item_entry, order_sn=order_sn, sku=sku, qty=qty, username=username
        )
    except LookupError as e:
        raise DomainException(status_code=404, detail=str(e))

    await conn_mgr.send_to_user(WSMessageType.PICK_ITEM_ENTRIES, username=username)
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, scope="admin")
    return res


async def delete_pie(pie_id: int, username: str, is_admin: bool = False) -> bool:
    res = await asyncio.to_thread(
        queries.delete_pie, pie_id=pie_id, username=username, is_admin=is_admin
    )
    if not res:
        raise DomainException(status_code=404, detail="Entry not found or unauthorized")

    await conn_mgr.send_to_user(WSMessageType.PICK_ITEM_ENTRIES, username=username)
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, scope="admin")
    await conn_mgr.broadcast(WSMessageType.STOCKS)  # delete restores stock (D1.4.2)
    return res
