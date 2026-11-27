"""T6.17: picks straight into an order, and unassign back to stock (V2_PICKING_SPEC §4)."""

import threading

import pytest
from sqlalchemy import func, select

from src.models import PickItemEntry, PickStockAllocation, ShopeeOrder, Stock, StocksLog, User
from src.services import queries

from .factories import add_item, add_order, add_stock, add_user

SKU = "A01_001"
ORDER = "260101ORDER1"


@pytest.fixture(params=["multi", "single"])
def mode(request, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", request.param)
    return request.param


@pytest.fixture(autouse=True)
def not_strict(monkeypatch):
    monkeypatch.setenv("STOCK_STRICT", "0")


def _seed(factory, *bins, **order):
    with factory() as db:
        add_user(db, "op")
        add_user(db, "other")
        add_item(db, SKU, name="Flour", supplier_barcode="SUP1")
        for location, qty in bins:
            add_stock(db, SKU, qty, location)
        add_order(db, ORDER, **{"owner": "op", **order})
        db.commit()


def _bins(factory):
    with factory() as db:
        return {s.location: s.stock for s in db.execute(select(Stock)).scalars()}


def _lines(factory):
    """[(qty, deducted)] of the order's entries."""
    with factory() as db:
        return [
            (e.qty, sum(a.qty for a in e.allocations))
            for e in db.execute(select(PickItemEntry).order_by(PickItemEntry.id)).scalars()
        ]


def _set_order(factory, **values):
    with factory() as db:
        order = db.get(ShopeeOrder, ORDER)
        for key, value in values.items():
            setattr(order, key, value)
        db.commit()


def _race(*fns):
    barrier, errors = threading.Barrier(len(fns)), []

    def run(fn):
        barrier.wait()
        try:
            fn()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(fn,)) for fn in fns]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    return errors


def test_pick_resolves_the_barcode_and_adds_to_one_line(pg_session_factory, mode):
    _seed(pg_session_factory, ("A-01", 10))
    assert queries.pick_for_order(ORDER, "SUP1", 2, "op") == (ORDER, SKU, 2, "Flour")
    assert queries.pick_for_order(ORDER, SKU, 3, "op").qty == 5
    assert _lines(pg_session_factory) == [(5, 5)]
    assert _bins(pg_session_factory) == {"A-01": 5}


def test_partial_unassign_undoes_the_newest_bin_first(pg_session_factory, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", "multi")
    _seed(pg_session_factory, ("A-01", 3), ("B-02", 10))
    queries.pick_for_order(ORDER, SKU, 5, "op")  # 3 from A-01, 2 from B-02
    assert queries.unassign_from_order(ORDER, SKU, 3, "op") == (ORDER, SKU, 2, "Flour")
    assert _bins(pg_session_factory) == {"A-01": 1, "B-02": 10}  # A-01 recreated
    assert _lines(pg_session_factory) == [(2, 2)]
    with pg_session_factory() as db:
        logs = db.execute(
            select(StocksLog).filter_by(reason="pick_restore").order_by(StocksLog.id)
        ).scalars()
        assert [(x.location, x.delta, x.actor) for x in logs] == [
            ("B-02", 2, "op"),
            ("A-01", 1, "op"),
        ]


def test_single_mode_returns_to_the_current_location(pg_session_factory, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", "single")
    _seed(pg_session_factory, ("A-01", 5))
    queries.pick_for_order(ORDER, SKU, 2, "op")
    queries.update_or_move_stock(SKU, 3, "op", move_to="Z-09")
    queries.unassign_from_order(ORDER, SKU, 2, "op")
    assert _bins(pg_session_factory) == {"Z-09": 5}


def test_unassign_all_removes_the_line_and_it_can_be_picked_again(pg_session_factory, mode):
    _seed(pg_session_factory, ("A-01", 4))
    queries.pick_for_order(ORDER, SKU, 4, "op")
    assert queries.unassign_from_order(ORDER, SKU, 4, "op").qty == 0
    assert _lines(pg_session_factory) == [] and _bins(pg_session_factory) == {"A-01": 4}
    with pg_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PickStockAllocation)) == 0
    assert queries.pick_for_order(ORDER, SKU, 1, "op").qty == 1


def test_mistyped_quantity_is_undone_exactly(pg_session_factory, mode):
    """P3 / Q62: 50 typed instead of 5 with 10 in stock; removing 45 must leave 5."""
    _seed(pg_session_factory, ("A-01", 10))
    queries.pick_for_order(ORDER, SKU, 50, "op")
    assert _bins(pg_session_factory) == {}
    queries.unassign_from_order(ORDER, SKU, 45, "op")
    assert _bins(pg_session_factory) == {"A-01": 5}
    assert _lines(pg_session_factory) == [(5, 5)]


