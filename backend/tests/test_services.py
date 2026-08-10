from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.exceptions import DomainException
from src.services import outbound_service, pick_item_service, shopee_service, stock_service


@pytest.mark.asyncio
async def test_outbound_duplicate_becomes_conflict(monkeypatch):
    def duplicate(**_):
        raise ValueError("Duplicate scan detected")

    monkeypatch.setattr(outbound_service.queries, "create_outbound_item", duplicate)
    with pytest.raises(DomainException) as exc:
        await outbound_service.create_outbound_item("label", "operator", [])
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_outbound_create_broadcasts_to_admin_and_owner(monkeypatch):
    item = SimpleNamespace(id=1)
    monkeypatch.setattr(outbound_service.queries, "create_outbound_item", lambda **_: item)
    monkeypatch.setattr(outbound_service.conn_mgr, "broadcast", AsyncMock())
    monkeypatch.setattr(outbound_service.conn_mgr, "send_to_user", AsyncMock())
    assert await outbound_service.create_outbound_item("label", "operator", []) is item
    outbound_service.conn_mgr.broadcast.assert_awaited_once()
    outbound_service.conn_mgr.send_to_user.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_outbounds_returns_count_and_broadcasts(monkeypatch):
    monkeypatch.setattr(outbound_service.queries, "clear_all_outbound_items", lambda: 4)
    monkeypatch.setattr(outbound_service.conn_mgr, "broadcast", AsyncMock())
    assert await outbound_service.clear_outbound_items("admin") == 4
    outbound_service.conn_mgr.broadcast.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [(LookupError("missing"), 404), (ValueError("bad"), 400)],
)
async def test_stock_errors_become_domain_errors(monkeypatch, error, status_code):
    def fail(**_):
        raise error

    monkeypatch.setattr(stock_service.queries, "update_or_move_stock", fail)
    with pytest.raises(DomainException) as exc:
        await stock_service.update_or_move_stock("SKU", 1, "operator")
    assert exc.value.status_code == status_code


@pytest.mark.asyncio
async def test_pick_missing_item_becomes_not_found(monkeypatch):
    def fail(**_):
        raise LookupError("missing")

    monkeypatch.setattr(pick_item_service.queries, "create_pick_item_entry", fail)
    with pytest.raises(DomainException) as exc:
        await pick_item_service.create_pick_item_entry("SKU", 1, "operator")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_pick_enforces_query_result(monkeypatch):
    monkeypatch.setattr(pick_item_service.queries, "delete_pie", lambda **_: False)
    with pytest.raises(DomainException) as exc:
        await pick_item_service.delete_pie(1, "operator")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_acquire_order_rejects_existing_owner(monkeypatch):
    def conflict(*_):
        raise ValueError("Order is already assigned to another operator")

    monkeypatch.setattr(shopee_service.queries, "acquire_order", conflict)
    with pytest.raises(DomainException) as exc:
        await shopee_service.acquire_order("ORDER", "operator")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_fetch_chunk_details_chunks_packages(monkeypatch):
    from datetime import datetime, timezone
    from src.models import (
        ILImageInfo,
        MTNSuccessList,
        ODItemList,
        ODPackageList,
        ODRecipientAddress,
        OrderListT,
        ShopeeResponse,
        ShpMassTrackingNumber,
        ShpOrderDetails,
    )

    # 60 packages across orders
    order_details = [
        ShpOrderDetails(
            order_sn=f"SN_{i}",
            order_status="PROCESSED",
            ship_by_date=datetime.now(timezone.utc),
            note=None,
            item_list=[
                ODItemList(
                    item_id=1,
                    item_name="Item 1",
                    item_sku="SKU1",
                    model_quantity_purchased=1,
                    image_info=ILImageInfo(image_url="http://example.com/img.jpg"),
                )
            ],
            package_list=[
                ODPackageList(
                    package_number=f"PKG_{i}_{j}",
                    logistics_status="LOGISTICS_READY",
                    shipping_carrier="Standard",
                )
                for j in range(2)
            ],
            split_up=False,
            recipient_address=ODRecipientAddress(name="User", city="City"),
        )
        for i in range(30)
    ]
    # Total 60 packages

    mass_tracking_calls = []

    async def mock_shopee_request(path, params=None, body=None, method="GET", **kwargs):
        if path == "/api/v2/order/get_order_detail":
            return ShopeeResponse(
                error="",
                message="",
                response=OrderListT(order_list=order_details),
                request_id="req_1",
            )
        elif path == "/api/v2/logistics/get_mass_tracking_number":
            mass_tracking_calls.append(body)
            pkg_list = body.get("package_list", [])
            successes = [
                MTNSuccessList(
                    package_number=p["package_number"],
                    tracking_number=f"TRK_{p['package_number']}",
                    pickup_code=None,
                )
                for p in pkg_list
            ]
            return ShopeeResponse(
                error="",
                message="",
                response=ShpMassTrackingNumber(success_list=successes, fail_list=[]),
                request_id="req_2",
            )
        return None

    monkeypatch.setattr(shopee_service, "shopee_request", mock_shopee_request)

    chunk_sns = [f"SN_{i}" for i in range(30)]
    details, tracking_map, fail_pkgs = await shopee_service.fetch_chunk_details(chunk_sns)

    assert len(details) == 30
    assert len(tracking_map) == 60
    assert len(fail_pkgs) == 0

    # Verify get_mass_tracking_number was called twice: once with 50 packages, once with 10 packages
    assert len(mass_tracking_calls) == 2
    assert len(mass_tracking_calls[0]["package_list"]) == 50
    assert len(mass_tracking_calls[1]["package_list"]) == 10


