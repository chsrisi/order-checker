import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from src.models import (
    Base,
    WarehouseItem,
    Stock,
    StocksLog,
    PickItemEntry,
    WSMessageType,
    PickItemEntryCreate,
    ShopeeOrder,
    User,
)
from src.services.queries import stocks as stock_queries
from src.services.queries import pick_items as pick_queries
from src.services.queries import warehouse as warehouse_queries
from src.services import pick_item_service
from src.routers import pick_items as pick_router


@pytest.fixture
def sqlite_test_db(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def do_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        for schema in ["warehouse", "auth", "shopee", "orders"]:
            cursor.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
        cursor.close()

    Base.metadata.create_all(test_engine)

    TestSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine, expire_on_commit=False
    )

    from contextlib import contextmanager

    @contextmanager
    def mock_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(stock_queries, "get_db", mock_get_db)
    monkeypatch.setattr(pick_queries, "get_db", mock_get_db)
    monkeypatch.setattr(warehouse_queries, "get_db", mock_get_db)

    # Insert test warehouse items
    with mock_get_db() as db:
        item = WarehouseItem(
            sku="SKU-PICK-001",
            item_name="Pickable Item 001",
            supplier_barcode="BAR-PICK-001",
        )
        db.add(item)
        db.commit()

    yield mock_get_db
    test_engine.dispose()


def _stocks(db_factory):
    with db_factory() as db:
        rows = db.execute(select(Stock).filter(Stock.sku == "SKU-PICK-001")).scalars().all()
        return {r.location: r.stock for r in rows}


def _logs(db_factory, reason):
    with db_factory() as db:
        return db.execute(select(StocksLog).filter(StocksLog.reason == reason)).scalars().all()


def _seed_stock(db_factory, *bins):
    with db_factory() as db:
        for location, qty in bins:
            db.add(Stock(sku="SKU-PICK-001", stock=qty, location=location))
        db.commit()


def _seed_order(db_factory, order_sn="240830123", owner="operator_1", done=False):
    with db_factory() as db:
        db.add(
            ShopeeOrder(
                order_sn=order_sn,
                owner_user=owner,
                done=done,
                split_up=False,
                ship_by=datetime.now(UTC),
                status="PROCESSED",
            )
        )
        db.commit()


def test_pick_deducts_bins_in_location_order_with_allocations(sqlite_test_db):
    _seed_stock(sqlite_test_db, ("LOC-B", 7), ("LOC-A", 3))
    pie = pick_queries.create_pick_item_entry(sku="SKU-PICK-001", qty=5, username="tester")

    assert _stocks(sqlite_test_db) == {"LOC-B": 5}  # LOC-A emptied first, then LOC-B
    assert [(a.location, a.qty) for a in pie.allocations] == [("LOC-A", 3), ("LOC-B", 2)]
    picks = _logs(sqlite_test_db, "pick")
    assert [(log.location, log.delta, log.before, log.after) for log in picks] == [
        ("LOC-A", -3, 3, 0),
        ("LOC-B", -2, 7, 5),
    ]
    assert all(log.actor == "tester" and log.ref_id == str(pie.id) for log in picks)


def test_create_pick_item_entry_reduces_stock(sqlite_test_db):
    _seed_stock(sqlite_test_db, ("LOC-1", 15))
    _seed_order(sqlite_test_db)

    pie = pick_queries.create_pick_item_entry(
        sku="SKU-PICK-001", qty=5, username="operator_1", order_sn="240830123"
    )

    assert pie.sku == "SKU-PICK-001"
    assert pie.qty == 5
    assert pie.owner_user == "operator_1"
    assert pie.order_sn == "240830123"
    assert _stocks(sqlite_test_db) == {"LOC-1": 10}


