"""T9.1: tasks on the stock and pick engine (V2_TASKS_SPEC §11 tests, both location modes)."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models import (
    BOMDetail,
    BOMHeader,
    PickItemEntry,
    PickStockAllocation,
    Stock,
    StocksLog,
    Task,
)
from src.services import queries
from src.services.queries import tasks
from src.services.queries.pick_items import PickQuantityError

from .factories import add_item, add_order, add_stock, add_user

FLOUR, SUGAR, BUNDLE = "A01_001", "A01_002", "B01_001"


@pytest.fixture(params=["multi", "single"])
def mode(request, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", request.param)
    return request.param


@pytest.fixture(autouse=True)
def not_strict(monkeypatch):
    monkeypatch.setenv("STOCK_STRICT", "0")


@pytest.fixture
def db(pg_session_factory):
    """Workers, items, a bundle (2 flour + 1 sugar) and stock in one bin each."""
    with pg_session_factory() as s:
        add_user(s, "eko")
        add_user(s, "ani")
        add_user(s, "boss", scope="admin")
        add_item(s, FLOUR, name="Flour", supplier_barcode="SUPFLOUR")
        add_item(s, SUGAR, name="Sugar")
        add_item(s, BUNDLE, name="Cake kit")
        add_stock(s, FLOUR, 20, "A1")
        add_stock(s, SUGAR, 10, "A2")
        header = BOMHeader(sku=BUNDLE, quantity_standard=1)
        s.add(header)
        s.flush()
        s.add(BOMDetail(bom_header_id=header.id, component_sku=FLOUR, quantity_standard=2))
        s.add(BOMDetail(bom_header_id=header.id, component_sku=SUGAR, quantity_standard=1))
        s.commit()
    return pg_session_factory


def _bins(factory, sku):
    with factory() as s:
        return {
            r.location: r.stock for r in s.execute(select(Stock).where(Stock.sku == sku)).scalars()
        }


def _log(factory, **filters):
    with factory() as s:
        query = select(StocksLog).order_by(StocksLog.id)
        for column, value in filters.items():
            query = query.where(getattr(StocksLog, column) == value)
        return list(s.execute(query).scalars())


def _task(factory, task_id):
    with factory() as s:
        return s.get(Task, task_id)


def _task_entries(factory):
    with factory() as s:
        return list(
            s.execute(
                select(PickItemEntry)
                .where(PickItemEntry.task_line_id.is_not(None))
                .order_by(PickItemEntry.sku)
            ).scalars()
        )


def _count_task(mode):
    location = "A1" if mode == "multi" else None
    return tasks.create_count_task(FLOUR, "eko", "boss", location=location)


def _pick_task(lines=((BUNDLE, 2), (FLOUR, 1))):
    return tasks.create_pick_task(lines, "eko", "boss", reference="Toko Sinar, invoice 123")


# ------------------------------------------------------------------------------ count
def test_count_sets_the_stock_logs_it_on_the_task_and_completes_it(db, mode):
    task = _count_task(mode)

    done = tasks.count_task(task.id, "eko", "SUPFLOUR", 17, location_scan="A1")

    assert done.status == "done" and done.closed_by == "eko"
    assert done.lines[0].counted_qty == 17
    assert _bins(db, FLOUR) == {"A1": 17}
    (row,) = _log(db, ref_type="task", ref_id=str(task.id))
    assert (row.reason, row.before, row.after, row.actor) == ("adjust_set", 20, 17, "eko")


def test_count_in_multi_mode_sets_only_the_tasks_bin(db, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", "multi")
    with db() as s:
        add_stock(s, FLOUR, 5, "B9")
        s.commit()
    task = tasks.create_count_task(FLOUR, "eko", "boss", location="B9")

    tasks.count_task(task.id, "eko", FLOUR, 3, location_scan="B9")

    assert _bins(db, FLOUR) == {"A1": 20, "B9": 3}


def test_count_matches_the_location_after_trim_and_upper_case_only(db, mode):
    with db() as s:
        add_item(s, "C01_001", name="Butter")
        add_stock(s, "C01_001", 4, "Rak-2b")
        s.commit()
    location = "Rak-2b" if mode == "multi" else None
    task = tasks.create_count_task("C01_001", "eko", "boss", location=location)

    with pytest.raises(tasks.TaskScanError):
        tasks.count_task(task.id, "eko", "C01_001", 1, location_scan="Rak-2")
    done = tasks.count_task(task.id, "eko", "C01_001", 1, location_scan="  rak-2B ")

    assert done.status == "done"
    assert _bins(db, "C01_001") == {"Rak-2b": 1}  # the stored name is kept


def test_count_in_single_mode_never_moves_stock_to_a_scanned_location(db, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", "single")
    task = tasks.create_count_task(FLOUR, "eko", "boss")
    assert task.lines[0].location is None

    with pytest.raises(tasks.TaskScanError):
        tasks.count_task(task.id, "eko", FLOUR, 4, location_scan="Z9")
    assert _bins(db, FLOUR) == {"A1": 20}

    tasks.count_task(task.id, "eko", FLOUR, 4)  # no scan: still the current location
    assert _bins(db, FLOUR) == {"A1": 4}
    assert [r.reason for r in _log(db, sku=FLOUR)] == ["adjust_set"]


def test_count_creation_follows_the_location_mode(db, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", "single")
    with pytest.raises(ValueError):
        tasks.create_count_task(FLOUR, "eko", "boss", location="A1")
    monkeypatch.setenv("STOCK_LOCATION_MODE", "multi")
    with pytest.raises(ValueError):
        tasks.create_count_task(FLOUR, "eko", "boss")


def test_count_refuses_a_wrong_item_or_bin_and_changes_nothing(db, mode):
    task = _count_task(mode)

    with pytest.raises(tasks.TaskScanError):
        tasks.count_task(task.id, "eko", SUGAR, 1, location_scan="A1")
    if mode == "multi":
        with pytest.raises(tasks.TaskScanError):
            tasks.count_task(task.id, "eko", FLOUR, 1, location_scan="A2")
        with pytest.raises(tasks.TaskScanError):
            tasks.count_task(task.id, "eko", FLOUR, 1)  # the bin scan is required

    assert _task(db, task.id).status == "open"
    assert _bins(db, FLOUR) == {"A1": 20}
    assert _log(db) == []


def test_only_the_assigned_worker_works_a_task(db, mode):
    count = _count_task(mode)
    pick = _pick_task()

    with pytest.raises(LookupError):
        tasks.count_task(count.id, "ani", FLOUR, 1, location_scan="A1")
    with pytest.raises(LookupError):
        tasks.pick_for_task(pick.id, "ani", FLOUR, 1)
    with pytest.raises(LookupError):
        tasks.block_task(pick.id, "ani", "not mine")
    with pytest.raises(LookupError):  # admins are not workers
        tasks.create_count_task(FLOUR, "boss", "boss", location="A1" if mode == "multi" else None)


# ------------------------------------------------------------------------------- pick
def test_pick_task_stores_the_bom_leaves_at_creation(db, mode):
    task = _pick_task()

    entered = [(line.sku, line.qty) for line in task.lines if line.kind == "entered"]
    leaves = {line.sku: line.qty for line in task.lines if line.kind == "leaf"}
    assert entered == [(BUNDLE, 2), (FLOUR, 1)]
    assert leaves == {FLOUR: 5, SUGAR: 2}

    with db() as s:  # a BOM edit after creation changes nothing
        s.execute(select(BOMDetail)).scalars().first().quantity_standard = 9
        s.commit()
    again = _task(db, task.id)
    assert {line.sku: line.qty for line in again.lines if line.kind == "leaf"} == leaves


def test_pick_task_is_done_when_every_leaf_is_picked_exactly(db, mode):
    task = _pick_task()

    first = tasks.pick_for_task(task.id, "eko", "SUPFLOUR", 5)
    assert (first.sku, first.qty, first.required, first.status) == (FLOUR, 5, 5, "open")
    assert tasks.pick_for_task(task.id, "eko", SUGAR, 1).status == "open"
    last = tasks.pick_for_task(task.id, "eko", SUGAR, 1)

    assert last.status == "done"
    assert _bins(db, FLOUR) == {"A1": 15} and _bins(db, SUGAR) == {"A2": 8}
    picks = _log(db, reason="pick")
    assert picks and all((r.ref_type, r.ref_id) == ("task", str(task.id)) for r in picks)
    assert tasks.picked_quantities([task.id]) == {task.id: {FLOUR: 5, SUGAR: 2}}
    with pytest.raises(tasks.TaskStateError):  # a done task takes no more picks
        tasks.pick_for_task(task.id, "eko", SUGAR, 1)


def test_over_pick_keeps_the_task_open_until_unassigned_back(db, mode):
    task = tasks.create_pick_task([(FLOUR, 2)], "eko", "boss")

    assert tasks.pick_for_task(task.id, "eko", FLOUR, 3).status == "open"
    back = tasks.unassign_from_task(task.id, "eko", FLOUR, 1)

    assert (back.qty, back.status, back.item_name) == (2, "done", "Flour")
    assert _bins(db, FLOUR) == {"A1": 18}
    (restore,) = _log(db, reason="pick_restore")
    assert (restore.ref_type, restore.ref_id) == ("task", str(task.id))


def test_unassign_more_than_picked_changes_nothing(db, mode):
    task = _pick_task()
    tasks.pick_for_task(task.id, "eko", FLOUR, 2)

    with pytest.raises(PickQuantityError):
        tasks.unassign_from_task(task.id, "eko", FLOUR, 3)
    with pytest.raises(LookupError):
        tasks.unassign_from_task(task.id, "eko", SUGAR, 1)

    assert _bins(db, FLOUR) == {"A1": 18}


def test_pick_refuses_a_sku_that_is_not_on_the_task(db, mode):
    task = tasks.create_pick_task([(FLOUR, 1)], "eko", "boss")

    with pytest.raises(tasks.TaskScanError):
        tasks.pick_for_task(task.id, "eko", SUGAR, 1)
    assert _bins(db, SUGAR) == {"A2": 10}


def test_strict_stock_rejects_a_task_pick_larger_than_the_stock(db, mode, monkeypatch):
    monkeypatch.setenv("STOCK_STRICT", "1")
    task = tasks.create_pick_task([(SUGAR, 11)], "eko", "boss")

    with pytest.raises(queries.InsufficientStockError):
        tasks.pick_for_task(task.id, "eko", SUGAR, 11)

    assert _bins(db, SUGAR) == {"A2": 10}
    assert _task_entries(db) == []


# ---------------------------------------------------------- kept out of order paths
def test_task_picks_never_reach_v1_payloads_or_the_release_script(db, mode):
    task = _pick_task()
    tasks.pick_for_task(task.id, "eko", FLOUR, 2)
    (entry,) = _task_entries(db)

    assert queries.get_pie_data() == []
    assert queries.get_pie_data(username="eko") == []
    assert queries.count_unassigned_picks() == 0
    assert queries.release_unassigned_picks(actor="script") == 0
    assert queries.delete_pie(entry.id, "eko") is False
    assert queries.delete_pie(entry.id, "boss", is_admin=True) is False
    with pytest.raises(LookupError):
        queries.assign_pick_item_entry(entry.id, "260101X", None, "eko")

    v1 = queries.create_pick_item_entry(FLOUR, 1, "eko")  # a v1 pool pick stays separate
    assert v1.id != entry.id and v1.task_line_id is None
    assert [e.id for e in queries.get_pie_data(username="eko")] == [v1.id]
    assert [(e.qty, e.task_line_id) for e in _task_entries(db)] == [(2, entry.task_line_id)]
    assert _bins(db, FLOUR) == {"A1": 17}


def test_v2_order_picks_never_merge_with_task_picks(db, mode):
    with db() as s:
        add_order(s, "260101ORDER1", owner="eko")
        s.commit()
    task = _pick_task()
    tasks.pick_for_task(task.id, "eko", FLOUR, 2)

    line = queries.pick_for_order("260101ORDER1", FLOUR, 1, "eko")

    assert line.qty == 1
    assert [e.qty for e in _task_entries(db)] == [2]


def test_cutover_clear_keeps_task_picks(db, mode):
    task = _pick_task()
    tasks.pick_for_task(task.id, "eko", FLOUR, 2)
    queries.create_pick_item_entry(SUGAR, 1, "eko")

    assert queries.clear_open_pick_entries(actor="cutover") == 1
    assert [e.qty for e in _task_entries(db)] == [2]


def test_only_task_picks_may_lose_their_owner(db):
    with db() as s:
        s.add(PickItemEntry(sku=FLOUR, qty=1, owner_user=None))
        with pytest.raises(IntegrityError):
            s.flush()


# ------------------------------------------------------------------ worker and admin
def test_cant_finish_blocks_the_task_and_stops_picking(db, mode):
    task = _pick_task()
    tasks.pick_for_task(task.id, "eko", FLOUR, 3)

    blocked = tasks.block_task(task.id, "eko", "only 3 on the shelf")

    assert (blocked.status, blocked.blocked_reason) == ("blocked", "only 3 on the shelf")
    with pytest.raises(tasks.TaskStateError):
        tasks.pick_for_task(task.id, "eko", FLOUR, 1)
    with pytest.raises(ValueError):
        tasks.block_task(task.id, "eko", "  ")


def test_close_as_picked_keeps_what_was_picked(db, mode):
    task = _pick_task()
    tasks.pick_for_task(task.id, "eko", FLOUR, 3)
    with pytest.raises(tasks.TaskStateError):  # only from blocked (T8)
        tasks.close_as_picked(task.id, "boss")
    tasks.block_task(task.id, "eko", "only 3 on the shelf")

    closed = tasks.close_as_picked(task.id, "boss")

    assert (closed.status, closed.closed_by) == ("done", "boss")
    assert [e.qty for e in _task_entries(db)] == [3]
    assert _bins(db, FLOUR) == {"A1": 17}


def test_cancel_returns_the_picked_stock_by_default(db, mode):
    task = _pick_task()
    tasks.pick_for_task(task.id, "eko", FLOUR, 3)

    cancelled = tasks.cancel_task(task.id, "boss")

    assert cancelled.status == "cancelled"
    assert _bins(db, FLOUR) == {"A1": 20}
    assert _task_entries(db) == []
    (restore,) = _log(db, reason="pick_restore")
    assert (restore.actor, restore.ref_type, restore.ref_id) == ("boss", "task", str(task.id))


def test_cancel_can_keep_the_picked_stock_deducted_and_logs_it(db, mode):
    task = _pick_task()
    tasks.pick_for_task(task.id, "eko", FLOUR, 3)

    tasks.cancel_task(task.id, "boss", return_stock=False)

    assert _bins(db, FLOUR) == {"A1": 17}
    assert [e.qty for e in _task_entries(db)] == [3]
    (kept,) = _log(db, reason="task_cancel_keep")
    assert (kept.sku, kept.delta, kept.ref_id) == (FLOUR, 0, str(task.id))
    with pytest.raises(tasks.TaskStateError):
        tasks.cancel_task(task.id, "boss")


def test_reassign_moves_the_picks_with_the_task(db, mode):
    task = _pick_task()
    tasks.pick_for_task(task.id, "eko", FLOUR, 3)
    tasks.block_task(task.id, "eko", "going home")

    moved = tasks.reassign_task(task.id, "ani", "boss")

    assert (moved.status, moved.assigned_to, moved.blocked_reason) == ("open", "ani", None)
    assert [e.owner_user for e in _task_entries(db)] == ["ani"]
    with pytest.raises(LookupError):
        tasks.pick_for_task(task.id, "eko", FLOUR, 1)
    assert tasks.pick_for_task(task.id, "ani", FLOUR, 2).qty == 5
    with pytest.raises(LookupError):
        tasks.reassign_task(task.id, "boss", "boss")


def test_deleting_a_worker_keeps_their_tasks_and_task_picks(db, mode):
    open_task = _pick_task()
    tasks.pick_for_task(open_task.id, "eko", FLOUR, 3)
    done_task = tasks.create_pick_task([(SUGAR, 1)], "eko", "boss")
    tasks.pick_for_task(done_task.id, "eko", SUGAR, 1)
    queries.create_pick_item_entry(SUGAR, 2, "eko")  # a v1 pick: restored as before

    assert queries.delete_user_by_username("eko", actor="boss") is True

    for task_id, status in ((open_task.id, "open"), (done_task.id, "done")):
        task = _task(db, task_id)
        assert (task.status, task.assigned_to, task.assigned_name) == (status, None, "eko")
    entries = _task_entries(db)
    assert [(e.sku, e.qty, e.owner_user) for e in entries] == [(FLOUR, 3, None), (SUGAR, 1, None)]
    with db() as s:
        allocated = s.execute(select(PickStockAllocation.sku, PickStockAllocation.qty)).all()
    assert sorted(allocated) == [(FLOUR, 3), (SUGAR, 1)]
    assert _bins(db, FLOUR) == {"A1": 17} and _bins(db, SUGAR) == {"A2": 9}
    assert [t.id for t in tasks.list_tasks(statuses=["open"]) if t.assigned_to is None] == [
        open_task.id
    ]

    tasks.reassign_task(open_task.id, "ani", "boss")
    assert tasks.pick_for_task(open_task.id, "ani", FLOUR, 2).qty == 5


def test_list_is_oldest_first_and_filters(db, mode):
    first = _pick_task()
    second = _count_task(mode)
    third = tasks.create_pick_task([(SUGAR, 1)], "ani", "boss")
    tasks.cancel_task(third.id, "boss")

    assert [t.id for t in tasks.list_tasks()] == [first.id, second.id, third.id]
    assert [t.id for t in tasks.list_tasks(assigned_to="eko")] == [first.id, second.id]
    assert [t.id for t in tasks.list_tasks(task_type="count")] == [second.id]
    assert [t.id for t in tasks.list_tasks(statuses=["open", "blocked"])] == [first.id, second.id]


# ------------------------------------------------------------------ console stock changes (T7.13)
def test_stock_changes_name_the_task_of_a_count_and_of_a_pick(db, mode):
    from src.services.queries import StockChangeFilter

    count = _count_task(mode)
    tasks.count_task(count.id, "eko", FLOUR, 18, location_scan="A1")
    pick = _pick_task(((SUGAR, 2),))
    tasks.pick_for_task(pick.id, "eko", SUGAR, 1)  # half: the task stays open
    page, _ = queries.get_stock_changes(limit=10, f=StockChangeFilter(actor="eko"))
    by_reason = {r["reason"]: r for r in page}
    assert by_reason["adjust_set"]["task_id"] == count.id
    assert by_reason["pick"]["task_id"] == pick.id
    assert by_reason["pick"]["order_sn"] is None

    tasks.unassign_from_task(pick.id, "eko", SUGAR, 1)  # back to stock: the same task
    page, _ = queries.get_stock_changes(limit=10, f=StockChangeFilter(reasons=("pick_restore",)))
    assert [r["task_id"] for r in page] == [pick.id]
