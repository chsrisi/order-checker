import logging
from typing import List
from fastapi import APIRouter, Depends

from ..models import User, WarehouseItemResponse
from ..dependencies import get_current_user
from ..services import queries

logger = logging.getLogger("backend.routers.items")

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/find", response_model=List[WarehouseItemResponse])
def find_warehouse_items(
    query: str,
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} searching for: {query}")
    results = queries.find_warehouse_items(query)
    logger.debug(f"Found {len(results)} matches for query '{query}'")
    return results
