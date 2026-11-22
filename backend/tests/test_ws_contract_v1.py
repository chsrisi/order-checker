"""WebSocket frame rules of operator client contract v1 (KNOWN_LIMITATIONS.md #8).

Both Flutter apps run ``List<Map<String, dynamic>>.from(frame['data'])`` *before* looking at
``frame['type']``, so every frame must carry ``data`` as a JSON list of objects, and a bad
ticket must be rejected with an HTTP 403 handshake (the client matches "403").
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from src.models import WSMessageType
from src.routers import websocket as ws_router
from src.services.managers import connection_manager
from src.services.managers.connection_manager import ConnectionManager
from src.services.managers.ticket_manager import TicketClaims

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _fake_queries(monkeypatch, scope="client"):
    q = connection_manager.queries
    user = SimpleNamespace(username="operator", scope=scope)
    monkeypatch.setattr(q, "get_user_data", lambda _u: user)
    outbound = SimpleNamespace(
        id=1,
        content="label",
        tags=["tag"],
        created_at=NOW,
        owner_user="operator",
        closed=False,
        closed_at=None,
    )
    monkeypatch.setattr(q, "get_outbounds_data", lambda _u: [outbound])
    monkeypatch.setattr(q, "get_all_outbound_data", lambda: [outbound])
    pick = SimpleNamespace(
        id=1, sku="A01_001", qty=2, order_sn=None, timestamp=NOW, owner_user="operator"
    )
    monkeypatch.setattr(q, "get_pie_data", lambda **_: [pick])
    monkeypatch.setattr(q, "item_names_for", lambda _skus: {})
    stock_row = SimpleNamespace(
        _mapping={"id": 1, "sku": "A01_001", "stock": 3, "location": None, "item_name": None}
    )
    monkeypatch.setattr(q, "get_stocks_data", lambda **_: [stock_row])
    monkeypatch.setattr(q, "get_all_user_data", lambda: [user])
    monkeypatch.setattr(q, "get_shopee_order_data", lambda _u: [])
    monkeypatch.setattr(q, "get_all_shopee_order_data", lambda: [])


@pytest.mark.parametrize(
    "message_type",
    [
        WSMessageType.OUTBOUNDS,
        WSMessageType.SHOPEE_ORDERS,
        WSMessageType.PICK_ITEM_ENTRIES,
        WSMessageType.STOCKS,
    ],
)
@pytest.mark.parametrize("scope", ["client", "admin"])
def test_ws_payloads_are_lists_of_objects(monkeypatch, message_type, scope):
    _fake_queries(monkeypatch, scope)
    data = ConnectionManager()._get_data(message_type, "operator")
    assert isinstance(data, list)
    assert all(isinstance(item, dict) for item in data)


def _client_with_ticket(monkeypatch, scope="client"):
    monkeypatch.setattr(
        ws_router.ticket_mgr,
        "consume_ticket",
        AsyncMock(return_value=TicketClaims("operator", "sid-1")),
    )
    monkeypatch.setattr(
        ws_router.queries,
        "get_user_for_session",
        lambda _u, _sid: SimpleNamespace(username="operator", scope=scope),
    )
    from src.main import app

    return TestClient(app)


@pytest.mark.parametrize("command", [{"command": "nope"}, {"command": "get_users"}])
def test_ws_error_frames_carry_list_data(monkeypatch, command):
    client = _client_with_ticket(monkeypatch, scope="client")
    with client.websocket_connect("/ws?token=t") as ws:
        ws.send_json(command)
        frame = ws.receive_json()
    assert frame["type"] == "error"
    assert isinstance(frame["data"], list)
    assert all(isinstance(item, dict) for item in frame["data"])


@pytest.mark.parametrize("url", ["/ws", "/ws?token=bad"])
def test_ws_bad_ticket_is_rejected_with_http_403(monkeypatch, url):
    monkeypatch.setattr(ws_router.ticket_mgr, "consume_ticket", AsyncMock(return_value=None))
    from src.main import app

    with pytest.raises(WebSocketDenialResponse) as exc:
        with TestClient(app).websocket_connect(url):
            pass
    assert exc.value.status_code == 403


def test_ws_ticket_of_a_revoked_session_is_rejected_with_http_403(monkeypatch):
    """T6.2: the ticket is valid but its session was revoked meanwhile."""
    monkeypatch.setattr(
        ws_router.ticket_mgr,
        "consume_ticket",
        AsyncMock(return_value=TicketClaims("operator", "revoked")),
    )
    monkeypatch.setattr(ws_router.queries, "get_user_for_session", lambda _u, _sid: None)
    from src.main import app

    with pytest.raises(WebSocketDenialResponse) as exc:
        with TestClient(app).websocket_connect("/ws?token=t"):
            pass
    assert exc.value.status_code == 403


def test_users_payload_never_contains_password_hash(monkeypatch):
    _fake_queries(monkeypatch, "admin")
    monkeypatch.setattr(
        connection_manager.queries,
        "get_all_user_data",
        lambda: [SimpleNamespace(username="operator", scope="client", password_hash="SECRET")],
    )
    data = ConnectionManager()._get_data(WSMessageType.USERS, "operator")
    assert data == [{"username": "operator", "scope": "client"}]


@pytest.mark.parametrize(
    "message_type, field",
    [(WSMessageType.OUTBOUNDS, "created_at"), (WSMessageType.PICK_ITEM_ENTRIES, "timestamp")],
)
def test_ws_datetimes_are_utc_z(monkeypatch, message_type, field):
    """T4.6: frames carry Dart-parsable UTC instants (``...Z``)."""
    import re

    _fake_queries(monkeypatch, "client")
    (item,) = ConnectionManager()._get_data(message_type, "operator")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$", item[field])
