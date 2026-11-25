"""T4.8 / F-M2, F-M3, F-M4: partial syncs are never marked done; upstream errors are 502/503."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.models import ShopeeResponse
from src.services import shopee_service


def _wire_sync(monkeypatch, chunk_outcomes, local_active=(), auto_closed=0, owners=()):
    monkeypatch.setenv("MOCK_ORDER_BYPASS", "0")
    monkeypatch.setattr(shopee_service, "MOCK_ORDER_BYPASS", False)
    monkeypatch.setattr(shopee_service.cache_mgr, "is_valid", lambda: False)
    mark = MagicMock()
    monkeypatch.setattr(shopee_service.cache_mgr, "mark_synced", mark)
    monkeypatch.setattr(shopee_service.conn_mgr, "broadcast", AsyncMock())
    monkeypatch.setattr(shopee_service.conn_mgr, "send_to_user", AsyncMock())
    monkeypatch.setattr(shopee_service, "SHOPEE_ORDER_CHUNK_SIZE", 1)
    sns = [f"SN{i}" for i in range(len(chunk_outcomes))]

    async def fake_sns(status, *_a):
        return sns if status == "READY_TO_SHIP" else []

    monkeypatch.setattr(shopee_service, "fetch_sns_for_status", fake_sns)
    asked_local = []

    def fake_local(exclude):
        asked_local.append(list(exclude))
        return list(local_active)

    monkeypatch.setattr(shopee_service.queries, "local_active_order_sns", fake_local)
    outcomes = dict(
        zip(sns + list(local_active), chunk_outcomes + [([], {}, set())] * len(local_active))
    )
    fetched = []

    async def fake_chunk(chunk):
        fetched.extend(chunk)
        result = outcomes[chunk[0]]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(shopee_service, "fetch_chunk_details", fake_chunk)
    stored = []
    monkeypatch.setattr(
        shopee_service.queries, "sync_shopee_orders_to_db", lambda chunks: stored.append(chunks)
    )
    monkeypatch.setattr(
        shopee_service.queries,
        "close_shipped_outbound",
        lambda: {"outbound": auto_closed, "orders_done": 0, "owners": list(owners)},
    )
    monkeypatch.setattr(shopee_service, "_orders_visible_to", lambda *_: [])
    return mark, stored, fetched, asked_local


@pytest.mark.asyncio
async def test_failed_chunk_stores_the_rest_but_never_marks_synced(monkeypatch):
    ok = (["detail"], {}, set())
    failure = HTTPException(status_code=502, detail="Failed to fetch order details from Shopee")
    mark, stored, _, _ = _wire_sync(monkeypatch, [ok, failure, ok])

    with pytest.raises(HTTPException) as exc:
        await shopee_service.sync_shopee_orders(refresh=True, username="op", scope="client")

    assert exc.value.status_code == 502
    assert stored == [[ok, ok]]
    mark.assert_not_called()


@pytest.mark.asyncio
async def test_complete_sync_marks_synced_and_refreshes_old_local_orders(monkeypatch):
    ok = ([], {}, set())
    mark, _, fetched, asked = _wire_sync(monkeypatch, [ok], local_active=["OLD-OPEN"])
    await shopee_service.sync_shopee_orders(refresh=True, username="op", scope="client")
    assert asked == [["SN0"]]
    assert fetched == ["SN0", "OLD-OPEN"]
    mark.assert_called_once()


@pytest.mark.asyncio
async def test_open_circuit_is_503(monkeypatch):
    monkeypatch.setattr(shopee_service.cache_mgr, "is_token_fatal", lambda: True)
    with pytest.raises(HTTPException) as exc:
        await shopee_service.shopee_request("/api/v2/order/get_order_list")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_failed_order_list_is_502(monkeypatch):
    monkeypatch.setattr(shopee_service, "shopee_request", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as exc:
        await shopee_service.fetch_sns_for_status("READY_TO_SHIP", 0, 1)
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_failed_tracking_lookup_keeps_packages_out_of_the_update(monkeypatch):
    from src.models import (
        ILImageInfo,
        ODItemList,
        ODPackageList,
        ODRecipientAddress,
        OrderListT,
        ShpOrderDetails,
    )

    detail = ShpOrderDetails(
        order_sn="SN1",
        order_status="PROCESSED",
        ship_by_date=datetime.now(UTC),
        item_list=[
            ODItemList(
                item_id=1,
                item_name="Synthetic",
                item_sku="S",
                model_quantity_purchased=1,
                image_info=ILImageInfo(image_url="http://example.invalid/i.jpg"),
            )
        ],
        package_list=[
            ODPackageList(package_number="P1", logistics_status="L", shipping_carrier="C")
        ],
        split_up=False,
        recipient_address=ODRecipientAddress(name="Synthetic", city="Town"),
    )

    async def fake_request(path, **_kw):
        if path == "/api/v2/order/get_order_detail":
            return ShopeeResponse(
                error="", message="", response=OrderListT(order_list=[detail]), request_id="r"
            )
        return None  # tracking lookup fails

    monkeypatch.setattr(shopee_service, "shopee_request", fake_request)
    _, tracking, failed = await shopee_service.fetch_chunk_details(["SN1"])
    assert tracking == {} and failed == {"P1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_closed", [0, 2])
async def test_a_sync_sends_admins_the_scans_only_when_it_closed_some(monkeypatch, auto_closed):
    """V2_ORDERS_DELTA C1."""
    _wire_sync(monkeypatch, [([], {}, set())], auto_closed=auto_closed)
    await shopee_service.sync_shopee_orders(refresh=True, username=None, scope="admin")
    sent = [c.args[0].value for c in shopee_service.conn_mgr.broadcast.await_args_list]
    assert sent.count("outbound_update") == (1 if auto_closed else 0)


@pytest.mark.asyncio
async def test_a_partial_sync_still_closes_what_it_stored(monkeypatch):
    failure = HTTPException(status_code=502, detail="x")
    _wire_sync(monkeypatch, [([], {}, set()), failure], auto_closed=1, owners=["alice"])
    with pytest.raises(HTTPException):
        await shopee_service.sync_shopee_orders(refresh=True, username=None, scope="admin")
    sent = [c.args[0].value for c in shopee_service.conn_mgr.broadcast.await_args_list]
    assert sent == ["outbound_update"]
    # Q81: the owner of a completed order is told too, although the sync failed.
    told = [c.kwargs["username"] for c in shopee_service.conn_mgr.send_to_user.await_args_list]
    assert told == ["alice"]
