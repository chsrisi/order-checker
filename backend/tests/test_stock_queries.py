import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from src.models import Base, WarehouseItem, Stock, StocksLog
from src.services.queries import stocks as stock_queries
from src.services.queries.engine import SessionLocal


def test_session_local_expire_on_commit_is_false():
    session = SessionLocal()
    try:
        assert session.expire_on_commit is False
    finally:
        session.close()


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

    # Create tables in the attached schemas
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

    # Insert a test warehouse item
    with mock_get_db() as db:
        item = WarehouseItem(
            sku="TEST-SKU-001",
            item_name="Test Product 001",
            supplier_barcode="BAR-001",
        )
        db.add(item)
        db.commit()

    yield mock_get_db
    test_engine.dispose()


def test_update_or_move_stock_set_mode_returns_accessible_stock(sqlite_test_db, monkeypatch):
    item = WarehouseItem(
        sku="TEST-SKU-001",
        item_name="Test Product 001",
    )
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # 1. Set stock for the first time (creates record)
    res, item_name = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=15,
        username="tester",
        mode="set",
        location="LOC-1",
        is_location_set=True,
    )

    # Verify attributes can be accessed on detached instance without DetachedInstanceError
    assert res.sku == "TEST-SKU-001"
    assert res.stock == 15
    assert res.location == "LOC-1"
    assert item_name == "Test Product 001"

    # 2. Update (set) existing stock
    res2, item_name2 = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=25,
        username="tester",
        mode="set",
        location="LOC-1",
        is_location_set=True,
    )
    assert res2.sku == "TEST-SKU-001"
    assert res2.stock == 25
    assert res2.location == "LOC-1"
    assert item_name2 == "Test Product 001"


def test_update_or_move_stock_add_mode_and_move_mode(sqlite_test_db, monkeypatch):
    item = WarehouseItem(
        sku="TEST-SKU-001",
        item_name="Test Product 001",
    )
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # Set initial stock
    stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=10,
        username="tester",
        mode="set",
        location="LOC-1",
    )

    # Add stock
    res, item_name = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=5,
        username="tester",
        mode="add",
        location="LOC-1",
    )
    assert res.stock == 15
    assert res.sku == "TEST-SKU-001"

    # Move stock to same location
    res_same, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=5,
        username="tester",
        location="LOC-1",
        move_to="LOC-1",
    )
    assert res_same.location == "LOC-1"

    # Move stock from LOC-1 to LOC-2
    res_move, item_name = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=5,
        username="tester",
        location="LOC-1",
        move_to="LOC-2",
    )
    assert res_move.location == "LOC-2"
    assert res_move.stock == 5

    # Move error when source has no stock
    with pytest.raises(ValueError, match="Source location has no stock"):
        stock_queries.update_or_move_stock(
            sku_in="TEST-SKU-001",
            stock_qty=5,
            username="tester",
            location="NONEXISTENT-LOC",
            move_to="LOC-2",
        )

    # Move error when source has insufficient stock
    with pytest.raises(ValueError, match="Insufficient stock"):
        stock_queries.update_or_move_stock(
            sku_in="TEST-SKU-001",
            stock_qty=100,
            username="tester",
            location="LOC-1",
            move_to="LOC-2",
        )


def test_update_or_move_stock_validation_and_zero_qty(sqlite_test_db, monkeypatch):
    item = WarehouseItem(
        sku="TEST-SKU-001",
        item_name="Test Product 001",
    )
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # Negative stock
    with pytest.raises(ValueError, match="Stock quantity cannot be negative"):
        stock_queries.update_or_move_stock(
            sku_in="TEST-SKU-001",
            stock_qty=-1,
            username="tester",
        )

    # Missing item
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: None)
    with pytest.raises(LookupError, match="not found"):
        stock_queries.update_or_move_stock(
            sku_in="INVALID",
            stock_qty=5,
            username="tester",
        )

    # Set to 0 deletes record and returns 0 stock object
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)
    res, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=0,
        username="tester",
        location="LOC-1",
    )
    assert res.stock == 0


def test_get_or_merge_stock_returns_accessible_stock(sqlite_test_db):
    res = stock_queries.get_or_merge_stock(
        sku="TEST-SKU-001",
        location="LOC-MERGE",
        qty=8,
        username="tester",
    )
    assert res.sku == "TEST-SKU-001"
    assert res.stock == 8
    assert res.location == "LOC-MERGE"

    # Merge / update
    res2 = stock_queries.get_or_merge_stock(
        sku="TEST-SKU-001",
        location="LOC-MERGE",
        qty=12,
        username="tester",
    )
    assert res2.sku == "TEST-SKU-001"
    assert res2.stock == 12


def test_get_stocks_data_queries(sqlite_test_db):
    # Retrieve without join
    stocks = stock_queries.get_stocks_data(join_warehouse=False)
    assert isinstance(stocks, list)

    # Retrieve with join
    stocks_joined = stock_queries.get_stocks_data(join_warehouse=True)
    assert isinstance(stocks_joined, list)

    # All stocks alias
    assert isinstance(stock_queries.get_all_stocks_data(), list)


