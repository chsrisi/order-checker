"""T1.6 / F-M1: period-close counts with duplicate labels."""

from src.services import queries

from .factories import add_order, add_user


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


def test_close_matches_labels_exactly(pg_session_factory):
    """V2_ORDERS_DELTA Q57 (replaces Q44): trimmed, then exact, for scans as well as for the
    orders a close completes (by SN or tracking number)."""
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_order(db, "260101ABCD")
        add_order(db, "260101TRCK", tracking="SPXID0123")
        db.commit()
    _scan("alice", "260101abcd")
    _scan("alice", "SPXID0123")

    result = queries.close_outbound_items(["260101abcd", " SPXID0123 ", "spxid0123"], "admin")
    assert result == {"outbound": 2, "unknown": 1, "orders_done": 1}