def test_create_pick_item_entry_insufficient_stock_succeeds_with_warning(sqlite_test_db, caplog):
    _seed_stock(sqlite_test_db, ("LOC-1", 2))

    with caplog.at_level(logging.WARNING):
        pie = pick_queries.create_pick_item_entry(sku="SKU-PICK-001", qty=5, username="operator_1")

    # Pick entry is created despite insufficient stock; only 2 are allocated.
    assert pie.qty == 5
    assert sum(a.qty for a in pie.allocations) == 2
    assert "pick_shortfall" in caplog.text
    assert _stocks(sqlite_test_db) == {}
    (shortfall,) = _logs(sqlite_test_db, "pick_shortfall")
    assert "unmet=3" in shortfall.message


def test_pick_with_no_stock_records_allocates_nothing(sqlite_test_db):
    pie = pick_queries.create_pick_item_entry(sku="SKU-PICK-001", qty=2, username="operator_1")
    assert pie.qty == 2 and pie.allocations == []
    assert len(_logs(sqlite_test_db, "pick_shortfall")) == 1


def test_pick_for_unknown_or_foreign_order_is_404_and_done_order_409(sqlite_test_db):
    _seed_stock(sqlite_test_db, ("LOC-1", 5))
    _seed_order(sqlite_test_db, "OWNED-BY-OTHER", owner="someone_else")
    _seed_order(sqlite_test_db, "DONE-ORDER", owner="operator_1", done=True)
    with pytest.raises(LookupError):
        pick_queries.create_pick_item_entry("SKU-PICK-001", 1, "operator_1", order_sn="MISSING")
    with pytest.raises(LookupError):
        pick_queries.create_pick_item_entry(
            "SKU-PICK-001", 1, "operator_1", order_sn="OWNED-BY-OTHER"
        )
    with pytest.raises(pick_queries.OrderClosedError):
        pick_queries.create_pick_item_entry("SKU-PICK-001", 1, "operator_1", order_sn="DONE-ORDER")
    assert _stocks(sqlite_test_db) == {"LOC-1": 5}  # nothing half-applied (T4.2)


@pytest.mark.parametrize("mode", ["multi", "single"])
def test_split_then_delete_restores_deducted_amounts(sqlite_test_db, monkeypatch, mode):
    monkeypatch.setenv("STOCK_LOCATION_MODE", mode)
    _seed_stock(sqlite_test_db, ("LOC-A", 4))
    _seed_order(sqlite_test_db, "ORD-1")
    pie = pick_queries.create_pick_item_entry("SKU-PICK-001", 6, "operator_1")  # 4 + 2 short

    assigned = pick_queries.assign_pick_item_entry(pie.id, "ORD-1", 3, "operator_1")
    assert assigned.qty == 3 and sum(a.qty for a in assigned.allocations) == 3  # deducted first
    with sqlite_test_db() as db:
        remainder = db.get(PickItemEntry, pie.id)
        assert remainder.qty == 3 and sum(a.qty for a in remainder.allocations) == 1
    assert _stocks(sqlite_test_db) == {}  # assign never touches stock

    assert pick_queries.delete_pie(assigned.id, "operator_1")
    assert _stocks(sqlite_test_db) == {"LOC-A": 3}  # bin recreated
    assert pick_queries.delete_pie(pie.id, "operator_1")
    assert _stocks(sqlite_test_db) == {"LOC-A": 4}  # no phantom stock from the shortfall
    assert {log.actor for log in _logs(sqlite_test_db, "pick_restore")} == {"operator_1"}


def test_restore_target_differs_per_mode(sqlite_test_db, monkeypatch):
    _seed_stock(sqlite_test_db, ("LOC-A", 2))
    pie = pick_queries.create_pick_item_entry("SKU-PICK-001", 2, "operator_1")
    # stock later moved/recounted at another bin
    stock_queries.update_or_move_stock("SKU-PICK-001", 5, "admin", location="LOC-Z")

    monkeypatch.setenv("STOCK_LOCATION_MODE", "single")
    stock_queries.update_or_move_stock("SKU-PICK-001", 5, "admin", location="LOC-Z")
    assert pick_queries.delete_pie(pie.id, "admin_user", is_admin=True)
    assert _stocks(sqlite_test_db) == {"LOC-Z": 7}  # single: the current sole location
    (restore,) = _logs(sqlite_test_db, "pick_restore")
    assert restore.actor == "admin_user"


