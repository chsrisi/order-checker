"""T4.3: inventory transaction integrity on PostgreSQL (row locks, unique bins, migration).

Parametrized per stock location mode where behaviour is shared (STOCK_MODEL_DISCUSSION §8).
"""

import threading

import pytest
from sqlalchemy import select, text

from src.models import PickItemEntry, PickStockAllocation, Stock, StocksLog
from src.services import queries
from src.services.queries import pick_items as pick_queries

from .conftest import alembic_config
from .factories import add_item, add_order, add_stock, add_user

SKU = "A01_001"


@pytest.fixture(params=["multi", "single"])
def mode(request, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", request.param)
    return request.param


def _bins(factory):
    with factory() as db:
        return {
            r.location: r.stock
            for r in db.execute(select(Stock).filter(Stock.sku == SKU)).scalars()
        }


def _seed(factory, users=("op",), bins=(("A-01", 10),)):
    with factory() as db:
        for u in users:
            add_user(db, u)
        add_item(db, SKU)
        for location, qty in bins:
            add_stock(db, SKU, qty, location)
        db.commit()


def _race(n, fn):
    barrier = threading.Barrier(n)
    errors = []

    def run(i):
        barrier.wait()
        try:
            fn(i)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_concurrent_picks_never_lose_updates_or_overallocate(pg_session_factory, mode):
    users = [f"op{i}" for i in range(8)]
    _seed(pg_session_factory, users, bins=(("A-01", 5),))

    _race(8, lambda i: queries.create_pick_item_entry(SKU, 1, users[i]))

    assert _bins(pg_session_factory) == {}
    with pg_session_factory() as db:
        allocated = db.execute(select(PickStockAllocation)).scalars().all()
        assert sum(a.qty for a in allocated) == 5  # 3 picks are shortfalls, not negative stock
        assert len(db.execute(select(StocksLog).filter_by(reason="pick_shortfall")).all()) == 3


def test_concurrent_picks_by_one_user_merge_into_one_entry(pg_session_factory, mode):
    _seed(pg_session_factory, bins=(("A-01", 20),))
    with pg_session_factory() as db:
        add_order(db, "ORD-1", owner="op")
        db.commit()
    queries.create_pick_item_entry(SKU, 1, "op", order_sn="ORD-1")  # entry exists -> FOR UPDATE

    _race(6, lambda i: queries.create_pick_item_entry(SKU, 1, "op", order_sn="ORD-1"))

    with pg_session_factory() as db:
        (entry,) = db.execute(select(PickItemEntry)).scalars().all()
        assert entry.qty == 7
        assert sum(a.qty for a in entry.allocations) == 7
    assert _bins(pg_session_factory) == {"A-01": 13}


def test_restore_after_shortfall_creates_no_phantom_stock(pg_session_factory, mode):
    _seed(pg_session_factory, bins=(("A-01", 2),))
    pie = queries.create_pick_item_entry(SKU, 5, "op")
    assert queries.delete_pie(pie.id, "op")
    assert _bins(pg_session_factory) == {"A-01": 2}


def test_split_then_delete_restores_the_right_amounts(pg_session_factory, mode):
    _seed(
        pg_session_factory, bins=(("A-01", 3), ("B-02", 2)) if mode == "multi" else (("A-01", 5),)
    )
    with pg_session_factory() as db:
        add_order(db, "ORD-1", owner="op")
        db.commit()
    pie = queries.create_pick_item_entry(SKU, 7, "op")  # 5 deducted, 2 short
    assigned = queries.assign_pick_item_entry(pie.id, "ORD-1", 4, "op")
    assert sum(a.qty for a in assigned.allocations) == 4

    assert queries.delete_pie(assigned.id, "op")
    expected = {"A-01": 3, "B-02": 1} if mode == "multi" else {"A-01": 4}
    assert _bins(pg_session_factory) == expected
    assert queries.delete_pie(pie.id, "op")
    assert sum(_bins(pg_session_factory).values()) == 5


def test_multi_restore_recreates_original_bin(pg_session_factory, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", "multi")
    _seed(pg_session_factory, bins=(("A-01", 2), ("B-02", 9)))
    pie = queries.create_pick_item_entry(SKU, 2, "op")
    assert _bins(pg_session_factory) == {"B-02": 9}
    assert queries.delete_pie(pie.id, "op")
    assert _bins(pg_session_factory) == {"A-01": 2, "B-02": 9}


def test_pick_on_done_order_is_rejected_without_side_effects(pg_session_factory, mode):
    _seed(pg_session_factory)
    with pg_session_factory() as db:
        add_order(db, "ORD-DONE", owner="op", done=True)
        db.commit()
    with pytest.raises(pick_queries.OrderClosedError):
        queries.create_pick_item_entry(SKU, 1, "op", order_sn="ORD-DONE")
    assert _bins(pg_session_factory) == {"A-01": 10}


def test_unique_bin_index_rejects_duplicates(pg_session_factory):
    _seed(pg_session_factory, bins=(("A-01", 1), (None, 1)))
    from sqlalchemy.exc import IntegrityError

    for location in ("A-01", None):
        with pg_session_factory() as db, pytest.raises(IntegrityError):
            add_stock(db, SKU, 1, location)


def test_merge_all_to_single_command(pg_session_factory):
    from scripts import stock_merge_single

    _seed(pg_session_factory, bins=(("B-02", 4), ("A-01", 1), (None, 2)))
    assert stock_merge_single.main(["--confirm"]) == 0
    assert _bins(pg_session_factory) == {"A-01": 7}
    with pg_session_factory() as db:
        assert db.execute(select(StocksLog).filter_by(reason="mode_merge")).all()
    assert stock_merge_single.main([]) == 2  # refuses without --confirm


def test_cutover_clear_deletes_entries_without_restoring(pg_session_factory):
    from scripts import clear_open_pick_entries

    _seed(pg_session_factory)
    queries.create_pick_item_entry(SKU, 3, "op")
    assert clear_open_pick_entries.main([]) == 2
    assert clear_open_pick_entries.main(["--confirm"]) == 0
    with pg_session_factory() as db:
        assert db.execute(select(PickItemEntry)).all() == []
        (log,) = db.execute(select(StocksLog).filter_by(reason="cutover_clear")).scalars().all()
        assert log.ref_id == "1"
    assert _bins(pg_session_factory) == {"A-01": 7}


def test_migration_merges_duplicate_bins(pg_engine, pg_url):
    from alembic import command

    cfg = alembic_config(pg_url)
    command.downgrade(cfg, "d862d86e8707")
    try:
        with pg_engine.begin() as conn:
            conn.execute(text("TRUNCATE warehouse.stocks, warehouse.items CASCADE"))
            conn.execute(text("INSERT INTO warehouse.items (sku) VALUES ('A01_001')"))
            conn.execute(
                text(
                    "INSERT INTO warehouse.stocks (sku, stock, location) VALUES "
                    "('A01_001', 2, 'A-01'), ('A01_001', 3, 'A-01'), ('A01_001', 1, NULL), "
                    "('A01_001', 4, NULL), ('A01_001', 9, 'B-02')"
                )
            )
    finally:
        command.upgrade(cfg, "head")
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT location, stock FROM warehouse.stocks ORDER BY location NULLS LAST")
        ).all()
        merged = conn.execute(
            text("SELECT count(*) FROM warehouse.stocks_log WHERE reason = 'migration_merge'")
        ).scalar_one()
    assert [tuple(r) for r in rows] == [("A-01", 5), ("B-02", 9), (None, 5)]
    assert merged == 2
