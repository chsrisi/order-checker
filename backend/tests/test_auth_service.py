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
    token = auth_service.create_access_token("operator")
    payload = auth_service.verify_access_token(token)
    assert payload["sub"] == "operator"
    assert payload["type"] == "access"


def test_refresh_token_cannot_be_used_as_access_token():
    token, _, _ = auth_service.create_refresh_token("operator")
    with pytest.raises(jwt.InvalidTokenError, match="Invalid token type"):
        auth_service.verify_access_token(token)


def test_refresh_token_round_trip():
    token, jti, expires_at = auth_service.create_refresh_token("operator")
    payload = auth_service.verify_refresh_token(token)
    assert payload["sub"] == "operator"
    assert payload["jti"] == jti
    assert expires_at > datetime.now(UTC)


def test_access_token_cannot_be_used_as_refresh_token():
    with pytest.raises(jwt.InvalidTokenError, match="Invalid token type"):
        auth_service.verify_refresh_token(auth_service.create_access_token("operator"))


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
    monkeypatch.setattr(auth_service, "get_tokens", lambda _: expected)
    assert auth_service.login_user("operator", "password") == expected


def test_refresh_rotates_persisted_token(monkeypatch):
    db_token = SimpleNamespace(
        username="operator",
        revoked_at=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    deleted: list[str] = []
    monkeypatch.setattr(auth_service, "verify_refresh_token", lambda _: {"jti": "old"})
    monkeypatch.setattr(auth_service.queries, "get_refresh_token", lambda _: db_token)
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _: user())
    monkeypatch.setattr(auth_service.queries, "delete_refresh_token", deleted.append)
    monkeypatch.setattr(auth_service, "get_tokens", lambda _: {"token_type": "bearer"})
    assert auth_service.refresh_tokens("token") == {"token_type": "bearer"}
    assert deleted == ["old"]


def test_refresh_rejects_expired_database_record(monkeypatch):
    db_token = SimpleNamespace(
        username="operator",
        revoked_at=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    deleted: list[str] = []
    monkeypatch.setattr(auth_service, "verify_refresh_token", lambda _: {"jti": "old"})
    monkeypatch.setattr(auth_service.queries, "get_refresh_token", lambda _: db_token)
    monkeypatch.setattr(auth_service.queries, "delete_refresh_token", deleted.append)
    with pytest.raises(HTTPException) as exc:
        auth_service.refresh_tokens("token")
    assert exc.value.status_code == 401
    assert deleted == ["old"]


def test_get_tokens_persists_refresh_jti(monkeypatch):
    expires = datetime.now(UTC) + timedelta(hours=1)
    created = []
    monkeypatch.setattr(auth_service, "create_access_token", lambda _: "access")
    monkeypatch.setattr(auth_service, "create_refresh_token", lambda _: ("refresh", "jti", expires))
    monkeypatch.setattr(
        auth_service.queries, "create_refresh_token", lambda **kwargs: created.append(kwargs)
    )
    result = auth_service.get_tokens(user())
    assert result["token_type"] == "bearer"
    assert created[0]["jti"] == "jti"


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
    monkeypatch.setattr(auth_service, "get_tokens", lambda _: {"token_type": "bearer"})
    monkeypatch.setattr(auth_service.conn_mgr, "broadcast", AsyncMock())
    assert await auth_service.register_client("operator", "password") == {"token_type": "bearer"}
    auth_service.conn_mgr.broadcast.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_user_not_found(monkeypatch):
    monkeypatch.setattr(auth_service.queries, "delete_user_by_username", lambda _: False)
    with pytest.raises(Exception) as exc:
        await auth_service.delete_user("missing")
    assert exc.value.status_code == 404


def test_logout_deletes_refresh_record(monkeypatch):
    deleted = []
    monkeypatch.setattr(auth_service, "verify_refresh_token", lambda _: {"jti": "jti"})
    monkeypatch.setattr(auth_service.queries, "delete_refresh_token", deleted.append)
    assert auth_service.logout_user("refresh")["message"] == "Logged out successfully"
    assert deleted == ["jti"]
