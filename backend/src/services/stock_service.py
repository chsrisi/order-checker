import logging
from typing import Optional

from .managers import conn_mgr
from . import queries
from ..models import Stock, WSMessageType
from ..exceptions import DomainException

logger = logging.getLogger("backend.services.stock")


async def update_or_move_stock(
    sku_in: str,
    stock_qty: int,
    username: str,
    mode: str = "set",
    location: Optional[str] = None,
    move_to: Optional[str] = None,
    is_location_set: bool = True,
) -> tuple[Stock, Optional[str]]:
    try:
        res, item_name = queries.update_or_move_stock(
            sku_in=sku_in,
            stock_qty=stock_qty,
            username=username,
            mode=mode,
            location=location,
            move_to=move_to,
            is_location_set=is_location_set,
        )
    except LookupError as e:
        raise DomainException(status_code=404, detail=str(e))
    except ValueError as e:
        raise DomainException(status_code=400, detail=str(e))

    await conn_mgr.broadcast(WSMessageType.STOCKS)
    return res, item_name


async def get_or_merge_stock(sku: str, location: Optional[str], qty: int, username: str) -> Stock:
    try:
        res = queries.get_or_merge_stock(sku=sku, location=location, qty=qty, username=username)
    except ValueError as e:
        raise DomainException(status_code=400, detail=str(e))

    await conn_mgr.broadcast(WSMessageType.STOCKS)
    return res
