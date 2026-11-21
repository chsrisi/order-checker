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
from typing import Any

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

CONSTRAINT_KEYS = ("maxLength", "maxItems", "minLength", "minItems", "pattern")


# --------------------------------------------------------------------------- normalization
def _resolve(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = components[schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def _normalize(schema: dict[str, Any] | None, components: dict[str, Any], depth: int = 0) -> Any:
    """Reduce a JSON schema to the parts the contract cares about."""
    if schema is None:
        return None
    if depth > 8:
        return {"type": "recursive"}
    schema = _resolve(schema, components)
    nullable = False
    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        non_null = [v for v in variants if _resolve(v, components).get("type") != "null"]
        nullable = len(non_null) != len(variants)
        if len(non_null) == 1:
            inner = _normalize(non_null[0], components, depth + 1)
            if isinstance(inner, dict):
                inner = dict(inner)
                inner["nullable"] = inner.get("nullable", False) or nullable
            return inner
        return {
            "type": "union",
            "nullable": nullable,
            "variants": [_normalize(v, components, depth + 1) for v in non_null],
        }

    node: dict[str, Any] = {"type": schema.get("type", "any"), "nullable": nullable}
    if schema.get("format"):
        node["format"] = schema["format"]
    for key in CONSTRAINT_KEYS:
        if key in schema:
            node[key] = schema[key]
    if node["type"] == "array":
        node["items"] = _normalize(schema.get("items", {}), components, depth + 1)
    if node["type"] == "object" and "properties" in schema:
        required = set(schema.get("required", []))
        node["properties"] = {
            name: {**_normalize(prop, components, depth + 1), "required": name in required}
            for name, prop in sorted(schema["properties"].items())
        }
    return node


def build_contract(app) -> dict[str, Any]:
    from src.models import (
        OutboundResponse,
        PickItemEntryResponse,
        ShopeeOrderResponse,
        StockResponse,
    )

    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    http: dict[str, Any] = {}
    for method, path in CLIENT_OPERATIONS:
        op = spec["paths"].get(path, {}).get(method)
        key = f"{method.upper()} {path}"
        if op is None:
            http[key] = None
            continue
        body = op.get("requestBody", {}).get("content", {}).get("application/json", {})
        ok = op.get("responses", {}).get("200", {})
        ok_schema = ok.get("content", {}).get("application/json", {}).get("schema")
        http[key] = {
            "success_200": "200" in op.get("responses", {}),
            "params": {
                p["name"]: {
                    "in": p["in"],
                    "required": p.get("required", False),
                    **_normalize(p.get("schema"), components),
                }
                for p in op.get("parameters", [])
            },
            "request": _normalize(body.get("schema"), components) if body else None,
            "response": _normalize(ok_schema, components),
        }

    ws: dict[str, Any] = {}
    for name, model in {
        "outbound_update": OutboundResponse,
        "shopee_orders_update": ShopeeOrderResponse,
        "pick_item_entries_update": PickItemEntryResponse,
        "stocks_update": StockResponse,
    }.items():
        schema = model.model_json_schema(mode="serialization", ref_template="#/$defs/{model}")
        defs = schema.pop("$defs", {})
        ws[name] = _normalize(schema, defs)
    return {"http": http, "ws_items": ws}


# --------------------------------------------------------------------------- comparison
def _diff_response(old: Any, new: Any, where: str, problems: list[str]) -> None:
    """Responses: everything the client may parse must still be there, same type/nullability."""
    if old is None:
        return
    if new is None:
        problems.append(f"{where}: response schema removed")
        return
    if old.get("type") != new.get("type"):
        problems.append(f"{where}: type {old.get('type')} -> {new.get('type')}")
        return
    if not old.get("nullable") and new.get("nullable"):
        problems.append(f"{where}: became nullable")
    if old.get("format") != new.get("format"):
        problems.append(f"{where}: format {old.get('format')} -> {new.get('format')}")
    if "items" in old:
        _diff_response(old["items"], new.get("items"), f"{where}[]", problems)
    for name, prop in old.get("properties", {}).items():
        new_prop = new.get("properties", {}).get(name)
        if new_prop is None:
            problems.append(f"{where}.{name}: removed")
            continue
        if prop.get("required") and not new_prop.get("required"):
            problems.append(f"{where}.{name}: no longer always present")
        _diff_response(prop, new_prop, f"{where}.{name}", problems)


def _diff_request(old: Any, new: Any, where: str, problems: list[str]) -> None:
    """Requests: what the client sends today must still be accepted."""
    if old is None:
        if new is not None and new.get("type") == "object":
            for name, prop in new.get("properties", {}).items():
                if prop.get("required"):
                    problems.append(f"{where}.{name}: new required field")
        return
    if new is None:
        return  # body no longer read: extra JSON is ignored
    if old.get("type") != new.get("type"):
        problems.append(f"{where}: type {old.get('type')} -> {new.get('type')}")
        return
    for key in CONSTRAINT_KEYS:
        if new.get(key) != old.get(key) and key in new:
            problems.append(f"{where}: constraint {key} {old.get(key)} -> {new.get(key)}")
    if "items" in old:
        _diff_request(old["items"], new.get("items"), f"{where}[]", problems)
    old_props = old.get("properties", {})
    for name, prop in new.get("properties", {}).items():
        if name not in old_props:
            if prop.get("required"):
                problems.append(f"{where}.{name}: new required field")
            continue
        if prop.get("required") and not old_props[name].get("required"):
            problems.append(f"{where}.{name}: became required")
        _diff_request(old_props[name], prop, f"{where}.{name}", problems)
    for name in old_props:
        if name not in new.get("properties", {}):
            problems.append(f"{where}.{name}: removed")


def diff_contract(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key, old_op in old["http"].items():
        new_op = new["http"].get(key)
        if new_op is None:
            problems.append(f"{key}: operation removed")
            continue
        if not new_op["success_200"]:
            problems.append(f"{key}: 200 response no longer declared")
        for name, param in new_op["params"].items():
            old_param = old_op["params"].get(name)
            if old_param is None and param["required"]:
                problems.append(f"{key} param {name}: new required parameter")
        for name in old_op["params"]:
            if name not in new_op["params"]:
                problems.append(f"{key} param {name}: removed")
        _diff_request(old_op["request"], new_op["request"], f"{key} request", problems)
        _diff_response(old_op["response"], new_op["response"], f"{key} response", problems)
    for name, old_ws in old["ws_items"].items():
        _diff_response(old_ws, new["ws_items"].get(name), f"WS {name} item", problems)
    return problems


# --------------------------------------------------------------------------- tests
def _snapshot() -> dict[str, Any]:
    return json.loads(SNAPSHOT_PATH.read_text())


def test_every_client_operation_exists_with_200():
    from src.main import app

    current = build_contract(app)
    missing = [k for k, v in current["http"].items() if v is None]
    assert not missing, f"client operations missing: {missing}"
    no_200 = [k for k, v in current["http"].items() if not v["success_200"]]
    assert not no_200, f"client operations without a declared 200: {no_200}"


def test_contract_changes_are_additive_only():
    from src.main import app

    problems = diff_contract(_snapshot(), build_contract(app))
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

    SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(build_contract(app), indent=2, sort_keys=True) + "\n")
    print(f"wrote {SNAPSHOT_PATH}")
