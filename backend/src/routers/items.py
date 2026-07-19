import logging
from typing import List
from fastapi import APIRouter, Depends, Query

from ..models import User, WarehouseItemResponse
from ..dependencies import get_current_user
from ..services import queries

logger = logging.getLogger("backend.routers.items")

router = APIRouter(prefix="/items", tags=["items"])


@router.get(
    "/find",
    response_model=List[WarehouseItemResponse],
    summary="Find warehouse items",
    description="Performs case-insensitive SKU/name lookup and recognizes configured barcode aliases.",
    responses={401: {"description": "Invalid bearer token"}},
)
def find_warehouse_items(
    query: str = Query(min_length=1, max_length=200),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} searching for: {query}")
    results = queries.find_warehouse_items(query)
    logger.debug(f"Found {len(results)} matches for query '{query}'")
    return results
