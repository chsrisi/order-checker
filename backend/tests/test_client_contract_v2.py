"""Operator client contract v2 (V2_SPEC §3, V2_DELTA D1, IMPLEMENTATION_PLAN T6.1/T6.3).

Contract v2 is served under ``/v2`` beside the frozen v1 root routes. It is **not frozen**, but
every change must be deliberate and coordinated with an app release, so it is guarded like v1:
the committed snapshot ``tests/contracts/client_v2.json`` may only grow additively unless it is
regenerated on purpose::

    cd backend && PYTHONPATH=. uv run python tests/test_client_contract_v2.py --write
"""

from __future__ import annotations

import sys
from pathlib import Path

from contract_harness import build_contract, diff_contract, load_snapshot, write_snapshot

SNAPSHOT_PATH = Path(__file__).parent / "contracts" / "client_v2.json"

# (method, path) of every HTTP operation the v2 operator client calls (filled by T6.3).
CLIENT_V2_OPERATIONS: list[tuple[str, str]] = []


def test_every_v2_operation_exists_with_200():
    from src.main import app

    current = build_contract(app, CLIENT_V2_OPERATIONS)
    missing = [k for k, v in current["http"].items() if v is None]
    assert not missing, f"v2 client operations missing: {missing}"
    no_200 = [k for k, v in current["http"].items() if not v["success_200"]]
    assert not no_200, f"v2 client operations without a declared 200: {no_200}"


def test_v2_contract_changes_are_additive_or_regenerated():
    from src.main import app

    problems = diff_contract(
        load_snapshot(SNAPSHOT_PATH), build_contract(app, CLIENT_V2_OPERATIONS)
    )
    assert not problems, (
        "Non-additive change to operator client contract v2. If deliberate (and coordinated with "
        "an app release), regenerate the snapshot:\n" + "\n".join(problems)
    )


def test_v2_snapshot_lists_exactly_the_declared_operations():
    """A new v2 operation must be added to the snapshot on purpose, not slip in unnoticed."""
    expected = {f"{m.upper()} {p}" for m, p in CLIENT_V2_OPERATIONS}
    assert set(load_snapshot(SNAPSHOT_PATH)["http"]) == expected


if __name__ == "__main__":
    if "--write" not in sys.argv:
        sys.exit("pass --write to regenerate the snapshot (deliberate contract change only)")
    from src.main import app

    write_snapshot(SNAPSHOT_PATH, build_contract(app, CLIENT_V2_OPERATIONS))
    print(f"wrote {SNAPSHOT_PATH}")
