"""T7.13: the console's stock change history (V2_STOCK_DELTA S8)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from src.models import StocksLog
from src.services import queries
from src.services.queries import StockChangeFilter

from .factories import add_item


def _seed(pg_session_factory):
    with pg_session_factory() as db:
        add_item(db, "SKU-A", name="Mug")
        add_item(db, "SKU-B", name="Coaster")
        db.add(StocksLog(message="legacy free-text row", timestamp=datetime.now(UTC) - timedelta(days=30)))
        db.commit()
    queries.update_or_move_stock(sku_in="SKU-A", stock_qty=10, username="eko", mode="set", location="201")
    queries.update_or_move_stock(sku_in="SKU-A", stock_qty=5, username="dina", mode="add", location="201")
    queries.update_or_move_stock(sku_in="SKU-B", stock_qty=3, username="eko", mode="set", location="203")


def test_changes_are_newest_first_with_item_names_and_a_total(pg_session_factory):
    _seed(pg_session_factory)
    page, total = queries.get_stock_changes(limit=2)
    assert total == 4
    assert [(r["sku"], r["reason"], r["before"], r["after"]) for r in page] == [
        ("SKU-B", "adjust_set", 0, 3),
        ("SKU-A", "adjust_add", 10, 15),
    ]
    assert page[1]["item_name"] == "Mug" and page[1]["actor"] == "dina"
    rest, _ = queries.get_stock_changes(limit=2, offset=2)
    assert [r["reason"] for r in rest] == ["adjust_set", None]  # the legacy row last
    assert rest[1]["message"] == "legacy free-text row" and rest[1]["sku"] is None


def test_filters_by_item_worker_reason_and_time(pg_session_factory):
    _seed(pg_session_factory)

    def skus(**kw):
        page, total = queries.get_stock_changes(limit=50, f=StockChangeFilter(**kw))
        assert total == len(page)
        return [(r["sku"], r["actor"]) for r in page]

    assert skus(sku="sku-a") == [("SKU-A", "dina"), ("SKU-A", "eko")]
    assert skus(actor="EKO") == [("SKU-B", "eko"), ("SKU-A", "eko")]
    assert skus(reasons=("adjust_add",)) == [("SKU-A", "dina")]
    assert skus(reasons=("adjust_add", "adjust_set"), sku="SKU-B") == [("SKU-B", "eko")]

    week_ago = datetime.now(UTC) - timedelta(days=7)
    assert len(skus(since=week_ago)) == 3
    assert skus(until=week_ago) == [(None, None)]


def test_time_range_is_inclusive(pg_session_factory):
    _seed(pg_session_factory)
    moment = datetime(2026, 11, 27, 7, 0, tzinfo=UTC)
    with pg_session_factory() as db:
        db.execute(update(StocksLog).where(StocksLog.actor == "dina").values(timestamp=moment))
        db.commit()
    page, _ = queries.get_stock_changes(limit=10, f=StockChangeFilter(since=moment, until=moment))
    assert [r["actor"] for r in page] == ["dina"]


def test_a_pick_names_its_order(pg_session_factory):
    from .factories import add_order, add_user

    _seed(pg_session_factory)
    with pg_session_factory() as db:
        add_user(db, "op")
        add_order(db, "261127PICK01", owner="op")
        db.commit()
    queries.pick_for_order("261127PICK01", "SKU-A", 2, "op")
    page, _ = queries.get_stock_changes(limit=1, f=StockChangeFilter(reasons=("pick",)))
    assert (page[0]["sku"], page[0]["before"], page[0]["after"], page[0]["order_sn"]) == ("SKU-A", 15, 13, "261127PICK01")
    other, _ = queries.get_stock_changes(limit=10, f=StockChangeFilter(reasons=("adjust_set",)))
    assert {r["order_sn"] for r in other} == {None}
