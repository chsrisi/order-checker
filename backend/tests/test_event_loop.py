"""T4.1 / F-H1: slow database work runs off the event loop."""

import asyncio
import time

import pytest

from src.services import pick_item_service, stock_service
from src.services.managers.connection_manager import ConnectionManager


async def _ticks_during(coro, window=0.3):
    """Count event-loop ticks while ``coro`` runs; a blocked loop yields ~0."""
    ticks = 0
    done = False

    async def ticker():
        nonlocal ticks
        while not done:
            await asyncio.sleep(0.01)
            ticks += 1

    t = asyncio.create_task(ticker())
    try:
        result = await coro
    finally:
        done = True
        await t
    return result, ticks


def _slow(result):
    def fn(*_a, **_kw):
        time.sleep(0.3)
        return result

    return fn


@pytest.mark.asyncio
async def test_stock_update_does_not_block_loop(monkeypatch):
    monkeypatch.setattr(stock_service.queries, "update_or_move_stock", _slow((object(), None)))
    monkeypatch.setattr(stock_service.conn_mgr, "broadcast", lambda *a, **k: asyncio.sleep(0))
    _, ticks = await _ticks_during(stock_service.update_or_move_stock("A01_001", 1, "op"))
    assert ticks >= 10


@pytest.mark.asyncio
async def test_pick_create_does_not_block_loop(monkeypatch):
    monkeypatch.setattr(pick_item_service.queries, "create_pick_item_entry", _slow(object()))
    for name in ("send_to_user", "broadcast"):
        monkeypatch.setattr(pick_item_service.conn_mgr, name, lambda *a, **k: asyncio.sleep(0))
    _, ticks = await _ticks_during(pick_item_service.create_pick_item_entry("A01_001", 1, "op"))
    assert ticks >= 10


@pytest.mark.asyncio
async def test_ws_payload_build_does_not_block_loop(monkeypatch):
    manager = ConnectionManager()
    monkeypatch.setattr(manager, "_get_data", _slow([]))

    class WS:
        async def send_json(self, _m):
            pass

    manager.active_connections["op"] = [WS()]
    manager.user_scopes[manager.active_connections["op"][0]] = "client"
    from src.models import WSMessageType

    _, ticks = await _ticks_during(manager.broadcast(WSMessageType.STOCKS))
    assert ticks >= 10
