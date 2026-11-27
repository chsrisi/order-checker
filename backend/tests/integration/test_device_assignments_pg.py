"""Per-device logout and worker switch (IMPLEMENTATION_PLAN T8.4a, V2_WORKER_SWITCH_DELTA):
HTTP, service and races, with PostgreSQL and an in-memory Redis."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from fake_redis import FakeRedis
from src import config
from src.models import AuthSession, Device, DeviceStateRequest, WSMessageType
from src.services import auth_service, device_assignment_service as service, queries
from src.services.managers import conn_mgr, device_assignment_manager

from .factories import add_user
from .test_devices_pg import keypair, sign

VERSION = {"X-Client-Version": "1"}
_counter = itertools.count()


def nonce(at: float | None = None) -> str:
    return f"{int(at if at is not None else time.time())}-n{next(_counter):012d}"


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(device_assignment_manager, "redis_mgr", fake)
    return fake


@pytest.fixture
def sockets(monkeypatch):
    """Records socket closes and admin frames instead of sending them."""
    closed = AsyncMock(return_value=1)
    frames = AsyncMock()
    monkeypatch.setattr(conn_mgr, "disconnect_session", closed)
    monkeypatch.setattr(conn_mgr, "broadcast", frames)
    return closed, frames


@pytest.fixture
def env(pg_session_factory, redis, sockets, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLIENT_RELEASES_DIR", str(tmp_path))
    key1, pub1 = keypair()
    key2, pub2 = keypair()
    keyp, pubp = keypair()
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_user(db, "eko")
        add_user(db, "boss", scope="admin")
        db.add(Device(id="dev1", public_key=pub1, status="active", model="MT67"))
        db.add(Device(id="dev2", public_key=pub2, status="active", model="MT67"))
        db.add(Device(id="devp", public_key=pubp, status="pending", model="MT67"))
        db.commit()
    tokens = auth_service.get_tokens(queries.get_user_data("boss"))

    class Env:
        pass

    e = Env()
    e.keys = {"dev1": key1, "dev2": key2, "devp": keyp}
    e.redis, e.db = redis, pg_session_factory
    e.closed, e.frames = sockets
    e.admin = {"Authorization": f"Bearer {tokens['access_token']}"}
    return e


@pytest.fixture
def client():
    from src.main import app

    return TestClient(app)


def logged_in(username: str, device_id: str) -> tuple[str, dict]:
    """A session of ``username`` bound to the device, as after a password login + register."""
    tokens = auth_service.get_tokens(queries.get_user_data(username))
    sid = auth_service.verify_access_token(tokens["access_token"])["sid"]
    assert queries.bind_session_to_device(sid, device_id, username)
    return sid, tokens


def body(e, device_id="dev1", key=None, n=None):
    n = n or nonce()
    key = key or e.keys[device_id]
    return {
        "device_id": device_id,
        "nonce": n,
        "signature": sign(key, f"oc-device:state:{device_id}:{n}"),
    }


def poll(client, e, device_id="dev1", **kw):
    e.redis.advance(3)  # past the 2 s poll limit
    return client.post("/v2/device/state", headers=VERSION, json=body(e, device_id, **kw))


def assign(client, e, username="eko", mode="direct", device_id="dev1"):
    return client.post(
        f"/admin/devices/{device_id}/assign",
        headers=e.admin,
        json={"username": username, "mode": mode},
    )


def device_row(client, e, device_id="dev1"):
    (row,) = [d for d in client.get("/admin/devices", headers=e.admin).json() if d["id"] == device_id]
    return row


def live(e, username):
    with e.db() as db:
        return list(
            db.execute(
                select(AuthSession).where(
                    AuthSession.username == username, AuthSession.revoked_at.is_(None)
                )
            ).scalars()
        )


def device_frames(e):
    return [c for c in e.frames.await_args_list if c.args[0] == WSMessageType.DEVICES]


# --- direct and preselect --------------------------------------------------------------------


def test_direct_switch_logs_the_old_worker_out_and_the_new_one_in(client, env):
    old_sid, _ = logged_in("alice", "dev1")
    response = assign(client, env)
    assert response.status_code == 200, response.text
    waiting = response.json()["assignment"]
    assert (waiting["username"], waiting["mode"], waiting["admin"]) == ("eko", "direct", "boss")
    env.closed.assert_awaited_once_with(old_sid)
    assert live(env, "alice") == []

    state = poll(client, env).json()
    assert state["logout_reason"] == {"kind": "switch", "username": "eko"}
    got = state["assignment"]
    assert (got["username"], got["mode"]) == ("eko", "direct")
    access = got["tokens"]["access_token"]
    claims = auth_service.verify_access_token(access)
    assert claims["sub"] == "eko"
    with env.db() as db:
        assert db.get(AuthSession, claims["sid"]).device_id == "dev1"
        assert db.get(Device, "dev1").current_username == "eko"
    headers = {"Authorization": f"Bearer {access}", **VERSION}
    assert client.get("/v2/items/find?query=zz", headers=headers).status_code != 401

    # Handed over once; the reason too.
    assert poll(client, env).json() == {"assignment": None, "logout_reason": None}
    row = device_row(client, env)
    assert row["assignment"] is None
    assert (row["last_assignment"]["outcome"], row["last_assignment"]["username"]) == (
        "collected",
        "eko",
    )


def test_preselect_hands_over_only_the_name_and_works_on_a_pending_device(client, env):
    response = assign(client, env, mode="preselect", device_id="devp")
    assert response.status_code == 200, response.text
    state = poll(client, env, "devp").json()
    assert state["assignment"] == {"username": "eko", "mode": "preselect", "tokens": None}
    assert state["logout_reason"] is None  # nobody was logged in
    assert live(env, "eko") == []


def test_direct_needs_an_approved_device(client, env):
    response = assign(client, env, device_id="devp")
    assert (response.status_code, response.json()["detail"]) == (409, "Device is not approved")


def test_admin_and_unknown_accounts_cannot_be_assigned(client, env):
    for name in ("boss", "nobody"):
        response = assign(client, env, username=name)
        assert (response.status_code, response.json()["detail"]) == (
            404,
            "Client account not found",
        )
    assert assign(client, env, device_id="nope").status_code == 404


def test_device_actions_need_an_admin(client, env):
    _sid, tokens = logged_in("alice", "dev2")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/admin/devices/dev1/logout", headers=headers).status_code == 403
    assert (
        client.post(
            "/admin/devices/dev1/assign", headers=headers, json={"username": "eko"}
        ).status_code
        == 403
    )
    assert client.delete("/admin/devices/dev1/assign", headers=headers).status_code == 403


# --- collected once, only by the device's key ------------------------------------------------


def test_two_polls_racing_collect_at_most_one_session(env, monkeypatch):
    monkeypatch.setattr(device_assignment_manager.DeviceAssignmentManager, "claim_poll_slot", AsyncMock(return_value=True))

    async def race():
        from src.models import AdminDeviceAssign

        await service.assign("dev1", AdminDeviceAssign(username="eko"), "boss")
        return await asyncio.gather(
            *(service.state(DeviceStateRequest(**body(env)), None) for _ in range(5))
        )

    results = asyncio.run(race())
    assert sum(r.assignment is not None for r in results) == 1
    assert len(live(env, "eko")) == 1


def test_taking_an_assignment_is_atomic(env):
    """The step two polls race on: one GETDEL, so exactly one caller gets it."""
    mgr = device_assignment_manager.device_assignment_mgr

    async def race():
        await mgr.put(device_id="dev1", username="eko", mode="direct", admin="boss", credential="c")
        return await asyncio.gather(*(mgr.take("dev1") for _ in range(5)))

    assert sum(a is not None for a in asyncio.run(race())) == 1


def test_bad_signatures_and_replays_are_refused(client, env):
    assign(client, env, mode="preselect")
    # Another device's key, for this device.
    r = poll(client, env, key=env.keys["dev2"])
    assert (r.status_code, r.json()["detail"]) == (400, "Invalid device signature")
    # A replayed nonce.
    n = nonce()
    assert poll(client, env, n=n).status_code == 200
    r = poll(client, env, n=n)
    assert (r.status_code, r.json()["detail"]) == (400, "Nonce already used")
    # Far off the server's time (a captured poll replayed later).
    r = poll(client, env, n=nonce(time.time() - 3600))
    assert (r.status_code, r.json()["detail"]) == (400, "Nonce out of time")
    # Not registered.
    r = client.post("/v2/device/state", headers=VERSION, json=body(env, "zzz", key=env.keys["dev1"]))
    assert (r.status_code, r.json()["detail"]) == (403, "Device not registered")
    # Without X-Client-Version (gated like the rest of /v2).
    assert client.post("/v2/device/state", json=body(env)).status_code == 400


def test_bad_signature_does_not_consume_the_assignment(client, env):
    assign(client, env, mode="preselect")
    assert poll(client, env, key=env.keys["dev2"]).status_code == 400
    assert poll(client, env).json()["assignment"]["username"] == "eko"


def test_polling_faster_than_every_2_s_is_429(client, env):
    assert client.post("/v2/device/state", headers=VERSION, json=body(env)).status_code == 200
    r = client.post("/v2/device/state", headers=VERSION, json=body(env))
    assert (r.status_code, r.json()["detail"]) == (429, "Polling too fast")


# --- revoked, expired, replaced, invalidated -------------------------------------------------


def test_a_revoked_device_gets_nothing(client, env):
    assign(client, env, mode="preselect")
    assert client.post("/admin/devices/dev1/revoke", headers=env.admin).status_code == 200
    r = poll(client, env)
    assert (r.status_code, r.json()["detail"]) == (403, "Device revoked")
    assert device_row(client, env)["last_assignment"]["outcome"] == "invalid"
    for call in (assign(client, env), client.post("/admin/devices/dev1/logout", headers=env.admin)):
        assert (call.status_code, call.json()["detail"]) == (409, "Device is revoked")


def test_an_assignment_expires_after_its_ttl(client, env, monkeypatch):
    assign(client, env, mode="preselect")
    env.redis.advance(device_assignment_manager.TTL_SECONDS + 1)
    assert poll(client, env).json()["assignment"] is None
    later = time.time() + device_assignment_manager.TTL_SECONDS + 1
    env.frames.reset_mock()
    with monkeypatch.context() as m:
        m.setattr(device_assignment_manager.time, "time", lambda: later)
        assert asyncio.run(service.expire_due()) == 1
        assert asyncio.run(service.expire_due()) == 0  # announced once
    assert len(device_frames(env)) == 1
    row = device_row(client, env)
    assert row["assignment"] is None and row["last_assignment"]["outcome"] == "expired"


def test_a_new_assignment_replaces_the_old_one(client, env, monkeypatch):
    assign(client, env, username="alice", mode="preselect")
    assign(client, env, username="eko", mode="direct")
    row = device_row(client, env)
    assert row["assignment"]["username"] == "eko"
    assert (row["last_assignment"]["outcome"], row["last_assignment"]["username"]) == (
        "replaced",
        "alice",
    )
    assert poll(client, env).json()["assignment"]["username"] == "eko"
    # The replaced one never expires later.
    later = time.time() + device_assignment_manager.TTL_SECONDS + 1
    monkeypatch.setattr(device_assignment_manager.time, "time", lambda: later)
    assert asyncio.run(service.expire_due()) == 0


@pytest.mark.parametrize("change", ["delete", "reset", "admin"])
def test_worker_changed_in_between_invalidates_it(client, env, change):
    assign(client, env)
    if change == "delete":
        queries.delete_user_by_username("eko", actor="boss")
    elif change == "reset":
        queries.set_password_and_revoke_sessions("eko", "new-hash")
    else:
        from src.models import User

        with env.db() as db:
            db.get(User, "eko").scope = "admin"
            db.commit()
    assert poll(client, env).json()["assignment"] is None
    assert live(env, "eko") == []
    assert device_row(client, env)["last_assignment"]["outcome"] == "invalid"


def test_the_new_workers_other_devices_stay_logged_in(client, env):
    other_sid, _ = logged_in("eko", "dev2")
    alice_elsewhere, _ = logged_in("alice", "dev2")
    logged_in("alice", "dev1")
    assign(client, env)
    assert poll(client, env).json()["assignment"]["tokens"] is not None
    live_eko = {s.id: s.device_id for s in live(env, "eko")}
    assert live_eko[other_sid] == "dev2" and sorted(live_eko.values()) == ["dev1", "dev2"]
    assert [s.id for s in live(env, "alice")] == [alice_elsewhere]


# --- logout, cancel, reachable ---------------------------------------------------------------


def test_logout_this_device(client, env):
    assign(client, env, mode="preselect", device_id="dev1")
    sid, _ = logged_in("alice", "dev1")  # someone logged in with a password meanwhile
    other, _ = logged_in("alice", "dev2")
    r = client.post("/admin/devices/dev1/logout", headers=env.admin)
    assert (r.status_code, r.json()["message"]) == (200, "1 session(s) revoked")
    assert [s.id for s in live(env, "alice")] == [other]
    env.closed.assert_any_await(sid)
    state = poll(client, env).json()
    assert state == {"assignment": None, "logout_reason": {"kind": "logout", "username": None}}
    assert device_row(client, env)["last_assignment"]["outcome"] == "cancelled"


def test_cancel_drops_the_waiting_assignment(client, env):
    assign(client, env, mode="preselect")
    r = client.delete("/admin/devices/dev1/assign", headers=env.admin)
    assert r.status_code == 200 and r.json()["assignment"] is None
    assert r.json()["last_assignment"]["outcome"] == "cancelled"
    assert client.delete("/admin/devices/dev1/assign", headers=env.admin).status_code == 200
    assert poll(client, env).json()["assignment"] is None


def test_a_poll_marks_the_device_reachable_and_touches_last_seen(client, env):
    assert device_row(client, env)["reachable"] is False
    old = datetime.now(UTC) - timedelta(seconds=30)
    with env.db() as db:
        db.get(Device, "dev1").last_seen_at = old
        db.commit()
    poll(client, env)
    row = device_row(client, env)
    assert row["reachable"] is True and row["online"] is False
    with env.db() as db:  # within 60 s of the last write: not written again (P-27)
        assert db.get(Device, "dev1").last_seen_at.replace(tzinfo=UTC) == old
        db.get(Device, "dev1").last_seen_at = old - timedelta(seconds=60)
        db.commit()
    poll(client, env)
    with env.db() as db:
        assert db.get(Device, "dev1").last_seen_at.replace(tzinfo=UTC) > old
    env.redis.advance(31)
    assert device_row(client, env)["reachable"] is False


def test_devices_update_on_create_collect_and_replace(client, env):
    env.frames.reset_mock()
    assign(client, env, mode="preselect")
    assign(client, env, mode="preselect")  # replaces
    poll(client, env)  # collects
    frames = device_frames(env)
    assert len(frames) == 3
    assert all(c.kwargs["scope"] == "admin" for c in frames)
    last = {d["id"]: d for d in frames[-1].kwargs["data"]}["dev1"]
    assert last["assignment"] is None and last["last_assignment"]["outcome"] == "collected"


# --- Redis down, logs ------------------------------------------------------------------------


def test_redis_down(client, env, pg_session_factory):
    from src.models import User

    with pg_session_factory() as db:
        db.get(User, "alice").password_hash = auth_service.get_password_hash("pw")
        db.commit()
    sid, _ = logged_in("alice", "dev1")
    env.redis.broken = True
    r = assign(client, env)
    assert (r.status_code, r.json()["detail"]) == (503, "Device assignments are unavailable")
    assert [s.id for s in live(env, "alice")] == [sid]  # nothing changed
    assert client.post("/v2/device/state", headers=VERSION, json=body(env)).status_code == 503
    assert client.delete("/admin/devices/dev1/assign", headers=env.admin).status_code == 503
    # Listing and logging a device out still work; so does a password login.
    assert device_row(client, env)["reachable"] is False
    assert client.post("/admin/devices/dev1/logout", headers=env.admin).status_code == 200
    assert live(env, "alice") == []
    login = client.post(
        "/v2/auth/login", headers=VERSION, json={"username": "alice", "password": "pw"}
    )
    assert login.status_code == 200, login.text


def test_no_token_in_a_log_line_or_a_stored_value(client, env, caplog):
    caplog.set_level(logging.DEBUG)
    logged_in("alice", "dev1")
    assign(client, env)
    tokens = poll(client, env).json()["assignment"]["tokens"]
    secrets = [tokens["access_token"], tokens["refresh_token"]]
    for record in caplog.records:
        text = record.getMessage() + json.dumps(record.__dict__, default=str)
        assert not any(s in text for s in secrets)
    stored = json.dumps(env.redis.values) + json.dumps(env.redis.zsets)
    assert not any(s in stored for s in secrets)
    events = {r.event for r in caplog.records if hasattr(r, "event")}
    assert {"device.assignment.created", "device.assignment.collected"} <= events
    created = next(r for r in caplog.records if getattr(r, "event", "") == "device.assignment.created")
    assert (created.admin, created.device_id, created.old_worker, created.new_worker) == (
        "boss",
        "dev1",
        "alice",
        "eko",
    )
