"""Operator client contract v1 (KNOWN_LIMITATIONS.md #8, docs/SYSTEM_REFERENCE.md §10).

The operator client is updated manually, so everything it relies on is frozen. This module
turns that contract into tests:

* every HTTP operation the client calls still exists, with the same method and a declared
  ``200`` success response;
* request and response schemas only change *additively* compared to the committed snapshot
  ``tests/contracts/client_v1.json`` (new optional fields are fine; removals, renames, type
  changes, new required request fields, new nullability on required response fields, or new
  length limits are not);
* the WebSocket shape rules: client-scope payloads are lists of objects, every frame's
  ``data`` is a list, and a bad ticket is rejected with an HTTP 403 handshake.

Regenerate the snapshot only for a deliberate, reviewed contract change::

    cd backend && PYTHONPATH=. uv run python tests/test_client_contract_v1.py --write
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from contract_harness import build_contract, diff_contract, load_snapshot, write_snapshot

SNAPSHOT_PATH = Path(__file__).parent / "contracts" / "client_v1.json"

# (method, path) of every HTTP operation the operator client calls.
CLIENT_OPERATIONS: list[tuple[str, str]] = [
    ("post", "/auth/login"),
    ("post", "/auth/register"),
    ("post", "/auth/refresh"),
    ("post", "/auth/logout"),
    ("post", "/auth/ws-token"),
    ("get", "/.well-known/jwks.json"),
    ("post", "/outbound"),
    ("post", "/pick-items"),
    ("post", "/pick-items/{entry_id}/assign"),
    ("post", "/pick-items/unassign"),
    ("delete", "/pick-items/{entry_id}"),
    ("post", "/shopee/orders/acquire"),
    ("get", "/shopee/orders"),
    ("get", "/items/find"),
    ("post", "/stocks/update"),
]


# --------------------------------------------------------------------------- tests
def _snapshot() -> dict:
    return load_snapshot(SNAPSHOT_PATH)


def test_every_client_operation_exists_with_200():
    from src.main import app

    current = build_contract(app, CLIENT_OPERATIONS)
    missing = [k for k, v in current["http"].items() if v is None]
    assert not missing, f"client operations missing: {missing}"
    no_200 = [k for k, v in current["http"].items() if not v["success_200"]]
    assert not no_200, f"client operations without a declared 200: {no_200}"


def test_contract_changes_are_additive_only():
    from src.main import app

    problems = diff_contract(_snapshot(), build_contract(app, CLIENT_OPERATIONS))
    assert not problems, "Breaking change to operator client contract v1:\n" + "\n".join(problems)


def test_diff_detects_breaking_changes():
    """Guard the guard: the comparison must flag the changes it is meant to catch."""
    old = {
        "http": {
            "POST /x": {
                "success_200": True,
                "params": {"q": {"in": "query", "required": False, "type": "string"}},
                "request": {
                    "type": "object",
                    "nullable": False,
                    "properties": {"a": {"type": "string", "nullable": False, "required": True}},
                },
                "response": {
                    "type": "object",
                    "nullable": False,
                    "properties": {"id": {"type": "integer", "nullable": False, "required": True}},
                },
            }
        },
        "ws_items": {},
    }
    new = json.loads(json.dumps(old))
    new["http"]["POST /x"]["request"]["properties"]["b"] = {
        "type": "string",
        "nullable": False,
        "required": True,
    }
    new["http"]["POST /x"]["request"]["properties"]["a"]["maxLength"] = 5
    new["http"]["POST /x"]["response"]["properties"]["id"]["nullable"] = True
    del new["http"]["POST /x"]["params"]["q"]
    problems = "\n".join(diff_contract(old, new))
    assert "new required field" in problems
    assert "constraint maxLength" in problems
    assert "became nullable" in problems
    assert "param q: removed" in problems
    assert diff_contract(old, old) == []


if __name__ == "__main__":
    if "--write" not in sys.argv:
        sys.exit("pass --write to regenerate the snapshot (deliberate contract change only)")
    from src.main import app

    write_snapshot(SNAPSHOT_PATH, build_contract(app, CLIENT_OPERATIONS))
    print(f"wrote {SNAPSHOT_PATH}")