def test_single_location_bypass_add_and_set_no_location(sqlite_test_db, monkeypatch):
    monkeypatch.setenv("SINGLE_LOCATION_STOCK_BYPASS", "1")
    item = WarehouseItem(sku="TEST-SKU-001", item_name="Test Product 001")
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # Initial set at LOC-1
    res1, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=10,
        username="tester",
        mode="set",
        location="LOC-1",
    )
    assert res1.stock == 10
    assert res1.location == "LOC-1"

    # Add 5 with location=None -> updates in sole location LOC-1
    res2, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=5,
        username="tester",
        mode="add",
        location=None,
    )
    assert res2.stock == 15
    assert res2.location == "LOC-1"

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        assert len(records) == 1
        assert records[0].stock == 15
        assert records[0].location == "LOC-1"

    # Set 30 with location=None -> updates in sole location LOC-1
    res3, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=30,
        username="tester",
        mode="set",
        location=None,
    )
    assert res3.stock == 30
    assert res3.location == "LOC-1"

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        assert len(records) == 1
        assert records[0].stock == 30


def test_single_location_bypass_location_provided_transfers_all(sqlite_test_db, monkeypatch):
    monkeypatch.setenv("SINGLE_LOCATION_STOCK_BYPASS", "1")
    item = WarehouseItem(sku="TEST-SKU-001", item_name="Test Product 001")
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # Initial stock: 10 at LOC-1
    stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=10,
        username="tester",
        mode="set",
        location="LOC-1",
    )

    # Add 5 with location="LOC-2" -> transfers 10 to LOC-2, then adds 5 => 15 at LOC-2
    res, item_name = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=5,
        username="tester",
        mode="add",
        location="LOC-2",
    )
    assert res.stock == 15
    assert res.location == "LOC-2"

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        assert len(records) == 1
        assert records[0].stock == 15
        assert records[0].location == "LOC-2"

    # Set 40 with location="LOC-3" -> transfers to LOC-3, sets to 40
    res_set, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=40,
        username="tester",
        mode="set",
        location="LOC-3",
    )
    assert res_set.stock == 40
    assert res_set.location == "LOC-3"

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        assert len(records) == 1
        assert records[0].stock == 40
        assert records[0].location == "LOC-3"


def test_single_location_bypass_no_prior_stock_and_zero_deletion(sqlite_test_db, monkeypatch):
    monkeypatch.setenv("SINGLE_LOCATION_STOCK_BYPASS", "1")
    item = WarehouseItem(sku="TEST-SKU-001", item_name="Test Product 001")
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # No prior stock, location=None -> creates stock with location=None
    res, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=8,
        username="tester",
        mode="set",
        location=None,
    )
    assert res.stock == 8
    assert res.location is None

    # Set to 0 -> deletes record
    res_zero, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=0,
        username="tester",
        mode="set",
        location=None,
    )
    assert res_zero.stock == 0

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        assert len(records) == 0



def test_single_location_bypass_consolidates_multiple_preexisting_locations(sqlite_test_db, monkeypatch):
    # Seed multiple existing records in DB (legacy state before bypass enabled)
    with sqlite_test_db() as db:
        db.add(Stock(sku="TEST-SKU-001", stock=10, location="LOC-A"))
        db.add(Stock(sku="TEST-SKU-001", stock=20, location="LOC-B"))
        db.commit()

    monkeypatch.setenv("SINGLE_LOCATION_STOCK_BYPASS", "1")
    item = WarehouseItem(sku="TEST-SKU-001", item_name="Test Product 001")
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # Add 5 with location=None -> consolidates 10+20=30 + 5 = 35 into LOC-A
    res, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=5,
        username="tester",
        mode="add",
        location=None,
    )
    assert res.stock == 35
    assert res.location == "LOC-A"

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        assert len(records) == 1
        assert records[0].stock == 35
        assert records[0].location == "LOC-A"


def test_single_location_bypass_move_to_operations(sqlite_test_db, monkeypatch):
    monkeypatch.setenv("SINGLE_LOCATION_STOCK_BYPASS", "1")
    item = WarehouseItem(sku="TEST-SKU-001", item_name="Test Product 001")
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # Initial stock: 15 at LOC-1
    stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=15,
        username="tester",
        mode="set",
        location="LOC-1",
    )

    # Same location move
    res_same, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=5,
        username="tester",
        location="LOC-1",
        move_to="LOC-1",
    )
    assert res_same.location == "LOC-1"

    # Transfer to LOC-2
    res_move, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=15,
        username="tester",
        location="LOC-1",
        move_to="LOC-2",
    )
    assert res_move.location == "LOC-2"
    assert res_move.stock == 15

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        assert len(records) == 1
        assert records[0].location == "LOC-2"
        assert records[0].stock == 15


