"""T1.5 / F-H5: a refresh token is consumed exactly once."""

import threading
from datetime import UTC, datetime, timedelta

from src.services import queries

from .factories import add_user


def test_consume_returns_row_once(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    queries.create_refresh_token("jti-1", "alice", datetime.now(UTC) + timedelta(hours=1))
    first = queries.consume_refresh_token("jti-1")
    assert first.username == "alice"
    assert queries.consume_refresh_token("jti-1") is None


def test_concurrent_consumes_have_one_winner(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    queries.create_refresh_token("jti-race", "alice", datetime.now(UTC) + timedelta(hours=1))
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
    for jti in ("a1", "a2"):
        queries.create_refresh_token(jti, "alice", datetime.now(UTC) + timedelta(hours=1))
    assert queries.set_password_and_revoke_sessions("alice", "new-hash") is True
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
    queries.create_refresh_token("adm-1", "admin", datetime.now(UTC) + timedelta(hours=1))

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
