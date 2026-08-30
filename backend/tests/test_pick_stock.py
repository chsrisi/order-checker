import logging
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


def test_reduce_stock_for_pick_zero_or_negative_qty(sqlite_test_db):
    assert stock_queries.reduce_stock_for_pick("SKU-PICK-001", 0, "tester") == 0
    assert stock_queries.reduce_stock_for_pick("SKU-PICK-001", -5, "tester") == 0


def test_reduce_stock_for_pick_sufficient_stock_single_location(sqlite_test_db):
    with sqlite_test_db() as db:
        db.add(Stock(sku="SKU-PICK-001", stock=10, location="LOC-A"))
        db.commit()

    remaining = stock_queries.reduce_stock_for_pick("SKU-PICK-001", 4, "tester")
    assert remaining == 6

    with sqlite_test_db() as db:
        records = db.execute(select(Stock).filter(Stock.sku == "SKU-PICK-001")).scalars().all()
        assert len(records) == 1
        assert records[0].stock == 6

        logs = db.execute(select(StocksLog)).scalars().all()
        assert any("stock pick: sku=SKU-PICK-001, qty=4" in log.message for log in logs)


def test_reduce_stock_for_pick_multi_location_sequential_deduction(sqlite_test_db):
    with sqlite_test_db() as db:
        db.add(Stock(sku="SKU-PICK-001", stock=3, location="LOC-A"))
        db.add(Stock(sku="SKU-PICK-001", stock=7, location="LOC-B"))
        db.commit()

    # Deduct 5 (3 from LOC-A -> deleted, 2 from LOC-B -> 5 remaining)
    remaining = stock_queries.reduce_stock_for_pick("SKU-PICK-001", 5, "tester")
    assert remaining == 5

    with sqlite_test_db() as db:
        records = db.execute(select(Stock).filter(Stock.sku == "SKU-PICK-001")).scalars().all()
        assert len(records) == 1
        assert records[0].location == "LOC-B"
        assert records[0].stock == 5


def test_reduce_stock_for_pick_insufficient_stock_clamps_to_zero_and_logs_warning(
    sqlite_test_db, caplog
):
    with sqlite_test_db() as db:
        db.add(Stock(sku="SKU-PICK-001", stock=3, location="LOC-A"))
        db.commit()

    with caplog.at_level(logging.WARNING):
        remaining = stock_queries.reduce_stock_for_pick("SKU-PICK-001", 10, "tester")

    assert remaining == 0
    assert "Insufficient stock for SKU 'SKU-PICK-001'" in caplog.text
    assert "requested 10, available 3. Available qty set to 0." in caplog.text

    with sqlite_test_db() as db:
        records = db.execute(select(Stock).filter(Stock.sku == "SKU-PICK-001")).scalars().all()
        assert len(records) == 0

        logs = db.execute(select(StocksLog)).scalars().all()
        assert any("warning=insufficient_stock" in log.message for log in logs)


def test_reduce_stock_for_pick_no_stock_records_clamps_to_zero_and_logs_warning(
    sqlite_test_db, caplog
):
    with caplog.at_level(logging.WARNING):
        remaining = stock_queries.reduce_stock_for_pick("SKU-PICK-001", 2, "tester")

    assert remaining == 0
    assert "Insufficient stock for SKU 'SKU-PICK-001'" in caplog.text
    assert "requested 2, available 0" in caplog.text

    with sqlite_test_db() as db:
        records = db.execute(select(Stock).filter(Stock.sku == "SKU-PICK-001")).scalars().all()
        assert len(records) == 0


def test_create_pick_item_entry_reduces_stock(sqlite_test_db):
    item = WarehouseItem(sku="SKU-PICK-001", item_name="Pickable Item 001")
    with sqlite_test_db() as db:
        db.add(Stock(sku="SKU-PICK-001", stock=15, location="LOC-1"))
        db.commit()

    pie = pick_queries.create_pick_item_entry(
        sku="SKU-PICK-001", qty=5, username="operator_1", order_sn="240830123"
    )

    assert pie.sku == "SKU-PICK-001"
    assert pie.qty == 5
    assert pie.owner_user == "operator_1"
    assert pie.order_sn == "240830123"

    with sqlite_test_db() as db:
        records = db.execute(select(Stock).filter(Stock.sku == "SKU-PICK-001")).scalars().all()
        assert len(records) == 1
        assert records[0].stock == 10


def test_create_pick_item_entry_insufficient_stock_succeeds_with_warning(sqlite_test_db, caplog):
    with sqlite_test_db() as db:
        db.add(Stock(sku="SKU-PICK-001", stock=2, location="LOC-1"))
        db.commit()

    with caplog.at_level(logging.WARNING):
        pie = pick_queries.create_pick_item_entry(sku="SKU-PICK-001", qty=5, username="operator_1")

    # Pick entry is successfully created despite insufficient stock
    assert pie.sku == "SKU-PICK-001"
    assert pie.qty == 5
    assert "Insufficient stock for SKU 'SKU-PICK-001'" in caplog.text

    # Stock is clamped to 0 (records deleted)
    with sqlite_test_db() as db:
        records = db.execute(select(Stock).filter(Stock.sku == "SKU-PICK-001")).scalars().all()
        assert len(records) == 0


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
