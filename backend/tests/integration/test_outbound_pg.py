"""T1.6 / F-M1: period-close counts with duplicate labels."""

import pytest

from src.services import queries

from .factories import add_order, add_user


def _scan(user, content):
    return queries.create_outbound_item(content, user, [])


def test_shared_label_counts_rows_and_unknown_inputs(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_user(db, "bob")
        add_user(db, "admin", scope="admin")
        db.commit()
    _scan("alice", "LABEL-1")
    _scan("bob", "LABEL-1")
    _scan("alice", "LABEL-2")

    result = queries.close_outbound_items(["LABEL-1", "LABEL-2", "MISSING"], "admin")
    assert result["outbound"] == 3
    assert result["unknown"] == 1


def test_duplicate_inputs_count_once(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        db.commit()
    _scan("alice", "LABEL-1")
    result = queries.close_outbound_items(["LABEL-1", " LABEL-1 ", "X", "X"], "admin")
    assert result == {"outbound": 1, "unknown": 1, "orders_done": 0}


def test_close_matches_labels_exactly(pg_session_factory):
    """V2_ORDERS_DELTA Q57 (replaces Q44): trimmed, then exact, for scans as well as for the
    orders a close completes (by SN or tracking number)."""
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_order(db, "260101ABCD")
        add_order(db, "260101TRCK", tracking="SPXID0123")
        db.commit()
    _scan("alice", "260101abcd")
    _scan("alice", "SPXID0123")

    result = queries.close_outbound_items(["260101abcd", " SPXID0123 ", "spxid0123"], "admin")
    assert result == {"outbound": 2, "unknown": 1, "orders_done": 1}


# V2_ORDERS_DELTA C1: a sync closes scans whose order left on Shopee.


def _state(pg_session_factory):
    from sqlalchemy import select

    from src.models import OutboundItem, ShopeeOrder

    with pg_session_factory() as db:
        scans = dict(db.execute(select(OutboundItem.content, OutboundItem.closed)).all())
        orders = dict(db.execute(select(ShopeeOrder.order_sn, ShopeeOrder.done)).all())
    return scans, orders


@pytest.mark.parametrize(
    "status,closes",
    [
        ("SHIPPED", True),
        ("TO_CONFIRM_RECEIVE", True),
        ("COMPLETED", True),
        ("READY_TO_SHIP", False),
        ("PROCESSED", False),
        ("RETRY_SHIP", False),
        ("CANCELLED", False),
        ("IN_CANCEL", False),
        ("TO_RETURN", False),
    ],
)
def test_auto_close_by_status(pg_session_factory, status, closes):
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_order(db, "SN", status=status, tracking="TRK")
        db.commit()
    _scan("alice", "TRK")
    assert queries.close_shipped_outbound() == {"outbound": int(closes), "orders_done": int(closes)}
    assert _state(pg_session_factory) == ({"TRK": closes}, {"SN": closes})


def test_auto_close_matches_both_barcodes_exactly_and_leaves_the_rest(pg_session_factory):
    from src.models import ShopeeOrderInfo

    with pg_session_factory() as db:
        add_user(db, "alice")
        add_user(db, "bob")
        add_order(db, "BOTH", status="SHIPPED", tracking="TRK-1")
        add_order(db, "SPLIT", status="SHIPPED", tracking="PKG-A")  # Q52: PKG-B is not scanned
        db.add(ShopeeOrderInfo(order_sn="SPLIT", package_number="P2", tracking_number="PKG-B"))
        add_order(db, "UNSCANNED", status="SHIPPED", tracking="TRK-2")
        add_order(db, "DONE", status="COMPLETED", done=True)
        add_order(db, "OTHERCASE", status="SHIPPED")
        db.commit()
    _scan("alice", "BOTH")
    _scan("bob", "BOTH")
    for label in ("TRK-1", "PKG-A", "DONE", "othercase", "TOKO-1"):
        _scan("alice", label)

    # DONE's scan is a rescan of an order that is already done: the scan still closes.
    assert queries.close_shipped_outbound() == {"outbound": 5, "orders_done": 2}
    scans, orders = _state(pg_session_factory)
    assert {c for c, closed in scans.items() if not closed} == {"othercase", "TOKO-1"}
    assert {sn for sn, done in orders.items() if not done} == {"UNSCANNED", "OTHERCASE"}
    assert queries.close_shipped_outbound() == {"outbound": 0, "orders_done": 0}


def test_auto_close_catches_a_label_scanned_after_the_order_shipped(pg_session_factory):
    with pg_session_factory() as db:
        add_user(db, "alice")
        add_order(db, "LATE", status="SHIPPED")
        db.commit()
    assert queries.close_shipped_outbound()["outbound"] == 0
    _scan("alice", "LATE")
    assert queries.close_shipped_outbound() == {"outbound": 1, "orders_done": 1}
