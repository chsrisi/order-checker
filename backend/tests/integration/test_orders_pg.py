from datetime import UTC, datetime, timedelta

from src.services import queries

from .factories import add_order


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
