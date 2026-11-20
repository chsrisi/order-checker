"""T4.5: batched order payloads are bounded in queries and equal to the per-order expansion."""

from sqlalchemy import event, select

from scripts.seed_dev.seed import seed
from src.models import WarehouseItem
from src.services import queries, shopee_service


def _reference_components(order):
    """The pre-T4.5 per-order algorithm (shopee_service.build_shopee_order_response @ v0.4.0),
    kept here as an oracle on top of the unchanged per-node BOM queries."""

    def item_info(sku):
        with queries.get_db() as db:
            item = db.execute(
                select(WarehouseItem).filter(WarehouseItem.sku == sku)
            ).scalar_one_or_none()
            return (item.item_name, item.location) if item else (None, None)

    def flatten(node):
        if node.get("children"):
            return [leaf for child in node["children"] for leaf in flatten(child)]
        sku = node.get("sku", "")
        return [(sku, node.get("name", ""), node.get("quantity", 1), item_info(sku)[1])]

    totals = {}
    for raw in order.item_list or []:
        sku = raw.model_sku or raw.item_sku or ""
        shopee_id = raw.model_id or raw.item_id
        qty = raw.model_quantity_purchased or 1
        tree = queries.resolve_shopee_order_bom_tree(shopee_id, sku, qty)
        if tree:
            leaves = flatten(tree)
        else:
            name, loc = item_info(sku)
            leaves = [(sku, name or raw.item_name or sku, qty, loc)]
        for leaf_sku, name, q, loc in leaves:
            totals[(leaf_sku, name, loc)] = totals.get((leaf_sku, name, loc), 0) + q
    return [
        {"component_sku": s, "component_name": n, "quantity": q, "location": loc}
        for (s, n, loc), q in totals.items()
    ]


def _count_queries(engine, fn):
    count = 0

    def before(*_a, **_k):
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return result, count


def test_payload_matches_reference_and_fills_new_fields(pg_session_factory):
    seed()
    orders = queries.get_all_shopee_order_data()
    payloads = {p.order_sn: p for p in shopee_service.build_shopee_order_responses(orders)}

    assert len(payloads) == len(orders)  # no duplicate rows for split orders
    for order in orders:
        got = [c.model_dump() for c in payloads[order.order_sn].item_list]
        assert got == _reference_components(order), order.order_sn

    split = payloads["DEV0003"]
    assert split.split_up is True
    assert [i.tracking_number for i in split.info] == ["DEVTRK0003A", "DEVTRK0003B"]
    assert split.shipping_carrier == "Synthetic Express"
    # nested standard BOM: gift box -> cookie kit (2x flour, 1x sugar) + butter
    assert {c.component_sku for c in split.item_list} == {"Z90_001", "Z90_002", "Z90_003"}


def test_query_count_is_independent_of_order_count(pg_session_factory, pg_engine):
    seed()
    orders = queries.get_all_shopee_order_data()
    assert len(orders) >= 4

    _, few = _count_queries(
        pg_engine, lambda: shopee_service.build_shopee_order_responses(orders[:1])
    )
    _, many = _count_queries(pg_engine, lambda: shopee_service.build_shopee_order_responses(orders))
    assert many <= few + 2  # only extra BOM depth levels may add queries, never per order
    assert many <= 10
