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

    async def getdel(self, key):
        return self.values.pop(key, None)

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
    await manager.set("once", "v")
    assert await manager.getdel("once") == "v"
    assert await manager.getdel("once") is None
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

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://user:pass@postgres_container:5432/dbname"
    )
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


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("redis://localhost:6379/0", "redis://redis:6379/0"),
        ("redis://127.0.0.1/0", "redis://redis/0"),
        ("redis://:secret@localhost:6379/0", "redis://:secret@redis:6379/0"),
        ("rediss://user:pw@localhost", "rediss://user:pw@redis"),
        ("redis://redis:6379/0", "redis://redis:6379/0"),
        ("redis://localhost.example.com:6379/0", "redis://localhost.example.com:6379/0"),
        ("redis://:localhost@cache:6379/0", "redis://:localhost@cache:6379/0"),
    ],
)
def test_config_redis_url_localhost_resolves_inside_docker(monkeypatch, given, expected):
    monkeypatch.setattr(config.os.path, "isfile", lambda _: False)
    monkeypatch.setattr(config.os.path, "exists", lambda path: path == "/.dockerenv")
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.setenv("REDIS_URL", given)
    assert config.get_config_value("REDIS_URL") == expected


def test_config_redis_url_custom_host_and_untouched_outside_docker(monkeypatch):
    monkeypatch.setattr(config.os.path, "isfile", lambda _: False)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(config.os.path, "exists", lambda _: False)
    assert config.get_config_value("REDIS_URL") == "redis://localhost:6379/0"
    monkeypatch.setattr(config.os.path, "exists", lambda path: path == "/run/secrets")
    monkeypatch.setenv("REDIS_HOST", "cache")
    assert config.get_config_value("REDIS_URL") == "redis://cache:6379/0"


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


def test_versioning_and_jwt_config_defaults():
    """T3.1: one version from pyproject; token identity per environment."""
    assert config.API_VERSION == config.PROJECT_VERSION == config.read_project_version()
    assert config.CLIENT_CONTRACT == 2  # /v2 since v0.6.0 (T6.3); root routes stay v1
    assert (config.CLIENT_CONTRACT_MIN, config.CLIENT_CONTRACT_MAX) == (1, 2)
    assert config.DEFAULT_JWT_AUDIENCE == f"api.bakingholic:{config.APP_ENV}"
    assert config.DEFAULT_JWT_ISSUER == f"auth.bakingholic:{config.APP_ENV}"
    assert config.JWT_ALGORITHM == "RS256"
    assert config.JWT_LEEWAY_SECONDS == 30.0
    assert config.REFRESH_TTL_SECONDS == 86400
    assert config.REFRESH_CLEANUP_INTERVAL_SECONDS == 3600


def test_project_version_reader(tmp_path):
    good = tmp_path / "pyproject.toml"
    good.write_text('[project]\nname = "x"\nversion = "9.8.7"\n')
    assert config.read_project_version(good) == "9.8.7"
    assert config.read_project_version(tmp_path / "missing.toml") == "0.0.0+unknown"


def test_pyproject_version_is_semver():
    import re

    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", config.PROJECT_VERSION)


@pytest.mark.asyncio
async def test_redis_manager_counter_with_ttl(monkeypatch):
    class Counter(FakeRedisClient):
        def __init__(self):
            super().__init__()
            self.expiries = {}

        async def incr(self, key):
            self.values[key] = int(self.values.get(key, 0)) + 1
            return self.values[key]

        async def expire(self, key, ttl):
            self.expiries[key] = ttl
            return True

    client = Counter()
    monkeypatch.setattr(redis_service, "get_config_value", lambda *_: "redis://example/0")
    monkeypatch.setattr(redis_service.redis, "from_url", lambda *_, **__: client)
    manager = RedisManager()
    assert await manager.incr_with_ttl("k", 60) == 1
    assert await manager.incr_with_ttl("k", 60) == 2
    assert client.expiries == {"k": 60}