def test_single_location_bypass_get_or_merge_stock(sqlite_test_db, monkeypatch):
    monkeypatch.setenv("SINGLE_LOCATION_STOCK_BYPASS", "1")

    # First merge at LOC-A
    res1 = stock_queries.get_or_merge_stock(
        sku="TEST-SKU-001",
        location="LOC-A",
        qty=10,
        username="tester",
    )
    assert res1.stock == 10
    assert res1.location == "LOC-A"

    # Merge at LOC-B -> removes LOC-A and sets LOC-B
    res2 = stock_queries.get_or_merge_stock(
        sku="TEST-SKU-001",
        location="LOC-B",
        qty=25,
        username="tester",
    )
    assert res2.stock == 25
    assert res2.location == "LOC-B"

    # Merge with location=None -> preserves sole location LOC-B
    res3 = stock_queries.get_or_merge_stock(
        sku="TEST-SKU-001",
        location=None,
        qty=30,
        username="tester",
    )
    assert res3.stock == 30
    assert res3.location == "LOC-B"

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        assert len(records) == 1
        assert records[0].stock == 30
        assert records[0].location == "LOC-B"


def test_single_location_bypass_move_to_errors_and_edge_cases(sqlite_test_db, monkeypatch):
    monkeypatch.setenv("SINGLE_LOCATION_STOCK_BYPASS", "1")
    item = WarehouseItem(sku="TEST-SKU-001", item_name="Test Product 001")
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # 1. Same location move when no record exists creates 0 stock
    res_same, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=0,
        username="tester",
        location="LOC-EMPTY",
        move_to="LOC-EMPTY",
    )
    assert res_same.stock == 0
    assert res_same.location == "LOC-EMPTY"

    # 2. Move when total stock is 0
    with pytest.raises(ValueError, match="Source location has no stock"):
        stock_queries.update_or_move_stock(
            sku_in="TEST-SKU-001",
            stock_qty=5,
            username="tester",
            location="LOC-EMPTY",
            move_to="LOC-DEST",
        )

    # Set some stock
    stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=10,
        username="tester",
        mode="set",
        location="LOC-1",
    )

    # 3. Move when insufficient stock
    with pytest.raises(ValueError, match="Insufficient stock"):
        stock_queries.update_or_move_stock(
            sku_in="TEST-SKU-001",
            stock_qty=50,
            username="tester",
            location="LOC-1",
            move_to="LOC-DEST",
        )


def test_single_location_bypass_zero_stock_with_location_specified(sqlite_test_db, monkeypatch):
    monkeypatch.setenv("SINGLE_LOCATION_STOCK_BYPASS", "1")
    item = WarehouseItem(sku="TEST-SKU-001", item_name="Test Product 001")
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # Set initial stock at LOC-1
    stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=20,
        username="tester",
        mode="set",
        location="LOC-1",
    )

    # Set 0 with location="LOC-NEW" -> transfers and clears to 0
    res_zero, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=0,
        username="tester",
        mode="set",
        location="LOC-NEW",
    )
    assert res_zero.stock == 0
    assert res_zero.location == "LOC-NEW"

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        assert len(records) == 0


def test_single_location_bypass_alias_and_disabled_mode(sqlite_test_db, monkeypatch):
    item = WarehouseItem(sku="TEST-SKU-001", item_name="Test Product 001")
    monkeypatch.setattr(stock_queries, "resolve_barcode_to_item", lambda barcode: item)

    # 1. Alias STOCK_SINGLE_LOCATION_BYPASS
    monkeypatch.delenv("SINGLE_LOCATION_STOCK_BYPASS", raising=False)
    monkeypatch.setenv("STOCK_SINGLE_LOCATION_BYPASS", "1")

    res_alias, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=12,
        username="tester",
        mode="set",
        location="LOC-ALIAS",
    )
    assert res_alias.stock == 12
    assert res_alias.location == "LOC-ALIAS"

    # Add without location -> updates sole location
    res_alias_add, _ = stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=3,
        username="tester",
        mode="add",
        location=None,
    )
    assert res_alias_add.stock == 15
    assert res_alias_add.location == "LOC-ALIAS"

    # 2. Disabled mode allows independent multiple locations
    monkeypatch.setenv("SINGLE_LOCATION_STOCK_BYPASS", "0")
    monkeypatch.setenv("STOCK_SINGLE_LOCATION_BYPASS", "0")

    stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=50,
        username="tester",
        mode="set",
        location="LOC-MULTI-1",
    )
    stock_queries.update_or_move_stock(
        sku_in="TEST-SKU-001",
        stock_qty=75,
        username="tester",
        mode="set",
        location="LOC-MULTI-2",
    )

    with sqlite_test_db() as db:
        records = db.execute(
            select(Stock).filter(Stock.sku == "TEST-SKU-001")
        ).scalars().all()
        # Should have LOC-ALIAS, LOC-MULTI-1, LOC-MULTI-2 concurrently
        locations = {r.location for r in records}
        assert "LOC-MULTI-1" in locations
        assert "LOC-MULTI-2" in locations
        assert len(records) >= 2


