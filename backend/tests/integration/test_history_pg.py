"""T5.2: admin history is paginated newest-first with X-Total-Count."""

from datetime import UTC, date, datetime, timedelta

from src.services import queries

from .factories import add_order


def test_order_history_pages_are_newest_first_and_disjoint(pg_session_factory):
    base = datetime.now(UTC) - timedelta(days=1)
    with pg_session_factory() as db:
        for i in range(5):
            add_order(db, f"H{i}", done=True, status="COMPLETED", done_at=base + timedelta(hours=i))
        add_order(db, "OPEN", status="PROCESSED")
        db.commit()

    first, total = queries.get_shopee_orders_history(limit=2, offset=0)
    second, _ = queries.get_shopee_orders_history(limit=2, offset=2)
    rest, _ = queries.get_shopee_orders_history(limit=2, offset=4)
    assert total == 5
    assert [o.order_sn for o in first + second + rest] == ["H4", "H3", "H2", "H1", "H0"]


def test_outbound_history_pagination(pg_session_factory):
    with pg_session_factory() as db:
        from .factories import add_user

        add_user(db, "op")
        db.commit()
    for i in range(3):
        queries.create_outbound_item(content=f"LABEL-{i}", owner_username="op", tags_in=[])
    queries.close_outbound_items(contents=[f"LABEL-{i}" for i in range(3)], admin_username="a")
    page, total = queries.get_outbound_history(limit=2)
    assert total == 3 and len(page) == 2


# Delta 9 (Q40) and V2_ORDERS_DELTA C2: server-side filters and the list of days.


def _close(labels, *, user="op", tags=()):
    for label in labels:
        queries.create_outbound_item(content=label, owner_username=user, tags_in=list(tags))
    return queries.close_outbound_items(contents=list(labels), admin_username="a")


def _seed_two_days(pg_session_factory):
    """Scanned 23:59 on 24 Nov and 00:00 on 25 Nov at +07:00 (the same UTC day), closed later."""
    from .factories import add_user

    with pg_session_factory() as db:
        add_user(db, "op")
        add_user(db, "other")
        add_order(db, "251101AAA", owner="op", tracking="SPX-111")
        add_order(db, "251101BBB", owner="other")
        db.commit()
    _close(["SPX-111", "LOOSE-1"], tags=["Morning"])
    _close(["251101BBB"], user="other", tags=["Evening"])
    _scanned_at(pg_session_factory, ["SPX-111", "LOOSE-1"], "2026-11-24T23:59:59.999+07:00")
    _scanned_at(pg_session_factory, ["251101BBB"], "2026-11-25T00:00+07:00")


def _scanned_at(pg_session_factory, labels, when):
    from sqlalchemy import update

    from src.models import OutboundItem

    with pg_session_factory() as db:
        db.execute(
            update(OutboundItem)
            .where(OutboundItem.content.in_(labels))
            .values(created_at=datetime.fromisoformat(when))
        )
        db.commit()


MON, TUE = date(2026, 11, 24), date(2026, 11, 25)


def test_days_group_by_scan_time_in_the_business_zone(pg_session_factory):
    """V2_ORDERS_DELTA C2 / Q53: the close time plays no part."""
    _seed_two_days(pg_session_factory)
    days, total = queries.get_day_history()
    assert total == 2
    assert days == [
        {"day": TUE, "outbound": 1, "orders_done": 1, "tags": ["Evening"]},
        {"day": MON, "outbound": 2, "orders_done": 1, "tags": ["Morning"]},
    ]
    assert [d["day"] for d in queries.get_day_history(limit=1, offset=1)[0]] == [MON]
    detail = queries.get_day(MON)
    assert {s.content for s in detail["scans"]} == {"SPX-111", "LOOSE-1"}
    assert [o.order_sn for o in detail["orders"]] == ["251101AAA"]
    queries.create_outbound_item(content="STILL-OPEN", owner_username="op", tags_in=[])
    assert queries.get_day_history()[1] == 2  # open scans are not history


def test_an_order_scanned_over_two_days_is_on_both(pg_session_factory):
    from src.models import ShopeeOrderInfo

    from .factories import add_user

    with pg_session_factory() as db:
        add_user(db, "op")
        add_order(db, "SPLIT", tracking="PKG-A")
        db.add(ShopeeOrderInfo(order_sn="SPLIT", package_number="P2", tracking_number="PKG-B"))
        add_order(db, "NOSCAN", done=True, done_at=datetime.fromisoformat("2026-11-25T06:00+07:00"))
        db.commit()
    _close(["PKG-A", "PKG-B"])
    _scanned_at(pg_session_factory, ["PKG-A"], "2026-11-24T12:00+07:00")
    _scanned_at(pg_session_factory, ["PKG-B"], "2026-11-25T12:00+07:00")
    counts = {d["day"]: (d["outbound"], d["orders_done"]) for d in queries.get_day_history()[0]}
    # NOSCAN has no scan, so it falls on the day it was done.
    assert counts == {MON: (1, 1), TUE: (1, 2)}
    assert {o.order_sn for o in queries.get_day(TUE)["orders"]} == {"SPLIT", "NOSCAN"}


