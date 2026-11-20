"""T5.2: admin history is paginated newest-first with X-Total-Count."""

from datetime import UTC, datetime, timedelta

from src.services import queries

from .factories import add_order


def test_order_history_pages_are_newest_first_and_disjoint(pg_session_factory):
    base = datetime.now(UTC) - timedelta(days=1)
    with pg_session_factory() as db:
        for i in range(5):
            add_order(db, f"H{i}", done=True, status="COMPLETED", done_at=base + timedelta(hours=i))
        add_order(db, "OPEN", status="PROCESSED")
        db.commit()

    first, total = queries.get_shopee_orders_history(limit=2, offset=0)
    second, _ = queries.get_shopee_orders_history(limit=2, offset=2)
    rest, _ = queries.get_shopee_orders_history(limit=2, offset=4)
    assert total == 5
    assert [o.order_sn for o in first + second + rest] == ["H4", "H3", "H2", "H1", "H0"]


def test_outbound_history_pagination(pg_session_factory):
    with pg_session_factory() as db:
        from .factories import add_user

        add_user(db, "op")
        db.commit()
    for i in range(3):
        queries.create_outbound_item(content=f"LABEL-{i}", owner_username="op", tags_in=[])
    queries.close_outbound_items(contents=[f"LABEL-{i}" for i in range(3)], admin_username="a")
    page, total = queries.get_outbound_history(limit=2)
    assert total == 3 and len(page) == 2
