"""T2.13 / F-M17: per-username login throttling and constant-cost unknown users."""

import pytest
from fastapi import HTTPException

from src.services import auth_service
from src.services.managers import login_throttle as throttle_module
from src.services.managers.login_throttle import LoginThrottle


class FakeRedis:
    def __init__(self, broken=False):
        self.values: dict[str, int] = {}
        self.broken = broken

    def _check(self):
        if self.broken:
            raise ConnectionError("redis down")

    async def get(self, key):
        self._check()
        v = self.values.get(key)
        return None if v is None else str(v)

    async def incr_with_ttl(self, key, ttl):
        self._check()
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key, ttl):
        self._check()

    async def delete(self, key):
        self._check()
        self.values.pop(key, None)


@pytest.fixture
def throttle(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(throttle_module, "redis_mgr", redis)
    t = LoginThrottle(max_failures=3, window=900)
    monkeypatch.setattr(auth_service, "login_throttle", t)
    return redis


def _fail(*_args, **_kwargs):
    raise HTTPException(status_code=401, detail="Incorrect username or password")


@pytest.mark.asyncio
async def test_lockout_after_threshold_and_429(monkeypatch, throttle):
    monkeypatch.setattr(auth_service, "login_user", _fail)
    for _ in range(3):
        with pytest.raises(HTTPException) as exc:
            await auth_service.login_throttled("Operator", "bad")
        assert exc.value.status_code == 401
    monkeypatch.setattr(auth_service, "login_user", lambda *a: {"access_token": "a"})
    with pytest.raises(HTTPException) as exc:
        await auth_service.login_throttled("operator", "good")  # case-insensitive key
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"] == "900"


@pytest.mark.asyncio
async def test_success_resets_counter(monkeypatch, throttle):
    monkeypatch.setattr(auth_service, "login_user", _fail)
    for _ in range(2):
        with pytest.raises(HTTPException):
            await auth_service.login_throttled("op", "bad")
    monkeypatch.setattr(auth_service, "login_user", lambda *a: {"access_token": "a"})
    assert await auth_service.login_throttled("op", "good") == {"access_token": "a"}
    assert throttle.values == {}


@pytest.mark.asyncio
async def test_redis_down_fails_open(monkeypatch, throttle):
    throttle.broken = True
    monkeypatch.setattr(auth_service, "login_user", lambda *a: {"access_token": "a"})
    assert await auth_service.login_throttled("op", "good") == {"access_token": "a"}
    monkeypatch.setattr(auth_service, "login_user", _fail)
    with pytest.raises(HTTPException) as exc:
        await auth_service.login_throttled("op", "bad")
    assert exc.value.status_code == 401


def test_unknown_user_still_runs_a_password_check(monkeypatch):
    checked = []
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _u: None)
    monkeypatch.setattr(auth_service, "verify_password", lambda p, h: checked.append(h) or False)
    monkeypatch.setattr(auth_service, "_dummy_hash", lambda: "dummy")
    with pytest.raises(HTTPException) as exc:
        auth_service.login_user("ghost", "pw")
    assert exc.value.status_code == 401
    assert checked == ["dummy"]
