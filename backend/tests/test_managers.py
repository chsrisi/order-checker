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
    ticket = await TicketManager().generate_ticket("operator", ttl_seconds=10)
    assert redis.values[f"ws_token:{ticket}"] == "operator"
    assert ticket not in caplog.text


@pytest.mark.asyncio
async def test_ticket_is_consumed_once(monkeypatch):
    redis = SimpleRedis()
    monkeypatch.setattr(ticket_manager, "redis_mgr", redis)
    manager = TicketManager()
    ticket = await manager.generate_ticket("operator")
    assert await manager.consume_ticket(ticket) == "operator"
    assert await manager.consume_ticket(ticket) is None


@pytest.mark.asyncio
async def test_ticket_generation_fails_closed(monkeypatch):
    broken = AsyncMock()
    broken.set.side_effect = ConnectionError("offline")
    monkeypatch.setattr(ticket_manager, "redis_mgr", broken)
    with pytest.raises(RuntimeError, match="Unable to create"):
        await TicketManager().generate_ticket("operator")


class SimpleRedis:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)
