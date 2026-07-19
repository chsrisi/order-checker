from unittest.mock import AsyncMock

import pytest

from src import config
from src.services import redis_service
from src.services.managers import shopee_token_manager
from src.services.managers.shopee_token_manager import ShopeeTokenManager
from src.services.redis_service import RedisManager


class FakeRedisClient:
    def __init__(self):
        self.values = {}
        self.closed = False

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    async def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_redis_manager_lazy_lifecycle(monkeypatch):
    client = FakeRedisClient()
    monkeypatch.setattr(redis_service, "get_config_value", lambda *_: "redis://example/0")
    monkeypatch.setattr(redis_service.redis, "from_url", lambda *_, **__: client)
    manager = RedisManager()
    assert await manager.set("key", "value", ex=10)
    assert await manager.get("key") == "value"
    assert await manager.delete("key") == 1
    await manager.close()
    assert client.closed


def test_redis_manager_requires_url(monkeypatch):
    monkeypatch.setattr(redis_service, "get_config_value", lambda *_: None)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValueError, match="REDIS_URL"):
        RedisManager().initialize()


@pytest.mark.asyncio
async def test_shopee_token_reads_redis_value():
    redis = AsyncMock()
    redis.get.return_value = "stored"
    manager = ShopeeTokenManager(redis)
    assert await manager.get_token("ACCESS_TOKEN") == "stored"
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_shopee_token_seeds_configuration_fallback(monkeypatch):
    redis = AsyncMock()
    redis.get.return_value = None
    monkeypatch.setattr(shopee_token_manager, "get_config_value", lambda _: "fallback")
    manager = ShopeeTokenManager(redis)
    assert await manager.get_token("REFRESH_TOKEN") == "fallback"
    redis.set.assert_awaited_once_with("shopee:refresh_token", "fallback")


@pytest.mark.asyncio
async def test_shopee_token_returns_none_without_fallback(monkeypatch):
    redis = AsyncMock()
    redis.get.return_value = None
    monkeypatch.setattr(shopee_token_manager, "get_config_value", lambda _: None)
    assert await ShopeeTokenManager(redis).get_token("ACCESS_TOKEN") is None


def test_config_reads_environment(monkeypatch):
    monkeypatch.setattr(config.os.path, "exists", lambda _: False)
    monkeypatch.setenv("EXAMPLE_SETTING", "value")
    assert config.get_config_value("EXAMPLE_SETTING") == "value"


def test_config_uses_default(monkeypatch):
    monkeypatch.setattr(config.os.path, "exists", lambda _: False)
    monkeypatch.delenv("MISSING_SETTING", raising=False)
    assert config.get_config_value("MISSING_SETTING", "default") == "default"
