"""v2-only order picks (V2_PICKING_SPEC §4.1, IMPLEMENTATION_PLAN T6.18): a pick always belongs
to an order, and unassigning returns the stock. Contract v1 keeps its own ``/pick-items``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from ...dependencies import require_operator
from ...models import ORDER_SN_MAX_LENGTH, OrderPickRequest, OrderPickResponse, User
from ...services import pick_item_service
from . import GATE_RESPONSES, require_client_version

router = APIRouter(
    prefix="/v2/shopee/orders/{order_sn}/picks",
    tags=["v2 · order picks"],
    dependencies=[Depends(require_client_version)],
)

OrderSn = Annotated[str, Path(min_length=1, max_length=ORDER_SN_MAX_LENGTH)]
RESPONSES = {**GATE_RESPONSES, 403: {"description": "Admin accounts cannot work on orders"}}


@router.post(
    "",
    response_model=OrderPickResponse,
    summary="Pick an item into an order",
    description=(
        "Resolves the SKU/barcode, adds the quantity to the order and deducts stock bin by bin. "
        "Returns the resolved SKU and what the order now has of it."
    ),
    responses={
        **RESPONSES,
        404: {"description": "SKU/barcode not found, or order not claimed by the caller"},
        409: {
            "description": (
                "Order completed or no longer active on Shopee, or not enough stock "
                "(only with `STOCK_STRICT`)"
            )
        },
    },
)
async def pick(
    order_sn: OrderSn,
    body: OrderPickRequest,
    current_user: User = Depends(require_operator),
):
    line = await pick_item_service.pick_for_order(
        order_sn, body.sku, body.qty, current_user.username
    )
    return OrderPickResponse(**line._asdict())


@router.post(
    "/unassign",
    response_model=OrderPickResponse,
    summary="Remove a picked quantity from an order",
    description=(
        "Returns the quantity to stock at once. `sku` is the stored SKU of the line. Allowed on "
        "a cancelled order, not on a completed one. Returns what is left (`qty` may be 0)."
    ),
    responses={
        **RESPONSES,
        404: {"description": "Order not claimed by the caller, or nothing of the SKU picked"},
        409: {"description": "Order completed, or more than is picked; nothing changes"},
    },
)
async def unassign(
    order_sn: OrderSn,
    body: OrderPickRequest,
    current_user: User = Depends(require_operator),
):
    line = await pick_item_service.unassign_from_order(
        order_sn, body.sku, body.qty, current_user.username
    )
    return OrderPickResponse(**line._asdict())
