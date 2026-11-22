from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import HTTPException

from src.services import auth_service


def user(username="operator", scope="client", password_hash="hash"):
    return SimpleNamespace(username=username, scope=scope, password_hash=password_hash)


def test_access_token_round_trip():
    token = auth_service.create_access_token("operator", "sid-1")
    payload = auth_service.verify_access_token(token)
    assert payload["sub"] == "operator"
    assert payload["type"] == "access"
    assert payload["sid"] == "sid-1"


def test_token_without_sid_is_rejected():
    """T6.2 / Q24: tokens from before sessions existed no longer verify."""
    sig = auth_service.key_mgr.get_active_signer()
    now = datetime.now(UTC)
    legacy = jwt.encode(
        {
            "sub": "operator",
            "type": "access",
            "jti": "j",
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "nbf": now,
            "aud": auth_service.JWT_AUDIENCE,
            "iss": auth_service.JWT_ISSUER,
        },
        sig.private_key,
        algorithm=auth_service.ALGORITHM,
        headers={"kid": sig.kid},
    )
    with pytest.raises(jwt.MissingRequiredClaimError):
        auth_service.verify_access_token(legacy)


def test_current_principal_requires_a_live_session(monkeypatch):
    seen = []
    monkeypatch.setattr(
        auth_service.queries,
        "get_user_for_session",
        lambda u, sid, version=None: (
            seen.append((u, sid, version)) or (user() if sid == "live" else None)
        ),
    )
    creds = SimpleNamespace(credentials=auth_service.create_access_token("operator", "live"))
    principal = auth_service.get_current_principal(creds)
    assert principal.sid == "live" and principal.user.username == "operator"
    revoked = SimpleNamespace(credentials=auth_service.create_access_token("operator", "gone"))
    with pytest.raises(HTTPException) as exc:
        auth_service.get_current_principal(revoked)
    assert exc.value.status_code == 401
    # The gate's versionCode (request.state) is passed on to touch the device (T6.6).
    request = SimpleNamespace(state=SimpleNamespace(client_version=7))
    auth_service.get_current_principal(creds, request)
    assert seen == [("operator", "live", None), ("operator", "gone", None), ("operator", "live", 7)]


def test_refresh_token_cannot_be_used_as_access_token():
    token, _, _ = auth_service.create_refresh_token("operator", "sid")
    with pytest.raises(jwt.InvalidTokenError, match="Invalid token type"):
        auth_service.verify_access_token(token)


def test_refresh_token_round_trip():
    token, jti, expires_at = auth_service.create_refresh_token("operator", "sid")
    payload = auth_service.verify_refresh_token(token)
    assert payload["sub"] == "operator"
    assert payload["jti"] == jti
    assert expires_at > datetime.now(UTC)


def test_access_token_cannot_be_used_as_refresh_token():
    with pytest.raises(jwt.InvalidTokenError, match="Invalid token type"):
        auth_service.verify_refresh_token(auth_service.create_access_token("operator", "sid"))


def test_login_rejects_unknown_user(monkeypatch):
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _: None)
    with pytest.raises(HTTPException) as exc:
        auth_service.login_user("missing", "password")
    assert exc.value.status_code == 401


def test_admin_login_rejects_client_scope(monkeypatch):
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _: user())
    with pytest.raises(HTTPException) as exc:
        auth_service.login_user("operator", "password", required_scope="admin")
    assert exc.value.status_code == 401


def test_login_returns_tokens_for_valid_user(monkeypatch):
    expected = {"access_token": "a", "refresh_token": "r", "token_type": "bearer"}
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _: user())
    monkeypatch.setattr(auth_service, "verify_password", lambda *_: True)
    monkeypatch.setattr(auth_service, "get_tokens", lambda *_a, **_k: expected)
    assert auth_service.login_user("operator", "password") == expected


def test_refresh_rotates_persisted_token_within_its_session(monkeypatch):
    db_token = SimpleNamespace(
        username="operator",
        revoked_at=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        session_id="sid-1",
    )
    consumed: list[str] = []
    issued = []
    monkeypatch.setattr(
        auth_service, "verify_refresh_token", lambda _: {"jti": "old", "sid": "sid-1"}
    )
    monkeypatch.setattr(
        auth_service.queries,
        "consume_refresh_token",
        lambda jti: consumed.append(jti) or db_token,
    )
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _: user())
    monkeypatch.setattr(
        auth_service,
        "get_tokens",
        lambda u, sid=None, **_: issued.append(sid) or {"token_type": "bearer"},
    )
    assert auth_service.refresh_tokens("token") == {"token_type": "bearer"}
    assert consumed == ["old"]
    assert issued == ["sid-1"]  # rotation keeps the session


def test_refresh_rejects_token_of_another_session(monkeypatch):
    db_token = SimpleNamespace(
        username="operator",
        revoked_at=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        session_id="sid-1",
    )
    monkeypatch.setattr(
        auth_service, "verify_refresh_token", lambda _: {"jti": "old", "sid": "other"}
    )
    monkeypatch.setattr(auth_service.queries, "consume_refresh_token", lambda _: db_token)
    with pytest.raises(HTTPException) as exc:
        auth_service.refresh_tokens("token")
    assert exc.value.status_code == 401


