from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.models import (
    OutboundCreate,
    PickItemEntryAssign,
    PickItemEntryCreate,
    PickItemEntryUnassign,
    RefreshTokenRequest,
    ShopeeConfigUnlockRequest,
    ShopeeConfigUpdateRequest,
    StockCreate,
    UserAuth,
)
from src.routers import admin, admin_shopee, auth, bom, items, outbound, pick_items, shopee, stocks


def actor(username="operator", scope="client", password_hash="hash"):
    return SimpleNamespace(username=username, scope=scope, password_hash=password_hash)


def test_auth_router_delegates_login_variants(monkeypatch):
    calls = []

    def login(username, password, required_scope=None):
        calls.append((username, password, required_scope))
        return {"access_token": "a", "refresh_token": "r", "token_type": "bearer"}

    monkeypatch.setattr(auth.auth_service, "login_user", login)
    payload = UserAuth(username="operator", password="password")
    auth.login_client(payload)
    auth.login_admin(payload)
    assert calls == [
        ("operator", "password", None),
        ("operator", "password", "admin"),
    ]


@pytest.mark.asyncio
async def test_auth_register_and_ws_ticket(monkeypatch):
    tokens = {"access_token": "a", "refresh_token": "r", "token_type": "bearer"}
    monkeypatch.setattr(auth.auth_service, "register_client", AsyncMock(return_value=tokens))
    monkeypatch.setattr(auth.ticket_mgr, "generate_ticket", AsyncMock(return_value="ticket"))
    payload = UserAuth(username="operator", password="password")
    assert await auth.register_client(payload) == tokens
    assert await auth.create_ws_token(actor()) == {"token": "ticket", "expires_in": 30}


@pytest.mark.asyncio
async def test_auth_ws_ticket_maps_manager_failure(monkeypatch):
    monkeypatch.setattr(
        auth.ticket_mgr,
        "generate_ticket",
        AsyncMock(side_effect=RuntimeError("offline")),
    )
    with pytest.raises(HTTPException) as exc:
        await auth.create_ws_token(actor())
    assert exc.value.status_code == 503


def test_auth_logout_refresh_and_jwks(monkeypatch):
    monkeypatch.setattr(auth.auth_service, "logout_user", lambda token: {"token": token})
    monkeypatch.setattr(auth.auth_service, "refresh_tokens", lambda token: {"token": token})
    monkeypatch.setattr(auth.key_mgr, "get_jwks", lambda: [{"kid": "one"}])
    body = RefreshTokenRequest(refresh_token="refresh")
    assert auth.logout(body) == {"token": "refresh"}
    assert auth.refresh(body) == {"token": "refresh"}
    assert auth.jwks_endpoint() == {"keys": [{"kid": "one"}]}


@pytest.mark.asyncio
async def test_admin_user_and_clear_operations(monkeypatch):
    admin_user = actor("admin", "admin")
    monkeypatch.setattr(admin.queries, "get_all_user_data", lambda: [actor()])
    monkeypatch.setattr(admin.auth_service, "delete_user", AsyncMock())
    monkeypatch.setattr(admin.outbound_service, "clear_outbound_items", AsyncMock(return_value=3))
    assert len(admin.get_users(admin_user)) == 1
    assert "deleted" in (await admin.delete_user("operator", admin_user))["message"]
    assert await admin.clear_outbound_items(admin_user) == {
        "message": "Outbound scans cleared",
        "deleted": 3,
    }


def test_admin_history_and_exports(monkeypatch):
    admin_user = actor("admin", "admin")
    monkeypatch.setattr(admin.queries, "get_outbound_history", lambda: ["scan"])
    monkeypatch.setattr(admin.queries, "get_shopee_orders_history", lambda: ["order"])
    monkeypatch.setattr(
        admin.shopee_service, "build_shopee_order_response", lambda value: f"built-{value}"
    )
    monkeypatch.setattr(admin.queries, "get_export_scans_csv", lambda: "a,b\n1,2\n")
    monkeypatch.setattr(admin.queries, "get_export_stocks_csv", lambda: "sku,qty\nA,1\n")
    assert admin.get_outbound_history(admin_user) == ["scan"]
    assert admin.get_shopee_orders_history(admin_user) == ["built-order"]
    assert admin.export_scanned_items(admin_user).media_type == "text/csv"
    assert admin.export_stocks(admin_user).media_type == "text/csv"


def test_item_and_stock_reads(monkeypatch):
    monkeypatch.setattr(items.queries, "find_warehouse_items", lambda query: [query])
    assert items.find_warehouse_items("cake", actor()) == ["cake"]

    row = SimpleNamespace(
        _mapping={"id": 1, "sku": "SKU", "stock": 2, "location": "A", "item_name": "Cake"}
    )
    monkeypatch.setattr(stocks.queries, "get_stocks_data", lambda **_: [row])
    assert stocks.get_stocks(True, actor())[0].sku == "SKU"


@pytest.mark.asyncio
async def test_stock_update_router(monkeypatch):
    record = SimpleNamespace(sku="SKU", stock=4, location="A")
    monkeypatch.setattr(
        stocks.stock_service, "update_or_move_stock", AsyncMock(return_value=(record, "Cake"))
    )
    result = await stocks.update_stock(StockCreate(sku="SKU", stock=4), actor())
    assert result["success"] is True
    assert result["item_name"] == "Cake"


