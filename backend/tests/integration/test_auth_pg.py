"""T1.5 / F-H5: a refresh token is consumed exactly once. T6.2: sessions and revocation."""

import threading
from datetime import UTC, datetime, timedelta

from src.models import AuthSession, RefreshToken
from src.services import auth_service, queries

from .factories import add_user

LATER = timedelta(hours=1)


def _session(username, jti, sid=None):
    sid = sid or f"sid-{jti}"
    queries.create_session(username, jti, datetime.now(UTC) + LATER, sid)
    return sid


def test_consume_returns_row_once(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    sid = _session("alice", "jti-1")
    first = queries.consume_refresh_token("jti-1")
    assert first.username == "alice"
    assert first.session_id == sid
    assert queries.consume_refresh_token("jti-1") is None


def test_concurrent_consumes_have_one_winner(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    _session("alice", "jti-race")
    barrier = threading.Barrier(6)
    results = []

    def consume():
        barrier.wait()
        results.append(queries.consume_refresh_token("jti-race"))

    threads = [threading.Thread(target=consume) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1


def test_password_reset_revokes_all_refresh_tokens(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_user(db, "boss", scope="admin")
        db.commit()
    sids = [_session("alice", jti) for jti in ("a1", "a2")]
    assert queries.set_password_and_revoke_sessions("alice", "new-hash") is True
    assert all(queries.get_user_for_session("alice", sid) is None for sid in sids)
    assert queries.get_user_data("alice").password_hash == "new-hash"
    assert queries.consume_refresh_token("a1") is None
    assert queries.consume_refresh_token("a2") is None
    assert queries.set_password_and_revoke_sessions("boss", "x") is False  # admin-side only
    assert queries.set_password_and_revoke_sessions("ghost", "x") is False


def test_set_admin_password_updates_existing_admin(pg_session_factory, monkeypatch):
    import pytest

    from scripts import set_admin_password as cmd
    from src.services.auth_service import verify_password

    with pg_session_factory() as db:
        add_user(db, "admin", scope="admin")
        db.commit()
    adm_sid = _session("admin", "adm-1")

    values = {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "admin"}
    monkeypatch.setattr(cmd, "get_config_value", lambda k, d=None: values.get(k, d))
    with pytest.raises(SystemExit):
        cmd.set_admin_password()  # placeholder refused

    values["ADMIN_PASSWORD"] = "a-new-long-admin-password"
    assert cmd.set_admin_password() == "admin"
    assert verify_password(
        "a-new-long-admin-password", queries.get_user_data("admin").password_hash
    )
    assert queries.consume_refresh_token("adm-1") is None
    assert queries.get_user_for_session("admin", adm_sid) is None


# --------------------------------------------------------------------------- sessions (T6.2)
def test_full_token_lifecycle_and_instant_revocation(pg_session_factory, monkeypatch):
    """Login → refresh keeps the sid → admin "log out everywhere" → access *and* refresh
    tokens fail on the next use (Q10: what a v1 device sees before its login screen)."""
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    alice = queries.get_user_data("alice")
    tokens = auth_service.get_tokens(alice, ip_address="10.0.0.7", agent="scanner")
    access = auth_service.verify_access_token(tokens["access_token"])
    sid = access["sid"]

    rotated = auth_service.refresh_tokens(tokens["refresh_token"])
    assert auth_service.verify_access_token(rotated["access_token"])["sid"] == sid
    creds = type("C", (), {"credentials": rotated["access_token"]})()
    assert auth_service.get_current_principal(creds).sid == sid
    with pg_session_factory() as db:
        row = db.get(AuthSession, sid)
        assert (row.ip_address, row.agent) == ("10.0.0.7", "scanner")
        assert db.query(RefreshToken).filter_by(session_id=sid).count() == 1  # old one consumed

    assert queries.revoke_user_sessions("alice") == [sid]
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        auth_service.get_current_principal(creds)
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        auth_service.refresh_tokens(rotated["refresh_token"])
    assert exc.value.status_code == 401


def test_revoking_one_session_keeps_the_others(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    keep, drop = _session("alice", "k"), _session("alice", "d")
    queries.revoke_session(drop)
    assert queries.get_user_for_session("alice", drop) is None
    assert queries.get_user_for_session("alice", keep).username == "alice"
    assert queries.consume_refresh_token("d") is None
    assert queries.create_refresh_token("d2", "alice", datetime.now(UTC) + LATER, drop) is False


def test_session_of_another_user_does_not_authenticate(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_user(db, "bob")
        db.commit()
    sid = _session("alice", "a")
    assert queries.get_user_for_session("bob", sid) is None


def test_last_seen_is_throttled(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    sid = _session("alice", "a")
    old = datetime.now(UTC) - timedelta(minutes=5)
    with pg_session_factory() as db:
        db.get(AuthSession, sid).last_seen_at = old
        db.commit()
    queries.get_user_for_session("alice", sid)
    with pg_session_factory() as db:
        first = db.get(AuthSession, sid).last_seen_at
    assert first.replace(tzinfo=UTC) > old
    queries.get_user_for_session("alice", sid)  # within 60 s: no write
    with pg_session_factory() as db:
        assert db.get(AuthSession, sid).last_seen_at == first


def test_cleanup_removes_expired_sessions_and_their_tokens(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    live = _session("alice", "live")
    queries.create_session("alice", "old", datetime.now(UTC) - timedelta(seconds=1), "expired")
    queries.delete_outdated_refresh_tokens()
    with pg_session_factory() as db:
        assert db.get(AuthSession, "expired") is None
        assert db.get(AuthSession, live) is not None
        assert db.get(RefreshToken, "old") is None


def test_deleting_a_user_deletes_its_sessions(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    sid = _session("alice", "a")
    assert queries.delete_user_by_username("alice", actor="boss") is True
    with pg_session_factory() as db:
        assert db.get(AuthSession, sid) is None
