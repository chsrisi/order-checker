from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models import (
    OutboundCreate,
    PickItemEntryAssign,
    PickItemEntryCreate,
    ShopeeOrderResponse,
    StockCreate,
    UserAuth,
)


@pytest.mark.parametrize("username", ["operator", "operator_1", "A123"])
def test_user_auth_accepts_supported_usernames(username: str):
    assert UserAuth(username=username, password="password").username == username


@pytest.mark.parametrize("username", ["", "user-name", "user name", "user@example.com"])
def test_user_auth_rejects_unsupported_usernames(username: str):
    with pytest.raises(ValidationError):
        UserAuth(username=username, password="password")


@pytest.mark.parametrize("qty", [0, -1])
def test_pick_quantity_must_be_positive(qty: int):
    with pytest.raises(ValidationError):
        PickItemEntryCreate(sku="SKU-1", qty=qty)


def test_assign_quantity_must_be_positive_when_present():
    with pytest.raises(ValidationError):
        PickItemEntryAssign(order_sn="ORDER-1", qty=0)


def test_stock_mode_is_constrained():
    with pytest.raises(ValidationError):
        StockCreate(sku="SKU-1", stock=1, mode="replace")


@pytest.mark.parametrize(
    "payload",
    [
        {"sku": "SKU-1", "stock": 0, "location": "A", "move_to": "B"},
        {"sku": "SKU-1", "stock": 1, "location": "A", "move_to": "A"},
    ],
)
def test_stock_transfer_requires_positive_quantity_and_distinct_locations(payload):
    with pytest.raises(ValidationError):
        StockCreate(**payload)


def test_outbound_content_cannot_be_empty():
    with pytest.raises(ValidationError):
        OutboundCreate(content="")


def test_shopee_response_lists_are_not_shared():
    first = ShopeeOrderResponse(order_sn="1", status="READY_TO_SHIP", ship_by=datetime.now(UTC))
    second = ShopeeOrderResponse(order_sn="2", status="READY_TO_SHIP", ship_by=datetime.now(UTC))
    first.item_list.append(object())  # type: ignore[arg-type]
    assert second.item_list == []
