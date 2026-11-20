"""T3.2: synthetic seed tooling works on a migrated database and refuses production."""

import pytest

from scripts.seed_dev.seed import SeedRefused, remove_seed, seed
from src import config
from src.services import queries


def test_seed_is_idempotent_and_exercises_active_orders(pg_session_factory):
    first = seed()
    assert first == {"users": 2, "items": 5, "boms": 5, "stocks": 3, "orders": 8}
    assert set(seed().values()) == {0}  # second run adds nothing

    active = {o.order_sn for o in queries.get_all_shopee_order_data()}
    assert active == {"DEV0001", "DEV0002", "DEV0003", "DEV0005"}
    assert {o.order_sn for o in queries.get_shopee_order_data("dev_op1")} == {"DEV0002"}
    assert queries.resolve_barcode_to_item("X-SUP9001-A").sku == "Z90_001"


def test_single_mode_layout_and_reset(pg_session_factory):
    seed(stock_mode="single")
    removed = remove_seed()
    assert removed["orders"] == 8 and removed["items"] == 5 and removed["stocks"] == 2
    assert seed(stock_mode="multi")["orders"] == 8


def test_seed_refuses_under_production_rules(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_RULES", True)
    monkeypatch.setattr(config, "APP_ENV", "production")
    with pytest.raises(SeedRefused):
        seed()
    with pytest.raises(SeedRefused):
        remove_seed()