def test_unassign_moves_quantity_without_stock_change(sqlite_test_db):
    _seed_stock(sqlite_test_db, ("LOC-A", 10))
    _seed_order(sqlite_test_db, "ORD-1")
    pie = pick_queries.create_pick_item_entry("SKU-PICK-001", 4, "operator_1", order_sn="ORD-1")
    assert pick_queries.unassign_pick_item_entry("ORD-1", "SKU-PICK-001", 1, "operator_1")
    assert _stocks(sqlite_test_db) == {"LOC-A": 6}
    with sqlite_test_db() as db:
        entries = {e.order_sn: e.qty for e in db.execute(select(PickItemEntry)).scalars()}
    assert entries == {"ORD-1": 3, None: 1}
    assert pie.id


def test_create_pick_item_entry_merges_existing_pie(sqlite_test_db):
    with sqlite_test_db() as db:
        db.add(Stock(sku="SKU-PICK-001", stock=20, location="LOC-1"))
        db.commit()

    pie1 = pick_queries.create_pick_item_entry(sku="SKU-PICK-001", qty=3, username="operator_1")
    assert pie1.qty == 3

    pie2 = pick_queries.create_pick_item_entry(sku="SKU-PICK-001", qty=4, username="operator_1")
    assert pie2.qty == 7
    assert pie2.id == pie1.id

    with sqlite_test_db() as db:
        records = db.execute(select(Stock).filter(Stock.sku == "SKU-PICK-001")).scalars().all()
        assert len(records) == 1
        assert records[0].stock == 13


@pytest.mark.asyncio
async def test_pick_service_create_broadcasts_stocks_and_pie(monkeypatch):
    pie_mock = PickItemEntry(
        id=1, sku="SKU-PICK-001", qty=3, owner_user="operator_1", order_sn=None
    )
    monkeypatch.setattr(pick_item_service.queries, "create_pick_item_entry", lambda **_: pie_mock)
    monkeypatch.setattr(pick_item_service.conn_mgr, "send_to_user", AsyncMock())
    monkeypatch.setattr(pick_item_service.conn_mgr, "broadcast", AsyncMock())

    result = await pick_item_service.create_pick_item_entry(
        sku="SKU-PICK-001", qty=3, username="operator_1"
    )
    assert result is pie_mock

    # Verify user send and broadcasts
    pick_item_service.conn_mgr.send_to_user.assert_awaited_once_with(
        WSMessageType.PICK_ITEM_ENTRIES, username="operator_1"
    )
    assert pick_item_service.conn_mgr.broadcast.await_count == 2
    pick_item_service.conn_mgr.broadcast.assert_any_await(
        WSMessageType.PICK_ITEM_ENTRIES, scope="admin"
    )
    pick_item_service.conn_mgr.broadcast.assert_any_await(WSMessageType.STOCKS)


@pytest.mark.asyncio
async def test_pick_router_create_pie_success_when_insufficient_stock(monkeypatch):
    from datetime import datetime, UTC

    pie_mock = PickItemEntry(
        id=1,
        sku="SKU-PICK-001",
        qty=10,
        owner_user="operator_1",
        order_sn=None,
        timestamp=datetime.now(UTC),
    )
    monkeypatch.setattr(
        pick_router.pick_item_service,
        "create_pick_item_entry",
        AsyncMock(return_value=pie_mock),
    )
    monkeypatch.setattr(
        pick_router.queries,
        "resolve_barcode_to_item",
        lambda _: WarehouseItem(sku="SKU-PICK-001", item_name="Pickable Item 001"),
    )

    user = User(username="operator_1", password_hash="hash", scope="client")
    response = await pick_router.create_pie(
        PickItemEntryCreate(sku="SKU-PICK-001", qty=10),
        current_user=user,
    )

    assert response.sku == "SKU-PICK-001"
    assert response.qty == 10
    assert response.item_name == "Pickable Item 001"
