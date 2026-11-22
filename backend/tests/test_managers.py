import json
import asyncio
from unittest.mock import AsyncMock

import pytest

from src.services.managers import shopee_cache_manager, ticket_manager
from src.services.managers.shopee_cache_manager import ShopeeOrderCacheManager
from src.services.managers.ticket_manager import TicketManager


def test_cache_lifecycle(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(shopee_cache_manager.time, "time", lambda: now[0])
    cache = ShopeeOrderCacheManager(cache_ttl=120)
    assert not cache.is_valid()
    cache.mark_synced()
    assert cache.is_valid()
    now[0] += 121
    assert not cache.is_valid()


def test_mark_synced_clears_fatal_state():
    cache = ShopeeOrderCacheManager()
    cache.set_token_fatal()
    cache.mark_synced()
    assert not cache.is_token_fatal()


@pytest.mark.asyncio
async def test_ticket_is_stored_without_being_logged(monkeypatch, caplog):
    redis = SimpleRedis()
    monkeypatch.setattr(ticket_manager, "redis_mgr", redis)
    ticket = await TicketManager().generate_ticket("operator", ttl_seconds=10, sid="s1")
    assert json.loads(redis.values[f"ws_token:{ticket}"]) == {"username": "operator", "sid": "s1"}
    assert ticket not in caplog.text


@pytest.mark.asyncio
async def test_ticket_is_consumed_once(monkeypatch):
    redis = SimpleRedis()
    monkeypatch.setattr(ticket_manager, "redis_mgr", redis)
    manager = TicketManager()
    ticket = await manager.generate_ticket("operator", sid="s1")
    assert await manager.consume_ticket(ticket) == ("operator", "s1")
    assert await manager.consume_ticket(ticket) is None


@pytest.mark.asyncio
async def test_ticket_from_before_sessions_is_rejected(monkeypatch):
    redis = SimpleRedis()
    monkeypatch.setattr(ticket_manager, "redis_mgr", redis)
    redis.values["ws_token:old"] = "operator"  # pre-T6.2 value: a bare username
    assert await TicketManager().consume_ticket("old") is None


@pytest.mark.asyncio
async def test_ticket_generation_fails_closed(monkeypatch):
    broken = AsyncMock()
    broken.set.side_effect = ConnectionError("offline")
    monkeypatch.setattr(ticket_manager, "redis_mgr", broken)
    with pytest.raises(RuntimeError, match="Unable to create"):
        await TicketManager().generate_ticket("operator")


class SimpleRedis:
    """Each call yields once, like a network round trip, so interleavings are realistic."""

    def __init__(self):
        self.values: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        await asyncio.sleep(0)
        self.values[key] = value

    async def get(self, key):
        await asyncio.sleep(0)
        return self.values.get(key)

    async def delete(self, key):
        await asyncio.sleep(0)
        self.values.pop(key, None)

    async def getdel(self, key):
        await asyncio.sleep(0)
        return self.values.pop(key, None)  # executes atomically server-side


@pytest.mark.asyncio
async def test_concurrent_ticket_consumers_have_one_winner(monkeypatch):
    """T1.8 / F-M11: racing consumers of one ticket; only one may open a socket."""
    redis = SimpleRedis()
    monkeypatch.setattr(ticket_manager, "redis_mgr", redis)
    manager = TicketManager()
    ticket = await manager.generate_ticket("operator")
    results = await asyncio.gather(*(manager.consume_ticket(ticket) for _ in range(5)))
    assert sum(r is not None for r in results) == 1
