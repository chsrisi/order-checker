from datetime import UTC, datetime, timedelta

from src.services import queries

from .factories import add_order, add_user


def test_active_orders_exclude_orders_past_ship_by(pg_session_factory):
    """T1.1 / F-C1: the cutoff is evaluated per query, not frozen at import time."""
    now = datetime.now(UTC)
    with pg_session_factory() as db:
        add_order(db, "260101PAST", ship_by=now - timedelta(minutes=1))
        add_order(db, "260101FUTURE", ship_by=now + timedelta(hours=1))
        add_order(db, "260101DONE", ship_by=now + timedelta(hours=1), done=True)
        db.commit()

    sns = {o.order_sn for o in queries.get_all_shopee_order_data()}
    assert sns == {"260101FUTURE"}


def _owner(factory, order_sn):
    from src.models import ShopeeOrder

    with factory() as db:
        return db.get(ShopeeOrder, order_sn).owner_user


def test_claim_unowned_and_reclaim_own_order(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_order(db, "260101CLAIM")
        db.commit()
    assert queries.acquire_order("260101CLAIM", "alice") is True
    assert queries.acquire_order("260101CLAIM", "alice") is True  # idempotent for owner
    assert _owner(pg_session_factory, "260101CLAIM") == "alice"


def test_claim_missing_order_returns_false(pg_session_factory):
    assert queries.acquire_order("NOPE", "alice") is False


def test_claim_owned_or_done_order_is_rejected(pg_session_factory):
    import pytest

    with pg_session_factory() as db:
        add_user(db, "alice")
        add_user(db, "bob")
        add_order(db, "260101OWNED", owner="bob")
        add_order(db, "260101DONE", done=True)
        db.commit()
    with pytest.raises(ValueError, match="another operator"):
        queries.acquire_order("260101OWNED", "alice")
    with pytest.raises(ValueError, match="already completed"):
        queries.acquire_order("260101DONE", "alice")
    assert _owner(pg_session_factory, "260101OWNED") == "bob"
    assert _owner(pg_session_factory, "260101DONE") is None


def test_concurrent_claims_have_exactly_one_winner(pg_session_factory):
    """Two sessions race: the conditional UPDATE serialises on the row lock."""
    import threading

    with pg_session_factory() as db:
        for i in range(8):
            add_user(db, f"op{i}")
        add_order(db, "260101RACE")
        db.commit()

    barrier = threading.Barrier(8)
    results: dict[str, object] = {}

    def claim(user):
        barrier.wait()
        try:
            results[user] = queries.acquire_order("260101RACE", user)
        except ValueError as exc:
            results[user] = exc

    threads = [threading.Thread(target=claim, args=(f"op{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [u for u, r in results.items() if r is True]
    assert len(winners) == 1
    assert _owner(pg_session_factory, "260101RACE") == winners[0]
    assert all(isinstance(r, ValueError) for u, r in results.items() if u not in winners)