def test_refresh_rejects_expired_database_record(monkeypatch):
    db_token = SimpleNamespace(
        username="operator",
        revoked_at=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    consumed: list[str] = []
    monkeypatch.setattr(auth_service, "verify_refresh_token", lambda _: {"jti": "old"})
    monkeypatch.setattr(
        auth_service.queries,
        "consume_refresh_token",
        lambda jti: consumed.append(jti) or db_token,
    )
    with pytest.raises(HTTPException) as exc:
        auth_service.refresh_tokens("token")
    assert exc.value.status_code == 401
    assert consumed == ["old"]  # the expired row is gone after the call


def test_refresh_rejects_already_used_token(monkeypatch):
    monkeypatch.setattr(auth_service, "verify_refresh_token", lambda _: {"jti": "old"})
    monkeypatch.setattr(auth_service.queries, "consume_refresh_token", lambda _: None)
    with pytest.raises(HTTPException) as exc:
        auth_service.refresh_tokens("token")
    assert exc.value.status_code == 401


def test_get_tokens_starts_a_session_at_login(monkeypatch):
    expires = datetime.now(UTC) + timedelta(hours=1)
    created = []
    monkeypatch.setattr(auth_service, "create_access_token", lambda u, sid: f"access:{sid}")
    monkeypatch.setattr(
        auth_service, "create_refresh_token", lambda u, sid: ("refresh", "jti", expires)
    )
    monkeypatch.setattr(
        auth_service.queries, "create_session", lambda **kwargs: created.append(kwargs)
    )
    result = auth_service.get_tokens(user(), ip_address="10.0.0.7", agent="x" * 400)
    assert result["token_type"] == "bearer"
    assert created[0]["jti"] == "jti"
    assert result["access_token"] == f"access:{created[0]['sid']}"
    assert created[0]["ip_address"] == "10.0.0.7"
    assert len(created[0]["agent"]) == 256


def test_get_tokens_rotation_fails_when_session_was_revoked(monkeypatch):
    expires = datetime.now(UTC) + timedelta(hours=1)
    monkeypatch.setattr(auth_service, "create_access_token", lambda u, sid: "access")
    monkeypatch.setattr(
        auth_service, "create_refresh_token", lambda u, sid: ("refresh", "jti", expires)
    )
    monkeypatch.setattr(auth_service.queries, "create_refresh_token", lambda **_: False)
    with pytest.raises(HTTPException) as exc:
        auth_service.get_tokens(user(), sid="revoked")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_register_rejects_duplicate(monkeypatch):
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _: user())
    with pytest.raises(HTTPException) as exc:
        await auth_service.register_client("operator", "password")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_register_creates_user_and_broadcasts(monkeypatch):
    new_user = user()
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _: None)
    monkeypatch.setattr(auth_service, "get_password_hash", lambda _: "hash")
    monkeypatch.setattr(auth_service.queries, "create_user", lambda **_: new_user)
    monkeypatch.setattr(auth_service, "get_tokens", lambda *_a, **_k: {"token_type": "bearer"})
    monkeypatch.setattr(auth_service.conn_mgr, "broadcast", AsyncMock())
    assert await auth_service.register_client("operator", "password") == {"token_type": "bearer"}
    auth_service.conn_mgr.broadcast.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_user_not_found(monkeypatch):
    monkeypatch.setattr(auth_service.queries, "delete_user_by_username", lambda *_: False)
    with pytest.raises(Exception) as exc:
        await auth_service.delete_user("missing")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_logout_revokes_the_session_and_closes_its_sockets(monkeypatch):
    revoked = []
    monkeypatch.setattr(
        auth_service, "verify_refresh_token", lambda _: {"jti": "jti", "sid": "sid-1"}
    )
    monkeypatch.setattr(auth_service.queries, "revoke_session", revoked.append)
    monkeypatch.setattr(auth_service.conn_mgr, "disconnect_session", AsyncMock(return_value=1))
    assert (await auth_service.logout_user("refresh"))["message"] == "Logged out successfully"
    assert revoked == ["sid-1"]
    auth_service.conn_mgr.disconnect_session.assert_awaited_once_with("sid-1")


@pytest.mark.asyncio
async def test_admin_logout_user_revokes_and_disconnects(monkeypatch):
    monkeypatch.setattr(auth_service.queries, "revoke_user_sessions", lambda u: ["a", "b"])
    monkeypatch.setattr(auth_service.conn_mgr, "disconnect_user", AsyncMock(return_value=2))
    assert await auth_service.admin_logout_user("operator") == 2
    auth_service.conn_mgr.disconnect_user.assert_awaited_once_with("operator")
    monkeypatch.setattr(auth_service.queries, "revoke_user_sessions", lambda u: None)
    with pytest.raises(Exception) as exc:
        await auth_service.admin_logout_user("ghost")
    assert exc.value.status_code == 404


def test_require_admin_success():
    admin_user = user("admin_user", scope="admin")
    res = auth_service.require_admin(admin_user)
    assert res == admin_user


def test_require_admin_forbidden():
    client_user = user("client_user", scope="client")
    with pytest.raises(HTTPException) as exc:
        auth_service.require_admin(client_user)
    assert exc.value.status_code == 403
