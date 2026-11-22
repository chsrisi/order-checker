"""``/v2/ws`` (IMPLEMENTATION_PLAN T6.4, P-9): typed envelope ``{type, data, ts}``, handshake
failures as close codes after accept, events shared with v1 sockets."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src import config
from src.models import WSMessageType
from src.routers import websocket as ws_router
from src.services.managers.connection_manager import ConnectionManager
from src.services.managers.ticket_manager import TicketClaims

TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")


@pytest.fixture(autouse=True)
def no_release(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLIENT_RELEASES_DIR", str(tmp_path))
    return tmp_path


def _valid_ticket(monkeypatch, scope="client"):
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


def _client():
    from src.main import app

    return TestClient(app)


def _close_code(headers, monkeypatch=None) -> int:
    with _client().websocket_connect("/v2/ws?token=t", headers=headers) as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    return exc.value.code


def test_missing_version_closes_4400(monkeypatch):
    _valid_ticket(monkeypatch)
    assert _close_code({}) == 4400


def test_client_below_minimum_closes_4426(monkeypatch, no_release):
    _valid_ticket(monkeypatch)
    (no_release / "latest.json").write_text(
        json.dumps({"version_code": 9, "min_supported_version_code": 5})
    )
    assert _close_code({"X-Client-Version": "4"}) == 4426


@pytest.mark.parametrize("claims", [None, TicketClaims("operator", None)])
def test_bad_or_pre_session_ticket_closes_4401(monkeypatch, claims):
    monkeypatch.setattr(ws_router.ticket_mgr, "consume_ticket", AsyncMock(return_value=claims))
    assert _close_code({"X-Client-Version": "1"}) == 4401


def test_revoked_session_closes_4401(monkeypatch):
    monkeypatch.setattr(
        ws_router.ticket_mgr,
        "consume_ticket",
        AsyncMock(return_value=TicketClaims("operator", "revoked")),
    )
    monkeypatch.setattr(ws_router.queries, "get_user_for_session", lambda _u, _sid: None)
    assert _close_code({"X-Client-Version": "1"}) == 4401


def test_v2_frames_carry_type_list_data_and_ts(monkeypatch):
    _valid_ticket(monkeypatch)
    with _client().websocket_connect("/v2/ws?token=t", headers={"X-Client-Version": "1"}) as ws:
        ws.send_json({"command": "nope"})
        frame = ws.receive_json()
    assert set(frame) == {"type", "data", "ts"}
    assert frame["type"] == "error"
    assert frame["data"] == [{"detail": "Unknown command: nope"}]
    assert TS.match(frame["ts"])


class RecordingSocket:
    def __init__(self):
        self.frames = []

    async def accept(self):
        pass

    async def send_json(self, message):
        self.frames.append(message)


@pytest.mark.asyncio
async def test_one_broadcast_reaches_v1_and_v2_with_one_payload_build(monkeypatch):
    manager = ConnectionManager()
    builds = []
    monkeypatch.setattr(
        manager, "_get_data", lambda t, u, s=None: builds.append(u) or [{"sku": "A01_001"}]
    )
    v1_socket, v2_socket = RecordingSocket(), RecordingSocket()
    await manager.connect(v1_socket, "alice", "client", sid="a")
    await manager.connect(v2_socket, "bob", "client", sid="b", contract=2)

    await manager.broadcast(WSMessageType.STOCKS)

    assert len(builds) == 1  # scope-independent payload built once for both contracts
    (v1_frame,) = v1_socket.frames
    (v2_frame,) = v2_socket.frames
    assert v1_frame == {"type": "stocks_update", "data": [{"sku": "A01_001"}]}  # v1 frozen
    assert v2_frame["data"] == v1_frame["data"] and TS.match(v2_frame["ts"])


@pytest.mark.asyncio
async def test_same_operator_on_v1_and_v2_shares_one_payload(monkeypatch):
    manager = ConnectionManager()
    builds = []
    monkeypatch.setattr(manager, "_get_data", lambda t, u, s=None: builds.append(u) or [{}])
    old_app, new_app = RecordingSocket(), RecordingSocket()
    await manager.connect(old_app, "alice", "client", sid="a")
    await manager.connect(new_app, "alice", "client", sid="b", contract=2)
    await manager.broadcast(WSMessageType.PICK_ITEM_ENTRIES)
    assert builds == ["alice"]
    assert "ts" not in old_app.frames[0] and "ts" in new_app.frames[0]
    manager.disconnect(new_app, "alice")
    assert new_app not in manager.socket_contracts
