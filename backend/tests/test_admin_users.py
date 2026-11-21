"""T2.5–T2.7: registration flag, admin-side account creation and password reset."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src import config
from src.dependencies import require_admin
from src.exceptions import DomainException
from src.models import AdminPasswordReset, AdminUserCreate
from src.services import auth_service


@pytest.fixture
def no_ws(monkeypatch):
    monkeypatch.setattr(auth_service.conn_mgr, "broadcast", AsyncMock())
    monkeypatch.setattr(auth_service.conn_mgr, "disconnect_user", AsyncMock(return_value=1))
    monkeypatch.setattr(auth_service, "get_password_hash", lambda p: f"hash:{p}")


@pytest.mark.asyncio
async def test_register_is_refused_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_REGISTRATION", False)
    with pytest.raises(DomainException) as exc:
        await auth_service.register_client("new_op", "pw")
    assert exc.value.status_code == 403
    assert exc.value.detail == "Registration is disabled"


@pytest.mark.asyncio
async def test_admin_create_user_is_client_scope(monkeypatch, no_ws):
    created = {}
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _u: None)

    def create_user(username, password_hash, scope):
        created.update(username=username, password_hash=password_hash, scope=scope)
        return SimpleNamespace(username=username, scope=scope)

    monkeypatch.setattr(auth_service.queries, "create_user", create_user)
    user = await auth_service.admin_create_user("op_2", "pw")
    assert user.scope == "client"
    assert created == {"username": "op_2", "password_hash": "hash:pw", "scope": "client"}
    auth_service.conn_mgr.broadcast.assert_awaited()


@pytest.mark.asyncio
async def test_admin_create_duplicate_is_409(monkeypatch, no_ws):
    monkeypatch.setattr(auth_service.queries, "get_user_data", lambda _u: object())
    with pytest.raises(DomainException) as exc:
        await auth_service.admin_create_user("op_2", "pw")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reset_password_revokes_and_closes_sessions(monkeypatch, no_ws):
    calls = []
    monkeypatch.setattr(
        auth_service.queries,
        "set_password_and_revoke_sessions",
        lambda u, h: calls.append((u, h)) or True,
    )
    await auth_service.admin_reset_password("op_2", "new")
    assert calls == [("op_2", "hash:new")]
    auth_service.conn_mgr.disconnect_user.assert_awaited_once_with("op_2")


@pytest.mark.asyncio
async def test_reset_unknown_or_admin_user_is_404(monkeypatch, no_ws):
    monkeypatch.setattr(auth_service.queries, "set_password_and_revoke_sessions", lambda *_: False)
    with pytest.raises(DomainException) as exc:
        await auth_service.admin_reset_password("ghost", "new")
    assert exc.value.status_code == 404
    auth_service.conn_mgr.disconnect_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_user_closes_sockets(monkeypatch, no_ws):
    monkeypatch.setattr(auth_service.queries, "delete_user_by_username", lambda *_: True)
    await auth_service.delete_user("op_2")
    auth_service.conn_mgr.disconnect_user.assert_awaited_once_with("op_2")


def test_admin_models_reuse_username_rule():
    with pytest.raises(ValidationError):
        AdminUserCreate(username="bad name!", password="pw")
    assert AdminUserCreate(username="op_3", password="p").password == "p"
    assert AdminPasswordReset(password="p").password == "p"  # rule is dormant


# HARDENING(password-min-length): uncomment together with the model change.
# def test_admin_password_min_length_is_enforced():
#     with pytest.raises(ValidationError):
#         AdminUserCreate(username="op_3", password="7chars_")
#     with pytest.raises(ValidationError):
#         AdminPasswordReset(password="7chars_")


def _client(scope):
    from src.main import app

    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(username="boss", scope=scope)
    return app, TestClient(app)


def test_create_route_requires_admin_and_validates(monkeypatch):
    from src.dependencies import get_current_user
    from src.main import app

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        username="op", scope="client"
    )
    try:
        client = TestClient(app)
        resp = client.post("/admin/users", json={"username": "x", "password": "y"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()

    monkeypatch.setattr(
        auth_service,
        "admin_create_user",
        AsyncMock(return_value=SimpleNamespace(username="op_9", scope="client")),
    )
    app, client = _client("admin")
    try:
        ok = client.post("/admin/users", json={"username": "op_9", "password": "a-long-password"})
        assert ok.status_code == 200
        assert ok.json() == {"username": "op_9", "scope": "client"}
        bad = client.post("/admin/users/bad%20name/password", json={"password": "a-long-password"})
        assert bad.status_code == 422
    finally:
        app.dependency_overrides.clear()
