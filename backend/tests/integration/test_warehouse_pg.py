"""T1.3 / F-H3: scanned input is matched literally, never as a LIKE pattern."""

import pytest

from src.services import queries

from .factories import add_item


@pytest.fixture
def items(pg_session_factory):
    with pg_session_factory() as db:
        add_item(db, "A01X001", name="Other bin item")
        add_item(db, "B02_003", name="Flour 50% blend", supplier_barcode="SUP-777")
        db.commit()


def test_wildcards_in_scans_resolve_to_nothing(items):
    assert queries.resolve_barcode_to_item("%") is None
    assert queries.resolve_barcode_to_item("_") is None
    assert queries.resolve_barcode_to_item("A01%") is None


def test_underscore_sku_does_not_match_other_character(items):
    assert queries.resolve_barcode_to_item("A01_001") is None


def test_exact_matches_stay_case_insensitive(items):
    assert queries.resolve_barcode_to_item("b02_003").sku == "B02_003"
    assert queries.resolve_barcode_to_item("x-sup-777").sku == "B02_003"


def test_substring_search_escapes_wildcards(items):
    assert [i.sku for i in queries.find_warehouse_items("50%")] == ["B02_003"]
    assert [i.sku for i in queries.find_warehouse_items("%")] == ["B02_003"]  # literal %
    assert [i.sku for i in queries.find_warehouse_items("X_0")] == []  # _ is not a wildcard
    assert {i.sku for i in queries.find_warehouse_items("0")} == {"A01X001", "B02_003"}
