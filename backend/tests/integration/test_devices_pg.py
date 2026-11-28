"""v2 device registration against PostgreSQL (IMPLEMENTATION_PLAN T6.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src import config
from src.models import AuthSession, Device
from src.services import auth_service, queries

from .factories import add_user


def keypair():
    """A P-256 key pair as the Android Keystore would make it (synthetic)."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return key, base64.b64encode(spki).decode()


def sign(key, sid: str) -> str:
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    return base64.b64encode(key.sign(sid.encode(), ec.ECDSA(hashes.SHA256()))).decode()


@pytest.fixture
def operator(pg_session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLIENT_RELEASES_DIR", str(tmp_path))  # no release published
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_user(db, "boss", scope="admin")
        db.commit()

    def login(username="alice", with_refresh=False):
        tokens = auth_service.get_tokens(queries.get_user_data(username))
        sid = auth_service.verify_access_token(tokens["access_token"])["sid"]
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        if with_refresh:
            return headers, sid, tokens["refresh_token"]
        return headers, sid

    return login


@pytest.fixture
def client():
    from src.main import app

    return TestClient(app)


def _register(client, headers, key, pub, sid, version=1):
    return client.post(
        "/v2/device/register",
        headers=headers,
        json={
            "public_key": pub,
            "model": "MT67",
            "android_version": "11",
            "app_version_code": version,
            "signature": sign(key, sid),
        },
    )


def test_first_registration_is_pending_and_binds_the_session(client, operator, pg_session_factory):
    headers, sid = operator()
    key, pub = keypair()
    response = _register(client, headers, key, pub, sid)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["current_username"] == "alice"
    assert (body["model"], body["android_version"], body["app_version_code"]) == ("MT67", "11", 1)
    with pg_session_factory() as db:
        assert db.get(AuthSession, sid).device_id == body["id"]


def test_reregistration_is_idempotent(client, operator, pg_session_factory):
    key, pub = keypair()
    headers, sid = operator()
    first = _register(client, headers, key, pub, sid).json()
    headers2, sid2 = operator()  # next login on the same scanner
    second = _register(client, headers2, key, pub, sid2, version=2).json()
    assert second["id"] == first["id"]
    assert second["app_version_code"] == 2
    with pg_session_factory() as db:
        assert db.query(Device).count() == 1
        assert db.get(AuthSession, sid2).device_id == first["id"]


def test_signature_for_another_session_is_400(client, operator):
    headers, _sid = operator()
    key, pub = keypair()
    response = _register(client, headers, key, pub, "some-other-sid")
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid device signature"}


def test_a_revoked_device_stays_revoked(client, operator, pg_session_factory):
    headers, sid = operator()
    key, pub = keypair()
    device_id = _register(client, headers, key, pub, sid).json()["id"]
    with pg_session_factory() as db:
        db.get(Device, device_id).status = "revoked"
        db.commit()
    headers2, sid2, refresh2 = operator(with_refresh=True)  # a password login on it
    response = _register(client, headers2, key, pub, sid2)
    assert response.status_code == 403
    with pg_session_factory() as db:
        assert db.get(Device, device_id).status == "revoked"
        assert db.get(AuthSession, sid2).device_id is None
        # W9 (T8.1): the session of that password login ends with the refused registration.
        assert db.get(AuthSession, sid2).revoked_at is not None
    assert client.get("/v2/items/find?query=zz", headers={**headers2, **V2}).status_code == 401
    assert _refresh(client, refresh2).status_code == 401


V2 = {"X-Client-Version": "1"}


def _refresh(client, refresh_token):
    return client.post("/v2/auth/refresh", headers=V2, json={"refresh_token": refresh_token})


def test_registration_needs_a_valid_token(client, operator):
    key, pub = keypair()
    assert _register(client, {}, key, pub, "x").status_code in (401, 403)


def test_gated_requests_report_the_app_version(client, operator, pg_session_factory):
    headers, sid = operator()
    key, pub = keypair()
    device_id = _register(client, headers, key, pub, sid).json()["id"]
    # After an OTA update the app sends its new versionCode: recorded at once.
    response = client.get("/v2/items/find?query=zz", headers={**headers, "X-Client-Version": "7"})
    assert response.status_code in (200, 404)
    with pg_session_factory() as db:
        assert db.get(Device, device_id).app_version_code == 7

    # Same version within the throttle window: no write.
    old = datetime.now(UTC) - timedelta(seconds=5)
    with pg_session_factory() as db:
        db.get(Device, device_id).last_seen_at = old
        db.commit()
    client.get("/v2/items/find?query=zz", headers={**headers, "X-Client-Version": "7"})
    with pg_session_factory() as db:
        assert db.get(Device, device_id).last_seen_at.replace(tzinfo=UTC) == old


def test_v1_requests_do_not_touch_the_device(client, operator, pg_session_factory):
    headers, sid = operator()
    key, pub = keypair()
    device_id = _register(client, headers, key, pub, sid, version=3).json()["id"]
    client.get("/items/find?query=zz", headers={**headers, "X-Client-Version": "9"})
    with pg_session_factory() as db:
        assert db.get(Device, device_id).app_version_code == 3


def test_admin_lists_devices(client, operator):
    headers, sid = operator()
    key, pub = keypair()
    _register(client, headers, key, pub, sid)
    admin_headers, _ = operator("boss")
    listing = client.get("/admin/devices", headers=admin_headers)
    assert listing.status_code == 200
    (device,) = listing.json()
    assert device["status"] == "pending" and device["current_username"] == "alice"
    assert "public_key" not in device and "token_hash" not in device
    assert device["online"] is False  # no open socket
    assert client.get("/admin/devices", headers=headers).status_code == 403


def test_admin_device_listing_marks_devices_with_a_live_socket_online(
    client, operator, monkeypatch
):
    """V2_DELTA Q35: online = a live session of the device has an open socket."""
    from src.services.managers import conn_mgr

    headers, sid = operator()
    key, pub = keypair()
    device_id = _register(client, headers, key, pub, sid).json()["id"]
    admin_headers, _ = operator("boss")
    monkeypatch.setattr(conn_mgr, "socket_sessions", {object(): sid})
    (device,) = client.get("/admin/devices", headers=admin_headers).json()
    assert device["id"] == device_id and device["online"] is True
    # A revoked session no longer counts, even if its socket were still in the registry.
    queries.revoke_session(sid)
    (device,) = client.get("/admin/devices", headers=admin_headers).json()
    assert device["online"] is False


def test_deleting_the_operator_keeps_the_device(client, operator, pg_session_factory):
    headers, sid = operator()
    key, pub = keypair()
    device_id = _register(client, headers, key, pub, sid).json()["id"]
    assert queries.delete_user_by_username("alice", actor="boss") is True
    with pg_session_factory() as db:
        assert db.get(Device, device_id).current_username is None


# --- T8.1: approve and revoke ------------------------------------------------------------


def _device(client, operator, username="alice"):
    """A registered device with one live session of ``username`` on it."""
    headers, sid, refresh = operator(username, with_refresh=True)
    key, pub = keypair()
    device_id = _register(client, headers, key, pub, sid).json()["id"]
    return device_id, headers, sid, refresh, key, pub


def _act(client, operator, device_id, action):
    admin_headers, _ = operator("boss")
    return client.post(f"/admin/devices/{device_id}/{action}", headers=admin_headers)


@pytest.mark.parametrize(
    "start, action, code, end",
    [
        ("pending", "approve", 200, "active"),
        ("active", "approve", 200, "active"),  # idempotent
        ("revoked", "approve", 409, "revoked"),  # final (W7)
        ("pending", "revoke", 200, "revoked"),
        ("active", "revoke", 200, "revoked"),
        ("revoked", "revoke", 200, "revoked"),  # idempotent
    ],
)
def test_device_status_transitions(client, operator, pg_session_factory, start, action, code, end):
    device_id, *_ = _device(client, operator)
    with pg_session_factory() as db:
        db.get(Device, device_id).status = start
        db.commit()
    response = _act(client, operator, device_id, action)
    assert response.status_code == code, response.text
    if code == 200:
        assert response.json()["status"] == end and response.json()["id"] == device_id
    else:
        assert response.json() == {"detail": f"Device is {start}"}
    with pg_session_factory() as db:
        assert db.get(Device, device_id).status == end


def test_device_actions_need_an_admin_and_a_known_device(client, operator):
    device_id, headers, *_ = _device(client, operator)
    assert client.post(f"/admin/devices/{device_id}/approve", headers=headers).status_code == 403
    assert _act(client, operator, "nope", "approve").status_code == 404
    assert _act(client, operator, "nope", "revoke").status_code == 404


def test_approving_keeps_the_session(client, operator, pg_session_factory):
    device_id, headers, sid, *_ = _device(client, operator)
    assert _act(client, operator, device_id, "approve").status_code == 200
    with pg_session_factory() as db:
        assert db.get(AuthSession, sid).revoked_at is None


def test_revoking_ends_the_sessions_on_that_device_only(
    client, operator, pg_session_factory, monkeypatch
):
    from unittest.mock import AsyncMock

    from src.services.managers import conn_mgr

    closed = AsyncMock(return_value=1)
    monkeypatch.setattr(conn_mgr, "disconnect_session", closed)
    device_a, headers_a, sid_a, refresh_a, *_ = _device(client, operator)
    _device_b, headers_b, sid_b, refresh_b, *_ = _device(client, operator)  # alice, 2nd scanner
    v1_headers, sid_v1, refresh_v1 = operator(with_refresh=True)  # v1 session: no device

    response = _act(client, operator, device_a, "revoke")
    assert response.status_code == 200
    closed.assert_awaited_once_with(sid_a)
    with pg_session_factory() as db:
        assert db.get(AuthSession, sid_a).revoked_at is not None
        assert db.get(AuthSession, sid_b).revoked_at is None
        assert db.get(AuthSession, sid_v1).revoked_at is None
    assert _refresh(client, refresh_a).status_code == 401
    assert _refresh(client, refresh_b).status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": refresh_v1}).status_code == 200
    assert client.get("/v2/items/find?query=zz", headers={**headers_a, **V2}).status_code == 401
    assert client.get("/v2/items/find?query=zz", headers={**headers_b, **V2}).status_code != 401


def test_a_device_revoked_by_the_admin_cannot_log_in_again(client, operator, pg_session_factory):
    device_id, _headers, _sid, _refresh, key, pub = _device(client, operator)
    assert _act(client, operator, device_id, "revoke").status_code == 200
    headers2, sid2 = operator()  # password login on the revoked scanner
    assert _register(client, headers2, key, pub, sid2).status_code == 403
    with pg_session_factory() as db:
        assert db.get(AuthSession, sid2).revoked_at is not None


def test_a_device_revoked_by_the_admin_cannot_ask_for_a_login(
    client, operator, monkeypatch
):
    from fake_redis import FakeRedis
    from src.services.managers import login_request_manager

    monkeypatch.setattr(login_request_manager, "redis_mgr", FakeRedis())
    device_id, _headers, _sid, _refresh, key, pub = _device(client, operator)
    assert _act(client, operator, device_id, "revoke").status_code == 200
    nonce = "nonce-revoked-0001"
    response = client.post(
        "/v2/auth/login-requests",
        headers=V2,
        json={
            "username": "alice",
            "public_key": pub,
            "nonce": nonce,
            "signature": sign(key, f"oc-login-request:create:alice:{nonce}"),
        },
    )
    assert (response.status_code, response.json()["detail"]) == (403, "Device revoked")


def test_device_actions_are_logged_with_admin_device_and_worker(client, operator, caplog):
    import logging

    device_id, *_ = _device(client, operator)
    with caplog.at_level(logging.INFO, logger="backend.services.device_service"):
        _act(client, operator, device_id, "approve")
        _act(client, operator, device_id, "revoke")
    events = {r.event: r for r in caplog.records if hasattr(r, "event")}
    for name in ("device.approved", "device.revoked"):
        record = events[name]
        assert (record.admin, record.device_id, record.username) == ("boss", device_id, "alice")
    assert events["device.revoked"].sessions_revoked == 1
