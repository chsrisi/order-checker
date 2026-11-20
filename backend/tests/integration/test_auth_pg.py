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
