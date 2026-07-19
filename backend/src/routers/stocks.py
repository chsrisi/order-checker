import logging
from typing import List
from fastapi import APIRouter, Depends
from ..models import StockCreate, StockResponse, StockUpdateResponse, User
from ..dependencies import get_current_user
from ..services import stock_service, queries

logger = logging.getLogger("backend.routers.stocks")

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get(
    "",
    response_model=List[StockResponse],
    summary="List inventory",
    description="Returns stock by SKU and location; optionally includes the warehouse item name.",
    responses={401: {"description": "Invalid bearer token"}},
)
def get_stocks(
    join_warehouse: bool = False,
    current_user: User = Depends(get_current_user),
):
    items = queries.get_stocks_data(join_warehouse=join_warehouse)
    return [StockResponse.model_validate(dict(i._mapping)) for i in items]


@router.post(
    "/update",
    response_model=StockUpdateResponse,
    summary="Adjust or transfer inventory",
    description="Sets/adds inventory at a location, or transfers a positive quantity to `move_to` without allowing negative source stock.",
    responses={
        400: {"description": "Invalid mode, quantity, or transfer"},
        404: {"description": "SKU/barcode not found"},
    },
)
async def update_stock(
    payload: StockCreate,
    current_user: User = Depends(get_current_user),
):
    res, item_name = await stock_service.update_or_move_stock(
        sku_in=payload.sku,
        stock_qty=payload.stock,
        username=current_user.username,
        mode=payload.mode,
        location=payload.location,
        move_to=payload.move_to,
        is_location_set=payload.location is not None,
    )

    return {
        "success": True,
        "sku": res.sku,
        "stock": res.stock,
        "item_name": item_name,
        "location": res.location,
    }
