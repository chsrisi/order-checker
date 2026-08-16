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


def test_config_database_url_docker_resolves_to_backend_postgres_1(monkeypatch):
    monkeypatch.setattr(config.os.path, "isfile", lambda _: False)
    monkeypatch.setattr(config.os.path, "exists", lambda path: path == "/.dockerenv")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/dbname")
    monkeypatch.delenv("DB_HOST", raising=False)
    assert (
        config.get_config_value("DATABASE_URL")
        == "postgresql+psycopg://user:pass@backend-postgres-1:5432/dbname"
    )

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/dbname")
    assert (
        config.get_config_value("DATABASE_URL")
        == "postgresql+psycopg://user:pass@backend-postgres-1:5432/dbname"
    )

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@postgres-1:5432/dbname")
    assert (
        config.get_config_value("DATABASE_URL")
        == "postgresql+psycopg://user:pass@backend-postgres-1:5432/dbname"
    )

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@postgres_container:5432/dbname")
    assert (
        config.get_config_value("DATABASE_URL")
        == "postgresql+psycopg://user:pass@backend-postgres-1:5432/dbname"
    )



def test_config_database_url_docker_custom_db_host(monkeypatch):
    monkeypatch.setattr(config.os.path, "isfile", lambda _: False)
    monkeypatch.setattr(config.os.path, "exists", lambda path: path == "/.dockerenv")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/dbname")
    monkeypatch.setenv("DB_HOST", "custom-db")
    assert (
        config.get_config_value("DATABASE_URL")
        == "postgresql+psycopg://user:pass@custom-db:5432/dbname"
    )


def test_config_int_conversions(monkeypatch):
    monkeypatch.setattr(config.os.path, "exists", lambda _: False)
    monkeypatch.setenv("VALID_INT", "42")
    monkeypatch.setenv("INVALID_INT", "not-a-number")
    monkeypatch.delenv("MISSING_INT", raising=False)

    assert config.get_config_int("VALID_INT", 10) == 42
    assert config.get_config_int("INVALID_INT", 10) == 10
    assert config.get_config_int("MISSING_INT", 10) == 10


def test_config_float_conversions(monkeypatch):
    monkeypatch.setattr(config.os.path, "exists", lambda _: False)
    monkeypatch.setenv("VALID_FLOAT", "3.14")
    monkeypatch.setenv("INVALID_FLOAT", "abc")
    monkeypatch.delenv("MISSING_FLOAT", raising=False)

    assert config.get_config_float("VALID_FLOAT", 1.5) == 3.14
    assert config.get_config_float("INVALID_FLOAT", 1.5) == 1.5
    assert config.get_config_float("MISSING_FLOAT", 1.5) == 1.5


def test_config_bool_conversions(monkeypatch):
    monkeypatch.setattr(config.os.path, "exists", lambda _: False)
    monkeypatch.delenv("MISSING_BOOL", raising=False)
    assert config.get_config_bool("MISSING_BOOL", True) is True
    assert config.get_config_bool("MISSING_BOOL", False) is False

    for val in ["1", "true", "True", "TRUE", "yes", "YES", "on"]:
        monkeypatch.setenv("BOOL_TEST", val)
        assert config.get_config_bool("BOOL_TEST", False) is True

    for val in ["0", "false", "False", "no", "off", "anything_else"]:
        monkeypatch.setenv("BOOL_TEST", val)
        assert config.get_config_bool("BOOL_TEST", True) is False


@pytest.mark.asyncio
async def test_shopee_token_seeds_from_shopee_prefix(monkeypatch):
    redis = AsyncMock()
    redis.get.return_value = None
    monkeypatch.setattr(
        shopee_token_manager,
        "get_config_value",
        lambda key: "seeded_token" if key == "SHOPEE_ACCESS_TOKEN" else None,
    )
    manager = ShopeeTokenManager(redis)
    assert await manager.get_token("ACCESS_TOKEN") == "seeded_token"
    redis.set.assert_awaited_once_with("shopee:access_token", "seeded_token")


