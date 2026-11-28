"""Login requests (V2_LOGIN_REQUEST_DELTA, T6.21/T6.22): HTTP, service and races, with PostgreSQL
and an in-memory Redis."""

from __future__ import annotations

import asyncio
import itertools
import logging
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from fake_redis import FakeRedis
from src import config
from src.exceptions import DomainException
from src.models import (
    AuthSession,
    Device,
    LoginRequestCreate,
    LoginRequestProof,
    WSMessageType,
)
from src.services import auth_service, login_request_service as service, queries
from src.services.managers import conn_mgr, login_request_manager

from .factories import add_user
from .test_devices_pg import keypair, sign

VERSION = {"X-Client-Version": "1"}
_nonces = (f"nonce-{n:016d}" for n in itertools.count())


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(login_request_manager, "redis_mgr", fake)
    return fake


@pytest.fixture
def env(pg_session_factory, redis, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLIENT_RELEASES_DIR", str(tmp_path))
    key, pub = keypair()
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_user(db, "boss", scope="admin")
        db.add(Device(id="dev1", public_key=pub, status="pending", model="MT67"))
        db.commit()
    tokens = auth_service.get_tokens(queries.get_user_data("boss"))

    class Env:
        pass

    e = Env()
    e.key, e.pub, e.redis, e.db = key, pub, redis, pg_session_factory
    e.admin = {"Authorization": f"Bearer {tokens['access_token']}"}
    return e


@pytest.fixture
def client():
    from src.main import app

    return TestClient(app)


def proof(key, action, subject, nonce=None):
    nonce = nonce or next(_nonces)
    return {"nonce": nonce, "signature": sign(key, f"oc-login-request:{action}:{subject}:{nonce}")}


def ask(client, e, username="alice", **over):
    body = {"username": username, "public_key": e.pub, **proof(e.key, "create", username), **over}
    return client.post("/v2/auth/login-requests", headers=VERSION, json=body)


def poll(client, e, rid, key=None, **kw):
    return client.post(
        f"/v2/auth/login-requests/{rid}/poll",
        headers=VERSION,
        json=proof(key or e.key, "poll", rid, **kw),
    )


def cancel(client, e, rid):
    return client.post(
        f"/v2/auth/login-requests/{rid}/cancel", headers=VERSION, json=proof(e.key, "cancel", rid)
    )


def listed(client, e):
    return client.get("/admin/login-requests", headers=e.admin).json()


def decide(client, e, rid, what="approve"):
    return client.post(f"/admin/login-requests/{rid}/{what}", headers=e.admin).status_code


def test_approved_request_yields_one_working_session_bound_to_the_device(client, env, caplog):
    caplog.set_level(logging.DEBUG)
    made = ask(client, env).json()
    assert made["expires_in"] == 120 and len(made["match_code"]) == 2
    rid = made["id"]
    assert poll(client, env, rid).json() == {"status": "pending", "tokens": None}
    (row,) = listed(client, env)
    assert (row["username"], row["match_code"], row["device_name"]) == (
        "alice",
        made["match_code"],
        "MT67",
    )
    assert decide(client, env, rid) == 200
    assert listed(client, env) == []
    got = poll(client, env, rid).json()
    assert got["status"] == "approved"
    access = got["tokens"]["access_token"]
    sid = auth_service.verify_access_token(access)["sid"]
    with env.db() as db:
        assert db.get(AuthSession, sid).device_id == "dev1"
        assert db.get(Device, "dev1").current_username == "alice"
    assert queries.get_user_for_session("alice", sid).username == "alice"
    assert poll(client, env, rid).json()["status"] == "expired"
    secret = got["tokens"]["refresh_token"]
    assert secret not in caplog.text and access not in caplog.text
    assert not any(secret in v for v in env.redis.values.values())


def test_denied_cancelled_and_replaced(client, env):
    rid = ask(client, env).json()["id"]
    assert decide(client, env, rid, "deny") == 200
    assert decide(client, env, rid) == 409
    assert poll(client, env, rid).json()["status"] == "denied"
    rid = ask(client, env).json()["id"]
    assert cancel(client, env, rid).status_code == 200
    assert cancel(client, env, rid).status_code == 200
    assert decide(client, env, rid) == 404 and listed(client, env) == []
    first, second = ask(client, env).json()["id"], ask(client, env).json()["id"]
    assert [r["id"] for r in listed(client, env)] == [second]
    assert poll(client, env, first).json()["status"] == "expired"


def test_cancel_after_approval_leaves_nothing_to_collect(client, env):
    rid = ask(client, env).json()["id"]
    decide(client, env, rid)
    cancel(client, env, rid)
    assert poll(client, env, rid).json()["status"] == "expired"


@pytest.mark.parametrize("username", ["nobody", "boss"])
def test_unknown_and_admin_names_look_normal_but_reach_nobody(client, env, username):
    made = ask(client, env, username)
    assert made.status_code == 200 and set(made.json()) == {"id", "match_code", "expires_in"}
    rid = made.json()["id"]
    assert poll(client, env, rid).json()["status"] == "pending"
    assert listed(client, env) == []
    assert decide(client, env, rid) == 404


def test_both_windows_expire(client, env):
    rid = ask(client, env).json()["id"]
    env.redis.advance(121)
    assert decide(client, env, rid) == 404
    assert poll(client, env, rid).json()["status"] == "expired"
    rid = ask(client, env).json()["id"]
    env.redis.advance(110)
    assert decide(client, env, rid) == 200
    env.redis.advance(29)  # past the first deadline, inside the collect window
    assert env.redis.values.get(f"login_req:{rid}")
    env.redis.advance(2)
    assert poll(client, env, rid).json()["status"] == "expired"


def test_signatures_nonces_and_keys(client, env):
    other, other_pub = keypair()
    assert ask(client, env, signature=sign(env.key, "something else")).status_code == 400
    unknown = client.post(
        "/v2/auth/login-requests",
        headers=VERSION,
        json={"username": "alice", "public_key": other_pub, **proof(other, "create", "alice")},
    )
    assert (unknown.status_code, unknown.json()["detail"]) == (403, "Device not registered")
    p = proof(env.key, "create", "alice")
    rid = ask(client, env, **p).json()["id"]
    assert ask(client, env, **p).status_code == 400  # replay
    decide(client, env, rid)
    assert poll(client, env, rid, key=other).status_code == 400
    # a cancel signature is no poll
    body = proof(env.key, "cancel", rid)
    url = f"/v2/auth/login-requests/{rid}/poll"
    assert client.post(url, headers=VERSION, json=body).status_code == 400
    assert poll(client, env, rid).json()["status"] == "approved"


def test_poll_nonce_is_single_use(client, env):
    rid = ask(client, env).json()["id"]
    nonce = next(_nonces)
    assert poll(client, env, rid, nonce=nonce).status_code == 200
    assert poll(client, env, rid, nonce=nonce).status_code == 400


def _revoke(env):
    with env.db() as db:
        db.get(Device, "dev1").status = "revoked"
        db.commit()


def test_revoked_device_cannot_ask(client, env):
    _revoke(env)
    r = ask(client, env)
    assert (r.status_code, r.json()["detail"]) == (403, "Device revoked")


def test_device_revoked_while_waiting_gets_no_live_session(client, env):
    rid = ask(client, env).json()["id"]
    decide(client, env, rid)
    _revoke(env)
    assert poll(client, env, rid).json() == {"status": "denied", "tokens": None}
    with env.db() as db:
        rows = db.execute(select(AuthSession).where(AuthSession.username == "alice")).scalars()
        assert all(s.revoked_at is not None for s in rows)


@pytest.mark.parametrize("change", ["delete", "reset"])
def test_worker_changed_while_waiting(client, env, change):
    rid = ask(client, env).json()["id"]
    decide(client, env, rid)
    if change == "delete":
        queries.delete_user_by_username("alice")
    else:
        queries.set_password_and_revoke_sessions("alice", "new-hash")
    assert poll(client, env, rid).json()["status"] == "expired"


def test_limits(client, env, monkeypatch):
    codes = [ask(client, env).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
    env.redis.advance(601)
    monkeypatch.setattr(login_request_manager, "MAX_PENDING", 0)
    assert ask(client, env).status_code == 429
    assert listed(client, env) == []


def test_redis_down_is_503(client, env):
    env.redis.broken = True
    assert ask(client, env).status_code == 503
    assert client.get("/admin/login-requests", headers=env.admin).status_code == 503


def test_needs_version_and_admin(client, env):
    body = {"username": "alice", "public_key": env.pub, **proof(env.key, "create", "alice")}
    assert client.post("/v2/auth/login-requests", json=body).status_code == 400
    rid = ask(client, env).json()["id"]
    tokens = auth_service.get_tokens(queries.get_user_data("alice"))
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/admin/login-requests", headers=headers).status_code == 403
    for what in ("approve", "deny"):
        url = f"/admin/login-requests/{rid}/{what}"
        assert client.post(url, headers=headers).status_code == 403


async def _ask(e):
    return (
        await service.create(
            LoginRequestCreate(
                username="alice", public_key=e.pub, **proof(e.key, "create", "alice")
            ),
            None,
        )
    ).id


def _proof(e, action, rid):
    return LoginRequestProof(**proof(e.key, action, rid))


async def _try(coro):
    try:
        await coro
        return 200
    except DomainException as exc:
        return exc.status_code


@pytest.mark.asyncio
async def test_two_admins_one_decision(env):
    rid = await _ask(env)
    codes = await asyncio.gather(
        _try(service.decide(rid, "approved", "boss")), _try(service.decide(rid, "denied", "b2"))
    )
    assert sorted(codes) == [200, 409]


@pytest.mark.asyncio
async def test_concurrent_polls_collect_once(env):
    rid = await _ask(env)
    await service.decide(rid, "approved", "boss")
    polls = await asyncio.gather(*(service.poll(rid, _proof(env, "poll", rid)) for _ in range(5)))
    assert sorted(p.status for p in polls) == ["approved"] + ["expired"] * 4
    with env.db() as db:
        sessions = db.execute(select(AuthSession).where(AuthSession.username == "alice"))
        assert len(sessions.scalars().all()) == 1


@pytest.mark.asyncio
async def test_cancel_racing_approval_gives_at_most_one_session(env):
    rid = await _ask(env)
    await asyncio.gather(
        _try(service.decide(rid, "approved", "boss")), service.cancel(rid, _proof(env, "cancel", rid))
    )
    assert (await service.poll(rid, _proof(env, "poll", rid))).status == "expired"


@pytest.mark.asyncio
async def test_only_admin_sockets_hear_of_requests(env):
    admin, operator = AsyncMock(), AsyncMock()
    await conn_mgr.connect(admin, "boss", "admin")
    await conn_mgr.connect(operator, "alice", "client")
    try:
        rid = await _ask(env)
        frame = admin.send_json.await_args.args[0]
        assert frame["type"] == WSMessageType.LOGIN_REQUESTS.value
        assert [r["id"] for r in frame["data"]] == [rid]
        await service.decide(rid, "denied", "boss")
        assert admin.send_json.await_args.args[0]["data"] == []
        operator.send_json.assert_not_awaited()
    finally:
        conn_mgr.disconnect(admin, "boss")
        conn_mgr.disconnect(operator, "alice")
