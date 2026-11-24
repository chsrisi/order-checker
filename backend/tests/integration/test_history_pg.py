"""T5.2: admin history is paginated newest-first with X-Total-Count."""

from datetime import UTC, datetime, timedelta

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


# Delta 9 (Q40/Q42): server-side filters and the list of closes.


def _close(labels, *, user="op", tags=()):
    for label in labels:
        queries.create_outbound_item(content=label, owner_username=user, tags_in=list(tags))
    return queries.close_outbound_items(contents=list(labels), admin_username="a")


def _seed_two_closes(pg_session_factory):
    from .factories import add_user

    with pg_session_factory() as db:
        add_user(db, "op")
        add_user(db, "other")
        add_order(db, "251101AAA", owner="op", tracking="SPX-111")
        add_order(db, "251101BBB", owner="other")
        db.commit()
    _close(["SPX-111", "LOOSE-1"], tags=["Morning"])
    first = queries.get_close_history()[0][0]["closed_at"]
    _close(["251101BBB"], user="other", tags=["Evening"])
    return first


def test_close_history_lists_one_row_per_close_with_counts_and_tags(pg_session_factory):
    _seed_two_closes(pg_session_factory)
    closes, total = queries.get_close_history()
    assert total == 2
    newest, oldest = closes
    assert newest["closed_at"] > oldest["closed_at"]
    # The order whose tracking number was scanned is completed by the first close.
    assert (oldest["outbound"], oldest["orders_done"], oldest["tags"]) == (2, 1, ["Morning"])
    assert (newest["outbound"], newest["orders_done"], newest["tags"]) == (1, 1, ["Evening"])


def test_history_filters_by_one_close_and_by_range(pg_session_factory):
    from datetime import timedelta

    first = _seed_two_closes(pg_session_factory)
    one = queries.HistoryFilter(closed_at=first)
    scans, total = queries.get_outbound_history(f=one)
    assert total == 2 and {s.content for s in scans} == {"SPX-111", "LOOSE-1"}
    orders, total = queries.get_shopee_orders_history(f=one)
    assert total == 1 and orders[0].order_sn == "251101AAA"

    # Range bounds are inclusive and aware times are converted to the naive UTC columns.
    aware = first.replace(tzinfo=UTC)
    until_first = queries.HistoryFilter(closed_to=aware)
    assert queries.get_outbound_history(f=until_first)[1] == 2
    after_first = queries.HistoryFilter(closed_from=aware + timedelta(microseconds=1))
    assert [o.order_sn for o in queries.get_shopee_orders_history(f=after_first)[0]] == [
        "251101BBB"
    ]
    assert queries.get_close_history(f=after_first)[1] == 1


def test_history_search_runs_on_the_server(pg_session_factory):
    _seed_two_closes(pg_session_factory)
    by_tag = queries.get_outbound_history(f=queries.HistoryFilter(q="evening"))
    assert [s.content for s in by_tag[0]] == ["251101BBB"]
    by_worker = queries.get_outbound_history(f=queries.HistoryFilter(q="OTHER"))
    assert by_worker[1] == 1
    by_tracking = queries.get_shopee_orders_history(f=queries.HistoryFilter(q="spx-1"))
    assert [o.order_sn for o in by_tracking[0]] == ["251101AAA"]
    # LIKE wildcards are matched literally.
    assert queries.get_outbound_history(f=queries.HistoryFilter(q="%"))[1] == 0


# V2_ORDERS_DELTA Q49: search over courier and buyer name, closes with a match, exact lookup.


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


def test_close_search_keeps_closes_with_a_match_and_their_full_counts(pg_session_factory):
    _seed_two_closes(pg_session_factory)
    closes, total = queries.get_close_history(f=queries.HistoryFilter(q="loose"))
    assert total == 1
    # The close is listed with all it closed, not only the matching scan.
    assert (closes[0]["outbound"], closes[0]["orders_done"]) == (2, 1)
    by_order = queries.get_close_history(f=queries.HistoryFilter(q="251101bbb"))
    assert by_order[1] == 1 and by_order[0][0]["tags"] == ["Evening"]
    assert queries.get_close_history(f=queries.HistoryFilter(q="nothing-like-this"))[1] == 0


def test_lookup_finds_orders_and_scans_by_exact_label_in_any_case(pg_session_factory):
    _seed_two_closes(pg_session_factory)
    queries.create_outbound_item(content="OPEN-9", owner_username="op", tags_in=[])

    found = queries.lookup_label(" spx-111 ")
    assert [o.order_sn for o in found["orders"]] == ["251101AAA"]
    assert [(s.content, s.closed) for s in found["scans"]] == [("SPX-111", True)]
    by_sn = queries.lookup_label("251101aaa")  # an order found by SN; its scan was the tracking no.
    assert [o.order_sn for o in by_sn["orders"]] == ["251101AAA"] and by_sn["scans"] == []
    open_scan = queries.lookup_label("open-9")
    assert open_scan["orders"] == [] and [s.closed for s in open_scan["scans"]] == [False]
    assert queries.lookup_label("SPX-11") == {"orders": [], "scans": []}  # exact, not substring
    assert queries.lookup_label("  ") == {"orders": [], "scans": []}
