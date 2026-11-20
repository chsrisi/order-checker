"""T2.11 / A-10b: recipient data is purged after RECIPIENT_RETENTION_DAYS."""

from datetime import UTC, datetime, timedelta

from src import config
from src.models import ShopeeOrder, ShopeeOrderInfo, ShopeeOrderRecipientAddress
from src.services import retention_service

from .factories import add_order

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _state(factory, order_sn):
    from sqlalchemy import select

    with factory() as db:
        addr = db.execute(
            select(ShopeeOrderRecipientAddress).filter_by(order_sn=order_sn)
        ).scalar_one_or_none()
        info = db.execute(select(ShopeeOrderInfo).filter_by(order_sn=order_sn)).scalar_one()
        return addr is not None, info.note, info.tracking_number, db.get(ShopeeOrder, order_sn)


def test_purge_by_done_at_and_ship_by(pg_session_factory, monkeypatch, caplog):
    monkeypatch.setattr(config, "RECIPIENT_RETENTION_DAYS", 30)
    old, recent = NOW - timedelta(days=31), NOW - timedelta(days=29)
    kw = dict(recipient=True, note="Leave at door", tracking="TRK")
    with pg_session_factory() as db:
        add_order(db, "DONE_OLD", done=True, done_at=old, ship_by=old, **kw)
        add_order(db, "DONE_RECENT", done=True, done_at=recent, ship_by=old, **kw)
        add_order(db, "OPEN_OLD", ship_by=old, **kw)
        add_order(db, "OPEN_RECENT", ship_by=recent, **kw)
        db.commit()

    with caplog.at_level("INFO"):
        assert retention_service.purge_expired_recipient_data(now=NOW) == (2, 2)

    for sn in ("DONE_OLD", "OPEN_OLD"):
        has_addr, note, tracking, order = _state(pg_session_factory, sn)
        assert (has_addr, note) == (False, None)
        assert tracking == "TRK" and order is not None  # order and tracking are kept
    for sn in ("DONE_RECENT", "OPEN_RECENT"):
        assert _state(pg_session_factory, sn)[:2] == (True, "Leave at door")
    assert "Synthetic Name" not in caplog.text and "Leave at door" not in caplog.text

    assert retention_service.purge_expired_recipient_data(now=NOW) == (0, 0)  # idempotent


async def test_order_response_tolerates_purged_recipient(pg_session_factory, monkeypatch):
    from src.services import shopee_service

    with pg_session_factory() as db:
        add_order(db, "GONE", ship_by=datetime.now(UTC) + timedelta(days=1), recipient=False)
        db.commit()
    monkeypatch.setattr(shopee_service.cache_mgr, "is_valid", lambda: True)
    orders = await shopee_service.sync_shopee_orders(False, "boss", "admin")
    assert orders[0].recipient_address is None
