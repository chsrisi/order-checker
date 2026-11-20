"""T1.6 / F-M1: period-close counts with duplicate labels."""

from src.services import queries

from .factories import add_user


def _scan(user, content):
    return queries.create_outbound_item(content, user, [])


def test_shared_label_counts_rows_and_unknown_inputs(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_user(db, "bob")
        add_user(db, "admin", scope="admin")
        db.commit()
    _scan("alice", "LABEL-1")
    _scan("bob", "LABEL-1")
    _scan("alice", "LABEL-2")

    result = queries.close_outbound_items(["LABEL-1", "LABEL-2", "MISSING"], "admin")
    assert result["outbound"] == 3
    assert result["unknown"] == 1


def test_duplicate_inputs_count_once(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    _scan("alice", "LABEL-1")
    result = queries.close_outbound_items(["LABEL-1", " LABEL-1 ", "X", "X"], "admin")
    assert result == {"outbound": 1, "unknown": 1, "orders_done": 0}