def test_unassign_never_returns_more_than_was_deducted(pg_session_factory, mode):
    _seed(pg_session_factory, ("A-01", 3))
    queries.pick_for_order(ORDER, SKU, 5, "op")
    queries.unassign_from_order(ORDER, SKU, 2, "op")  # the shortfall: no stock change
    assert _bins(pg_session_factory) == {} and _lines(pg_session_factory) == [(3, 3)]
    queries.unassign_from_order(ORDER, SKU, 3, "op")
    assert _bins(pg_session_factory) == {"A-01": 3}


def test_rejections_change_nothing(pg_session_factory, mode):
    _seed(pg_session_factory, ("A-01", 10))
    queries.pick_for_order(ORDER, SKU, 2, "op")
    for call, error in [
        (lambda: queries.pick_for_order("260101NONE", SKU, 1, "op"), LookupError),
        (lambda: queries.pick_for_order(ORDER, SKU, 1, "other"), LookupError),
        (lambda: queries.pick_for_order(ORDER, "NOPE", 1, "op"), LookupError),
        (lambda: queries.unassign_from_order(ORDER, SKU, 1, "other"), LookupError),
        (lambda: queries.unassign_from_order(ORDER, "NOPE", 1, "op"), LookupError),
        (lambda: queries.unassign_from_order(ORDER, SKU, 3, "op"), queries.PickQuantityError),
    ]:
        with pytest.raises(error):
            call()
    _set_order(pg_session_factory, done=True)
    with pytest.raises(queries.OrderClosedError):
        queries.pick_for_order(ORDER, SKU, 1, "op")
    with pytest.raises(queries.OrderClosedError):  # P4: shipped goods never come back
        queries.unassign_from_order(ORDER, SKU, 1, "op")
    assert _bins(pg_session_factory) == {"A-01": 8} and _lines(pg_session_factory) == [(2, 2)]


def test_cancelled_order_accepts_unassign_only(pg_session_factory, mode):
    _seed(pg_session_factory, ("A-01", 10))
    queries.pick_for_order(ORDER, SKU, 2, "op")
    _set_order(pg_session_factory, status="CANCELLED")
    with pytest.raises(queries.OrderClosedError, match="CANCELLED"):
        queries.pick_for_order(ORDER, SKU, 1, "op")
    queries.unassign_from_order(ORDER, SKU, 2, "op")
    assert _bins(pg_session_factory) == {"A-01": 10}


def test_duplicate_rows_left_by_v1_are_merged(pg_session_factory, mode):
    _seed(pg_session_factory, ("A-01", 10))
    queries.pick_for_order(ORDER, SKU, 2, "op")
    with pg_session_factory() as db:
        dup = PickItemEntry(sku=SKU, qty=3, order_sn=ORDER, owner_user="op")
        dup.allocations.append(PickStockAllocation(sku=SKU, location="A-01", qty=3))
        db.add(dup)
        db.commit()
    queries.unassign_from_order(ORDER, SKU, 4, "op")
    assert _lines(pg_session_factory) == [(1, 1)] and _bins(pg_session_factory) == {"A-01": 12}


# ------------------------------------------------------------------------ strict stock
def test_strict_stock_is_all_or_nothing(pg_session_factory, mode, monkeypatch):
    monkeypatch.setenv("STOCK_STRICT", "1")
    bins = (("A-01", 2), ("B-02", 3)) if mode == "multi" else (("A-01", 5),)
    _seed(pg_session_factory, *bins)
    with pytest.raises(queries.InsufficientStockError, match="5 available, 6 requested"):
        queries.pick_for_order(ORDER, SKU, 6, "op")
    assert _lines(pg_session_factory) == [] and _bins(pg_session_factory) == dict(bins)
    assert queries.pick_for_order(ORDER, SKU, 5, "op").qty == 5  # bins add up
    with pytest.raises(queries.InsufficientStockError):
        queries.pick_for_order(ORDER, SKU, 1, "op")
    assert _lines(pg_session_factory) == [(5, 5)]
    with pg_session_factory() as db:
        assert not db.execute(select(StocksLog).filter_by(reason="pick_shortfall")).all()


