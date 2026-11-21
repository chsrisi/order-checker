"""Pre-0.5.0 fixes found during the documentation pass (KNOWN_LIMITATIONS #11, #12 as of
2026-11-21), on PostgreSQL."""

from types import SimpleNamespace

from sqlalchemy import select

from src.models import OutboundItem, PickItemEntry, ShopeeOrder, Stock, StocksLog, User
from src.routers import stocks as stocks_router
from src.services import queries

from .factories import add_item, add_order, add_stock, add_user


def test_get_stocks_works_with_and_without_warehouse_join(pg_session_factory):
    with pg_session_factory() as db:
        add_item(db, "A01_001", name="Flour")
        add_item(db, "B01_001", name="Sugar")
        add_stock(db, "A01_001", 4, "A-01")
        add_stock(db, "B01_001", 1, None)
        db.commit()
    user = SimpleNamespace(username="op", scope="client")

    plain = stocks_router.get_stocks(join_warehouse=False, current_user=user)
    assert {(s.sku, s.stock, s.location, s.item_name) for s in plain} == {
        ("A01_001", 4, "A-01", None),
        ("B01_001", 1, None, None),
    }
    joined = stocks_router.get_stocks(join_warehouse=True, current_user=user)
    assert {(s.sku, s.item_name) for s in joined} == {("A01_001", "Flour"), ("B01_001", "Sugar")}


def test_deleting_a_user_restores_its_picked_stock(pg_session_factory, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", "multi")
    with pg_session_factory() as db:
        add_user(db, "op")
        add_user(db, "other")
        add_item(db, "A01_001")
        add_item(db, "B01_001")
        add_stock(db, "A01_001", 3, "A-01")
        add_stock(db, "A01_001", 2, "B-02")
        add_stock(db, "B01_001", 5, None)
        add_order(db, "ORD-1", owner="op")
        db.add(OutboundItem(content="label", owner_user="op"))
        db.commit()
    queries.create_pick_item_entry("A01_001", 4, "op")  # 3 from A-01, 1 from B-02
    queries.create_pick_item_entry("A01_001", 1, "op", order_sn="ORD-1")
    queries.create_pick_item_entry("B01_001", 7, "op")  # 5 deducted, 2 short
    queries.create_pick_item_entry("B01_001", 1, "other")  # stock is 0: all shortfall

    assert queries.delete_user_by_username("op", actor="boss")

    with pg_session_factory() as db:
        bins = {(s.sku, s.location): s.stock for s in db.execute(select(Stock)).scalars()}
        assert bins == {("A01_001", "A-01"): 3, ("A01_001", "B-02"): 2, ("B01_001", None): 5}
        assert [e.owner_user for e in db.execute(select(PickItemEntry)).scalars()] == ["other"]
        restores = db.execute(select(StocksLog).filter_by(reason="pick_restore")).scalars().all()
        assert {r.actor for r in restores} == {"boss"}
        assert sum(r.delta for r in restores) == 3 + 1 + 1 + 5
        assert db.execute(select(OutboundItem)).all() == []
        assert db.get(ShopeeOrder, "ORD-1").owner_user is None
        assert db.get(User, "op") is None


def test_deleting_admin_or_unknown_user_changes_nothing(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "root", scope="admin")
        db.commit()
    assert not queries.delete_user_by_username("root", actor="boss")
    assert not queries.delete_user_by_username("ghost", actor="boss")