@pytest.mark.asyncio
async def test_outbound_router_create_read_and_close(monkeypatch):
    record = SimpleNamespace(
        id=1,
        content="label",
        tags=[],
        created_at=datetime.now(UTC),
        owner_user="operator",
        closed=False,
        closed_at=None,
    )
    monkeypatch.setattr(
        outbound.outbound_service, "create_outbound_item", AsyncMock(return_value=record)
    )
    response = await outbound.create_outbound(OutboundCreate(content="label"), actor())
    assert response.id == 1

    monkeypatch.setattr(outbound.queries, "get_outbounds_data", lambda _: [record])
    monkeypatch.setattr(outbound.queries, "get_all_outbound_data", lambda: [record, record])
    assert len(outbound.read_outbounds(actor())) == 1
    assert len(outbound.read_outbounds(actor("admin", "admin"))) == 2

    monkeypatch.setattr(
        outbound.outbound_service, "close_outbound_items", AsyncMock(return_value={"outbound": 1})
    )
    assert await outbound.close_outbound_period(["label"], actor("admin", "admin")) == {
        "outbound": 1
    }


@pytest.mark.asyncio
async def test_shopee_router_operations(monkeypatch):
    monkeypatch.setattr(shopee.shopee_service, "sync_shopee_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(shopee.shopee_service, "acquire_order", AsyncMock())
    assert await shopee.get_shopee_orders(False, actor()) == []
    assert (await shopee.acquire_order("ORDER", actor()))["order_sn"] == "ORDER"
    shopee.cache_mgr.set_token_fatal(True)
    assert (
        "reset"
        in (await shopee.reset_shopee_cache_state(actor("admin", "admin")))["message"].lower()
    )


@pytest.mark.asyncio
async def test_pick_router_mutations(monkeypatch):
    pie = SimpleNamespace(
        id=1,
        sku="SKU",
        qty=2,
        order_sn=None,
        timestamp=datetime.now(UTC),
        owner_user="operator",
    )
    monkeypatch.setattr(
        pick_items.pick_item_service, "create_pick_item_entry", AsyncMock(return_value=pie)
    )
    monkeypatch.setattr(
        pick_items.pick_item_service, "assign_pick_item_entry", AsyncMock(return_value=pie)
    )
    monkeypatch.setattr(pick_items.pick_item_service, "delete_pie", AsyncMock())
    monkeypatch.setattr(pick_items.pick_item_service, "unassign_pick_item_entry", AsyncMock())
    monkeypatch.setattr(
        pick_items.queries, "resolve_barcode_to_item", lambda _: SimpleNamespace(item_name="Cake")
    )
    created = await pick_items.create_pie(PickItemEntryCreate(sku="SKU", qty=2), actor())
    assigned = await pick_items.assign_pie(1, PickItemEntryAssign(order_sn="ORDER"), actor())
    assert created.item_name == assigned.item_name == "Cake"
    assert await pick_items.delete_pie(1, actor()) == {"message": "ok"}
    body = PickItemEntryUnassign(order_sn="ORDER", sku="SKU", qty=1)
    assert "unassigned" in (await pick_items.unassign_pie(body, actor()))["message"].lower()


def test_pick_router_read_is_scoped(monkeypatch):
    pie = SimpleNamespace(
        id=1,
        sku="SKU",
        qty=2,
        order_sn=None,
        timestamp=datetime.now(UTC),
        owner_user="operator",
    )
    requested = []
    monkeypatch.setattr(
        pick_items.queries,
        "get_pie_data",
        lambda username=None: requested.append(username) or [pie],
    )
    monkeypatch.setattr(pick_items.queries, "resolve_barcode_to_item", lambda _: None)
    assert len(pick_items.get_pies(actor())) == 1
    assert len(pick_items.get_pies(actor("admin", "admin"))) == 1
    assert requested == ["operator", None]


def test_bom_router_selectors(monkeypatch):
    monkeypatch.setattr(bom.queries, "get_bom_headers", lambda: ["standard"])
    monkeypatch.setattr(bom.queries, "get_marketplace_bom_headers", lambda: ["market"])
    monkeypatch.setattr(bom, "get_standard_bom_node", lambda *args: {"sku": args[0]})
    monkeypatch.setattr(bom, "get_marketplace_bom_node", lambda value: {"id": value})
    assert bom.get_bom_headers(actor("admin", "admin"))["standard"] == ["standard"]
    assert bom.get_bom_tree(" SKU ", None, actor("admin", "admin")) == {"sku": "SKU"}
    assert bom.get_bom_tree(None, 7, actor("admin", "admin")) == {"id": 7}
    with pytest.raises(HTTPException) as exc:
        bom.get_bom_tree(None, None, actor("admin", "admin"))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        bom.get_bom_tree("SKU", 7, actor("admin", "admin"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_shopee_config_token_is_bound_to_admin(monkeypatch):
    admin_user = actor("admin", "admin")
    monkeypatch.setattr(admin_shopee.redis_mgr, "get", AsyncMock(return_value="other-admin"))
    with pytest.raises(HTTPException) as exc:
        await admin_shopee.get_shopee_config("token", admin_user)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_shopee_config_unlock_and_save(monkeypatch):
    admin_user = actor("admin", "admin")
    monkeypatch.setattr(admin_shopee, "verify_password", lambda *_: True)
    monkeypatch.setattr(admin_shopee.redis_mgr, "set", AsyncMock())
    unlocked = await admin_shopee.unlock_shopee_config(
        ShopeeConfigUnlockRequest(password="password"), admin_user
    )
    assert unlocked["expires_in"] == 120

    monkeypatch.setattr(admin_shopee.redis_mgr, "get", AsyncMock(return_value="admin"))
    monkeypatch.setattr(admin_shopee.token_mgr, "set_token", AsyncMock())
    payload = ShopeeConfigUpdateRequest(access_token="access", refresh_token="refresh")
    assert (
        "saved"
        in (await admin_shopee.save_shopee_config(payload, "token", admin_user))["message"].lower()
    )
