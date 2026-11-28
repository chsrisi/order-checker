"""T9.1: the server's "Picked" rule for pick tasks (V2_TASKS_DELTA R1.3, R4.3)."""

from src.services.queries.tasks import is_picked


def test_picked_needs_every_required_sku_exactly():
    required = {"A": 5, "B": 2}
    assert is_picked(required, {"A": 5, "B": 2})
    assert not is_picked(required, {"A": 5, "B": 1})
    assert not is_picked(required, {"A": 6, "B": 2})  # over-picked
    assert not is_picked(required, {"A": 5})


def test_picked_ignores_zero_lines_and_refuses_extras_and_empty_tasks():
    assert is_picked({"A": 1}, {"A": 1, "B": 0})
    assert not is_picked({"A": 1}, {"A": 1, "B": 1})
    assert not is_picked({}, {})
