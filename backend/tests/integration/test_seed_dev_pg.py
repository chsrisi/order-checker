"""T3.2: synthetic seed tooling works on a migrated database and refuses production."""

import pytest

from scripts.seed_dev.seed import PICKING, SeedRefused, remove_seed, seed, seed_picking
from src import config
from src.services import queries


def test_seed_is_idempotent_and_exercises_active_orders(pg_session_factory):
    first = seed()
    assert first == {"users": 2, "items": 5, "boms": 5, "stocks": 3, "orders": 8}
    assert set(seed().values()) == {0}  # second run adds nothing

    active = {o.order_sn for o in queries.get_all_shopee_order_data()}
    # DEV0006 is past its ship-by: late, but still ongoing (V2_ORDERS_DELTA F4).
    assert active == {"DEV0001", "DEV0002", "DEV0003", "DEV0005", "DEV0006"}
    assert {o.order_sn for o in queries.get_shopee_order_data("dev_op1")} == {"DEV0002"}
    assert queries.resolve_barcode_to_item("X-SUP9001-A").sku == "Z90_001"


def test_single_mode_layout_and_reset(pg_session_factory):
    seed(stock_mode="single")
    removed = remove_seed()
    assert removed["orders"] == 8 and removed["items"] == 5 and removed["stocks"] == 2
    assert seed(stock_mode="multi")["orders"] == 8


def test_picking_scenario_is_idempotent_scannable_and_removable(pg_session_factory):
    seed()
    assert seed_picking() == len(PICKING) and seed_picking() == 0
    mine = {o.order_sn for o in queries.get_shopee_order_data("dev_op1")}
    picking = {sn for sn in mine if sn.startswith("991231")}
    # 01 is unclaimed, 07 cancelled and 08 done: not in the operator's list
    assert picking == {f"991231DEVPK0{n}" for n in (2, 3, 4, 5, 6)}
    assert queries.count_unassigned_picks() == 1
    queries.unassign_from_order("991231DEVPK05", "Z90_003", 1, "dev_op1")  # its shortfall
    removed = remove_seed()
    assert removed["orders"] == 8 + len(PICKING)
    assert queries.get_pie_data() == []


def test_release_script_counts_then_releases(pg_session_factory, capsys):
    from scripts.release_unassigned_picks import main

    seed()
    seed_picking()
    assert main([]) == 2
    assert "1 unassigned" in capsys.readouterr().out
    assert queries.count_unassigned_picks() == 1  # a dry run changes nothing
    assert main(["--confirm"]) == 0
    assert queries.count_unassigned_picks() == 0


def test_seed_refuses_under_production_rules(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_RULES", True)
    monkeypatch.setattr(config, "APP_ENV", "production")
    with pytest.raises(SeedRefused):
        seed()
    with pytest.raises(SeedRefused):
        seed_picking()
    with pytest.raises(SeedRefused):
        remove_seed()
