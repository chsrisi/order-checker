"""T4.8: the order upsert refreshes existing orders and respects retention (PostgreSQL)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.models import (
    ILImageInfo,
    ODItemList,
    ODPackageList,
    ODRecipientAddress,
    ShopeeOrderInfo,
    ShopeeOrderItemList,
    ShopeeOrderRecipientAddress,
    ShpOrderDetails,
)
from src.services import queries

from .factories import add_order


def _detail(sn, status="PROCESSED", ship_by=None, item="Synthetic A", note="note"):
    return ShpOrderDetails(
        order_sn=sn,
        order_status=status,
        ship_by_date=ship_by or datetime.now(UTC) + timedelta(days=2),
        note=note,
        item_list=[
            ODItemList(
                item_id=900000001,
                item_name=item,
                item_sku="Z90_001",
                model_quantity_purchased=2,
                image_info=ILImageInfo(image_url="http://example.invalid/i.jpg"),
            )
        ],
        package_list=[
            ODPackageList(
                package_number=f"PKG-{sn}", logistics_status="LOGISTICS_READY", shipping_carrier="X"
            )
        ],
        split_up=False,
        recipient_address=ODRecipientAddress(name="New Name", city="New City"),
    )


def test_old_open_order_cancelled_upstream_leaves_active_list(pg_session_factory):
    with pg_session_factory() as db:
        add_order(db, "OLD-OPEN", status="PROCESSED")
        add_order(db, "DONE-ONE", status="PROCESSED", done=True)
        db.commit()
    assert queries.local_active_order_sns(exclude=["SOMETHING"]) == ["OLD-OPEN"]
    assert queries.local_active_order_sns(exclude=["OLD-OPEN"]) == []

    queries.sync_shopee_orders_to_db([([_detail("OLD-OPEN", status="CANCELLED")], {}, set())])
    assert "OLD-OPEN" not in {o.order_sn for o in queries.get_all_shopee_order_data()}


def test_existing_order_gets_ship_by_items_and_recipient_refreshed(pg_session_factory):
    with pg_session_factory() as db:
        add_order(db, "EXISTING", status="READY_TO_SHIP", recipient=True, note="old")
        db.commit()
    new_ship_by = datetime.now(UTC) + timedelta(days=5)
    queries.sync_shopee_orders_to_db(
        [([_detail("EXISTING", ship_by=new_ship_by, item="Renamed")], {}, set())]
    )
    with pg_session_factory() as db:
        (order,) = queries.get_all_shopee_order_data()
        assert abs(order.ship_by.replace(tzinfo=UTC) - new_ship_by) < timedelta(seconds=1)
        assert order.status == "PROCESSED" and order.shipping_carrier == "X"
        items = db.execute(select(ShopeeOrderItemList)).scalars().all()
        assert [(i.item_name, i.model_quantity_purchased) for i in items] == [("Renamed", 2)]
        recipient = db.execute(select(ShopeeOrderRecipientAddress)).scalar_one()
        assert (recipient.name, recipient.city) == ("New Name", "New City")


def test_resync_never_restores_purged_buyer_data(pg_session_factory):
    long_ago = datetime.now(UTC) - timedelta(days=45)
    with pg_session_factory() as db:
        add_order(db, "OLD-DONE", status="COMPLETED", done=True, done_at=long_ago, note="n")
        db.commit()
    queries.purge_recipient_data(datetime.now(UTC) - timedelta(days=30))

    queries.sync_shopee_orders_to_db([([_detail("OLD-DONE", status="COMPLETED")], {}, set())])
    with pg_session_factory() as db:
        assert db.execute(select(ShopeeOrderRecipientAddress)).all() == []
        assert {i.note for i in db.execute(select(ShopeeOrderInfo)).scalars()} == {None}


def test_failed_packages_keep_their_tracking_number(pg_session_factory):
    with pg_session_factory() as db:
        add_order(db, "TRACKED", status="PROCESSED", tracking="TRK-KEEP")
        db.commit()
    detail = _detail("TRACKED")
    detail.package_list[0].package_number = "PKG-TRACKED"
    queries.sync_shopee_orders_to_db([([detail], {}, {"PKG-TRACKED"})])
    with pg_session_factory() as db:
        assert db.execute(select(ShopeeOrderInfo.tracking_number)).scalar_one() == "TRK-KEEP"
