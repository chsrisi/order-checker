from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.models import WSMessageType
from src.services.managers import connection_manager
from src.services.managers.connection_manager import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail=False):
        self.accepted = False
        self.fail = fail
        self.messages = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        if self.fail:
            raise ConnectionError("gone")
        self.messages.append(message)


def outbound_record():
    return SimpleNamespace(
        id=1,
        content="label",
        tags=[],
        created_at=datetime.now(UTC),
        owner_user="operator",
        closed=False,
        closed_at=None,
    )


def pick_record():
    return SimpleNamespace(
        id=1,
        sku="SKU",
        qty=2,
        order_sn=None,
        timestamp=datetime.now(UTC),
        owner_user="operator",
    )


@pytest.mark.asyncio
async def test_connect_and_disconnect_tracks_sessions():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect(ws, "operator", "client")
    assert ws.accepted
    assert manager.active_connections["operator"] == [ws]
    manager.disconnect(ws, "operator")
    assert manager.active_connections == {}
    assert manager.user_scopes == {}


def test_get_data_scopes_outbounds(monkeypatch):
    manager = ConnectionManager()
    monkeypatch.setattr(
        connection_manager.queries,
        "get_user_data",
        lambda name: SimpleNamespace(scope="admin" if name == "admin" else "client"),
    )
    monkeypatch.setattr(
        connection_manager.queries,
        "get_all_outbound_data",
        lambda: [outbound_record(), outbound_record()],
    )
    monkeypatch.setattr(
        connection_manager.queries, "get_outbounds_data", lambda _: [outbound_record()]
    )
    assert len(manager._get_data(WSMessageType.OUTBOUNDS, "admin")) == 2
    assert len(manager._get_data(WSMessageType.OUTBOUNDS, "operator")) == 1


def test_get_data_builds_user_pick_and_stock_payloads(monkeypatch):
    manager = ConnectionManager()
    monkeypatch.setattr(
        connection_manager.queries, "get_user_data", lambda _: SimpleNamespace(scope="admin")
    )
    monkeypatch.setattr(
        connection_manager.queries,
        "get_all_user_data",
        lambda: [{"username": "operator", "scope": "client"}],
    )
    monkeypatch.setattr(
        connection_manager.queries, "get_pie_data", lambda username=None: [pick_record()]
    )
    monkeypatch.setattr(
        connection_manager.queries,
        "resolve_barcode_to_item",
        lambda _: SimpleNamespace(item_name="Cake"),
    )
    stock = SimpleNamespace(
        _mapping={"id": 1, "sku": "SKU", "stock": 2, "location": "A", "item_name": "Cake"}
    )
    monkeypatch.setattr(connection_manager.queries, "get_all_stocks_data", lambda **_: [stock])
    assert manager._get_data(WSMessageType.USERS, "admin")[0]["username"] == "operator"
    assert manager._get_data(WSMessageType.PICK_ITEM_ENTRIES, "admin")[0]["item_name"] == "Cake"
    assert manager._get_data(WSMessageType.STOCKS, "admin")[0]["stock"] == 2


def test_get_data_rejects_deleted_user(monkeypatch):
    monkeypatch.setattr(connection_manager.queries, "get_user_data", lambda _: None)
    with pytest.raises(ValueError, match="not found"):
        ConnectionManager()._get_data(WSMessageType.USERS, "deleted")


@pytest.mark.asyncio
async def test_send_to_session_builds_payload(monkeypatch):
    manager = ConnectionManager()
    ws = FakeWebSocket()
    monkeypatch.setattr(manager, "_get_data", lambda *_: [{"id": 1}])
    await manager.send_to_session(WSMessageType.OUTBOUNDS, ws, "operator")
    assert ws.messages == [{"type": "outbound_update", "data": [{"id": 1}]}]


@pytest.mark.asyncio
async def test_failed_send_removes_socket():
    manager = ConnectionManager()
    ws = FakeWebSocket(fail=True)
    await manager.connect(ws, "operator", "client")
    await manager._send_raw(WSMessageType.ERROR, "failure", ws, "operator")
    assert "operator" not in manager.active_connections


@pytest.mark.asyncio
async def test_send_to_user_fans_out_to_all_sessions(monkeypatch):
    manager = ConnectionManager()
    one, two = FakeWebSocket(), FakeWebSocket()
    await manager.connect(one, "operator", "client")
    await manager.connect(two, "operator", "client")
    monkeypatch.setattr(manager, "_get_data", lambda *_: [1])
    await manager.send_to_user(WSMessageType.OUTBOUNDS, "operator")
    assert one.messages == two.messages


@pytest.mark.asyncio
async def test_broadcast_honors_scope_and_reuses_admin_payload(monkeypatch):
    manager = ConnectionManager()
    admin_one, admin_two, client = FakeWebSocket(), FakeWebSocket(), FakeWebSocket()
    await manager.connect(admin_one, "admin", "admin")
    await manager.connect(admin_two, "admin", "admin")
    await manager.connect(client, "operator", "client")
    calls = []
    monkeypatch.setattr(
        manager, "_get_data", lambda _, username: calls.append(username) or [username]
    )
    await manager.broadcast(WSMessageType.STOCKS, scope="admin")
    assert len(admin_one.messages) == len(admin_two.messages) == 1
    assert client.messages == []
    assert calls == ["admin"]