def test_history_filters_by_days_and_by_close_time(pg_session_factory):
    _seed_two_days(pg_session_factory)
    monday = queries.HistoryFilter(day_to=MON)
    assert queries.get_outbound_history(f=monday)[1] == 2
    assert [o.order_sn for o in queries.get_shopee_orders_history(f=monday)[0]] == ["251101AAA"]
    assert [d["day"] for d in queries.get_day_history(f=monday)[0]] == [MON]
    tuesday = queries.HistoryFilter(day_from=TUE)
    assert [s.content for s in queries.get_outbound_history(f=tuesday)[0]] == ["251101BBB"]
    assert [d["day"] for d in queries.get_day_history(f=tuesday)[0]] == [TUE]

    # Close-time bounds are inclusive; a naive one is UTC.
    closed_at = min(s.closed_at for s in queries.get_outbound_history()[0])
    assert queries.get_outbound_history(f=queries.HistoryFilter(closed_to=closed_at))[1] == 2
    naive = closed_at.astimezone(UTC).replace(tzinfo=None)
    assert queries.get_outbound_history(f=queries.HistoryFilter(closed_to=naive))[1] == 2
    after = queries.HistoryFilter(closed_from=closed_at + timedelta(microseconds=1))
    assert [o.order_sn for o in queries.get_shopee_orders_history(f=after)[0]] == ["251101BBB"]


def test_history_search_runs_on_the_server(pg_session_factory):
    _seed_two_days(pg_session_factory)
    by_tag = queries.get_outbound_history(f=queries.HistoryFilter(q="evening"))
    assert [s.content for s in by_tag[0]] == ["251101BBB"]
    by_worker = queries.get_outbound_history(f=queries.HistoryFilter(q="OTHER"))
    assert by_worker[1] == 1
    by_tracking = queries.get_shopee_orders_history(f=queries.HistoryFilter(q="spx-1"))
    assert [o.order_sn for o in by_tracking[0]] == ["251101AAA"]
    # LIKE wildcards are matched literally.
    assert queries.get_outbound_history(f=queries.HistoryFilter(q="%"))[1] == 0


# V2_ORDERS_DELTA Q49: search over courier and buyer name, days with a match, exact lookup.


def test_order_search_matches_courier_and_recipient_name(pg_session_factory):
    from .factories import add_user

    with pg_session_factory() as db:
        add_user(db, "op")
        add_order(db, "251102CCC", carrier="J&T Express", recipient=True, tracking="JX-1")
        add_order(db, "251102DDD", carrier="SPX Express")
        db.commit()
    _close(["JX-1", "251102DDD"])
    by_courier = queries.get_shopee_orders_history(f=queries.HistoryFilter(q="j&t"))
    assert [o.order_sn for o in by_courier[0]] == ["251102CCC"]
    by_name = queries.get_shopee_orders_history(f=queries.HistoryFilter(q="synthetic name"))
    assert [o.order_sn for o in by_name[0]] == ["251102CCC"]


def test_day_search_keeps_days_with_a_match_and_their_full_counts(pg_session_factory):
    _seed_two_days(pg_session_factory)
    days, total = queries.get_day_history(f=queries.HistoryFilter(q="loose"))
    assert total == 1
    # The day is listed with all of it, not only the matching scan.
    assert (days[0]["day"], days[0]["outbound"], days[0]["orders_done"]) == (MON, 2, 1)
    by_order = queries.get_day_history(f=queries.HistoryFilter(q="251101bbb"))
    assert by_order[1] == 1 and by_order[0][0]["tags"] == ["Evening"]
    assert queries.get_day_history(f=queries.HistoryFilter(q="nothing-like-this"))[1] == 0


def test_lookup_finds_orders_and_scans_by_exact_label(pg_session_factory):
    _seed_two_days(pg_session_factory)
    queries.create_outbound_item(content="OPEN-9", owner_username="op", tags_in=[])

    found = queries.lookup_label(" SPX-111 ")
    assert [o.order_sn for o in found["orders"]] == ["251101AAA"]
    assert [(s.content, s.closed) for s in found["scans"]] == [("SPX-111", True)]
    assert found["day"] == MON
    assert queries.lookup_label("LOOSE-1")["day"] == MON
    by_sn = queries.lookup_label("251101AAA")  # an order found by SN; its scan was the tracking no.
    assert [o.order_sn for o in by_sn["orders"]] == ["251101AAA"] and by_sn["scans"] == []
    open_scan = queries.lookup_label("OPEN-9")
    assert open_scan["orders"] == [] and [s.closed for s in open_scan["scans"]] == [False]
    assert open_scan["day"] is None
    assert queries.lookup_label("spx-111") == {"orders": [], "scans": [], "day": None}  # Q57
    assert queries.lookup_label("SPX-11") == {
        "orders": [],
        "scans": [],
        "day": None,
    }  # exact, not substring
    assert queries.lookup_label("  ") == {"orders": [], "scans": [], "day": None}


def test_history_day_routes_over_http(pg_session_factory):
    from fastapi.testclient import TestClient

    from src.dependencies import require_admin
    from src.main import app
    from src.models import User

    _seed_two_days(pg_session_factory)
    app.dependency_overrides[require_admin] = lambda: User(username="a", scope="admin")
    try:
        client = TestClient(app)
        days = client.get("/admin/history/days", params={"day_to": "2026-11-24"})
        assert days.headers["X-Total-Count"] == "1"
        assert days.json() == [
            {"day": "2026-11-24", "outbound": 2, "orders_done": 1, "tags": ["Morning"]}
        ]
        day = client.get("/admin/history/days/2026-11-24").json()
        assert [o["order_sn"] for o in day["orders"]] == ["251101AAA"]
        assert {s["created_at"] for s in day["scans"]} == {"2026-11-24T16:59:59.999000Z"}
        assert client.get("/admin/history/days/yesterday").status_code == 422
        found = client.get("/admin/lookup", params={"label": "SPX-111"}).json()
        assert found["day"] == "2026-11-24"
        assert client.get("/admin/history/closes").status_code == 404
    finally:
        app.dependency_overrides.pop(require_admin)
