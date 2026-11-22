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

    def login(username="alice"):
        tokens = auth_service.get_tokens(queries.get_user_data(username))
        sid = auth_service.verify_access_token(tokens["access_token"])["sid"]
        return {"Authorization": f"Bearer {tokens['access_token']}"}, sid

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
    headers2, sid2 = operator()
    response = _register(client, headers2, key, pub, sid2)
    assert response.status_code == 403
    with pg_session_factory() as db:
        assert db.get(Device, device_id).status == "revoked"
        assert db.get(AuthSession, sid2).device_id is None


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
    assert client.get("/admin/devices", headers=headers).status_code == 403


def test_deleting_the_operator_keeps_the_device(client, operator, pg_session_factory):
    headers, sid = operator()
    key, pub = keypair()
    device_id = _register(client, headers, key, pub, sid).json()["id"]
    assert queries.delete_user_by_username("alice", actor="boss") is True
    with pg_session_factory() as db:
        assert db.get(Device, device_id).current_username is None
