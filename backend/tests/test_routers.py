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


@pytest.mark.asyncio
async def test_auth_router_delegates_login_variants(monkeypatch):
    calls = []

    async def login(username, password, required_scope=None, ip_address=None, agent=None):
        calls.append((username, password, required_scope, ip_address, agent))
        return {"access_token": "a", "refresh_token": "r", "token_type": "bearer"}

    monkeypatch.setattr(auth.auth_service, "login_throttled", login)
    payload = UserAuth(username="operator", password="password")
    request = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.7"), headers={"user-agent": "scanner"}
    )
    await auth.login_client(payload, request)
    await auth.login_admin(payload, request)
    assert calls == [
        ("operator", "password", None, "10.0.0.7", "scanner"),
        ("operator", "password", "admin", "10.0.0.7", "scanner"),
    ]


@pytest.mark.asyncio
async def test_auth_register_and_ws_ticket(monkeypatch):
    tokens = {"access_token": "a", "refresh_token": "r", "token_type": "bearer"}
    monkeypatch.setattr(auth.auth_service, "register_client", AsyncMock(return_value=tokens))
    monkeypatch.setattr(auth.ticket_mgr, "generate_ticket", AsyncMock(return_value="ticket"))
    payload = UserAuth(username="operator", password="password")
    assert await auth.register_client(payload) == tokens
    principal = auth.Principal(user=actor(), sid="sid-1")
    assert await auth.create_ws_token(principal) == {"token": "ticket", "expires_in": 30}
    auth.ticket_mgr.generate_ticket.assert_awaited_once_with(
        "operator", ttl_seconds=30, sid="sid-1"
    )


@pytest.mark.asyncio
async def test_auth_ws_ticket_maps_manager_failure(monkeypatch):
    monkeypatch.setattr(
        auth.ticket_mgr,
        "generate_ticket",
        AsyncMock(side_effect=RuntimeError("offline")),
    )
    with pytest.raises(HTTPException) as exc:
        await auth.create_ws_token(auth.Principal(user=actor(), sid="sid-1"))
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_auth_logout_refresh_and_jwks(monkeypatch):
    monkeypatch.setattr(
        auth.auth_service, "logout_user", AsyncMock(side_effect=lambda token: {"token": token})
    )
    monkeypatch.setattr(auth.auth_service, "refresh_tokens", lambda token: {"token": token})
    monkeypatch.setattr(auth.key_mgr, "get_jwks", lambda: [{"kid": "one"}])
    body = RefreshTokenRequest(refresh_token="refresh")
    assert await auth.logout(body) == {"token": "refresh"}
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
    monkeypatch.setattr(admin.queries, "get_outbound_history", lambda **_: (["scan"], 7))
    monkeypatch.setattr(admin.queries, "get_shopee_orders_history", lambda **_: (["order"], 1))
    monkeypatch.setattr(
        admin.shopee_service,
        "build_shopee_order_responses",
        lambda values: [f"built-{v}" for v in values],
    )
    monkeypatch.setattr(admin.queries, "get_export_scans_csv", lambda: "a,b\n1,2\n")
    monkeypatch.setattr(admin.queries, "get_export_stocks_csv", lambda: "sku,qty\nA,1\n")
    from fastapi import Response

    response = Response()
    assert admin.get_outbound_history(response, 500, 0, admin_user) == ["scan"]
    assert response.headers["X-Total-Count"] == "7"
    assert admin.get_shopee_orders_history(Response(), 500, 0, admin_user) == ["built-order"]
    assert admin.export_scanned_items(admin_user).media_type == "text/csv"
    assert admin.export_stocks(admin_user).media_type == "text/csv"


def test_admin_history_filters_reach_the_queries(monkeypatch):
    from datetime import UTC, datetime

    from fastapi import Response

    seen = {}

    def fake(name, result):
        def call(**kwargs):
            seen[name] = kwargs["f"]
            return result

        return call

    monkeypatch.setattr(admin.queries, "get_outbound_history", fake("outbound", ([], 0)))
    monkeypatch.setattr(admin.queries, "get_close_history", fake("closes", ([], 3)))
    when = datetime(2026, 11, 24, tzinfo=UTC)
    admin.get_outbound_history(Response(), 500, 0, actor("admin", "admin"), when, None, None, "x")
    assert seen["outbound"] == admin.queries.HistoryFilter(closed_from=when, q="x")
    response = Response()
    admin.get_close_history(response, 50, 0, actor("admin", "admin"), None, when)
    assert seen["closes"] == admin.queries.HistoryFilter(closed_to=when)
    assert response.headers["X-Total-Count"] == "3"


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
    monkeypatch.setattr(pick_items.queries, "item_names_for", lambda _: {})
    assert len(pick_items.get_pies(actor())) == 1
    assert len(pick_items.get_pies(actor("admin", "admin"))) == 1
    assert requested == ["operator", None]


def test_bom_router_selectors(monkeypatch):
    monkeypatch.setattr(bom.queries, "get_bom_headers", lambda: ["standard"])
    monkeypatch.setattr(bom.queries, "get_marketplace_bom_headers", lambda: ["market"])
    monkeypatch.setattr(bom, "get_standard_bom_node", lambda *args: {"sku": args[0]})
    monkeypatch.setattr(bom, "get_marketplace_bom_node", lambda value, *args: {"id": value})
    assert bom.get_bom_headers(actor("admin", "admin"))["standard"] == ["standard"]
    assert bom.get_bom_tree(" SKU ", None, 1, actor("admin", "admin")) == {"sku": "SKU"}
    assert bom.get_bom_tree(None, 7, 1, actor("admin", "admin")) == {"id": 7}
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


def test_shopee_config_token_is_a_header_not_a_query_param():
    """T5.1 / F-M18."""
    from src.main import app

    schema = app.openapi()
    for path, method in (
        ("/admin/shopee-config", "get"),
        ("/admin/shopee-config", "post"),
        ("/admin/shopee-config/lock", "post"),
    ):
        params = {(p["in"], p["name"]) for p in schema["paths"][path][method].get("parameters", [])}
        assert ("header", "X-Config-Token") in params
        assert ("query", "token") not in params