def test_strict_stock_also_covers_v1_picks(pg_session_factory, mode, monkeypatch):
    _seed(pg_session_factory, ("A-01", 1))
    monkeypatch.setenv("STOCK_STRICT", "1")
    with pytest.raises(queries.InsufficientStockError):
        queries.create_pick_item_entry(SKU, 2, "op")
    assert _lines(pg_session_factory) == [] and _bins(pg_session_factory) == {"A-01": 1}


def test_strict_stock_race_for_the_last_unit(pg_session_factory, mode, monkeypatch):
    monkeypatch.setenv("STOCK_STRICT", "1")
    _seed(pg_session_factory, ("A-01", 1))
    with pg_session_factory() as db:
        add_order(db, "260101ORDER2", owner="other")
        db.commit()
    errors = _race(
        lambda: queries.pick_for_order(ORDER, SKU, 1, "op"),
        lambda: queries.pick_for_order("260101ORDER2", SKU, 1, "other"),
    )
    assert [type(e) for e in errors] == [queries.InsufficientStockError]
    assert _lines(pg_session_factory) == [(1, 1)] and _bins(pg_session_factory) == {}


# ----------------------------------------------------------------------------- races
def test_simultaneous_first_picks_make_one_line(pg_session_factory, mode):
    """P6: no entry exists yet, so only the order lock serializes them."""
    _seed(pg_session_factory, ("A-01", 20))
    assert _race(*[lambda: queries.pick_for_order(ORDER, SKU, 1, "op")] * 8) == []
    assert _lines(pg_session_factory) == [(8, 8)] and _bins(pg_session_factory) == {"A-01": 12}


def test_two_unassigns_of_the_last_unit(pg_session_factory, mode):
    _seed(pg_session_factory, ("A-01", 5))
    queries.pick_for_order(ORDER, SKU, 1, "op")
    errors = _race(*[lambda: queries.unassign_from_order(ORDER, SKU, 1, "op")] * 2)
    assert [type(e) for e in errors] == [LookupError]
    assert _bins(pg_session_factory) == {"A-01": 5}


def test_pick_waits_for_a_close_in_progress(pg_session_factory, mode):
    """P7: the close holds the order row; the pick must see it done."""
    _seed(pg_session_factory, ("A-01", 5))
    errors = []

    def pick():
        try:
            queries.pick_for_order(ORDER, SKU, 1, "op")
        except Exception as exc:
            errors.append(exc)

    with pg_session_factory() as db:
        db.get(ShopeeOrder, ORDER).done = True
        db.flush()  # row locked, not committed
        t = threading.Thread(target=pick)
        t.start()
        t.join(timeout=0.5)
        assert t.is_alive()  # waiting for the close
        db.commit()
    t.join(timeout=10)
    assert [type(e) for e in errors] == [queries.OrderClosedError]
    assert _bins(pg_session_factory) == {"A-01": 5} and _lines(pg_session_factory) == []


def test_worker_deletion_locks_orders_first(pg_session_factory, mode):
    """The deletion must queue behind a v2 transaction on the worker's order, holding nothing
    that transaction still needs (else they deadlock)."""
    _seed(pg_session_factory, ("A-01", 5))
    queries.pick_for_order(ORDER, SKU, 2, "op")
    with pg_session_factory() as db:
        db.execute(
            select(ShopeeOrder.order_sn)
            .where(ShopeeOrder.order_sn == ORDER)
            .with_for_update(key_share=True)
        )
        t = threading.Thread(target=lambda: queries.delete_user_by_username("op", actor="boss"))
        t.start()
        t.join(timeout=0.5)
        assert t.is_alive()
        # NOWAIT: fails at once if the deletion already holds the entry
        db.execute(select(PickItemEntry.id).with_for_update(nowait=True)).all()
        db.commit()
    t.join(timeout=10)
    assert _bins(pg_session_factory) == {"A-01": 5}
    with pg_session_factory() as db:
        assert db.get(User, "op") is None


def test_release_unassigned_picks_leaves_order_picks_alone(pg_session_factory, mode):
    _seed(pg_session_factory, ("A-01", 10))
    queries.pick_for_order(ORDER, SKU, 2, "op")
    queries.create_pick_item_entry(SKU, 3, "op")
    queries.create_pick_item_entry(SKU, 1, "other")
    assert queries.count_unassigned_picks() == 2
    assert queries.release_unassigned_picks("release") == 2
    assert queries.count_unassigned_picks() == 0
    assert _lines(pg_session_factory) == [(2, 2)] and _bins(pg_session_factory) == {"A-01": 8}
