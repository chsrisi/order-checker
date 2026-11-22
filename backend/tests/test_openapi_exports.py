"""Committed OpenAPI exports per surface (V2_DELTA Q14, IMPLEMENTATION_PLAN T6.1).

``backend/openapi/v2.json`` (the ``/v2`` operator-client surface) and
``backend/openapi/admin.json`` (what the admin apps call) are the sources for the generated
Kotlin and TypeScript types. Production keeps ``/openapi.json`` switched off, so the files are
generated from ``app.openapi()`` and must match it. Regenerate after a deliberate API change::

    cd backend && PYTHONPATH=. uv run python tests/test_openapi_exports.py --write
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

EXPORT_DIR = Path(__file__).resolve().parent.parent / "openapi"

# Root paths the admin apps call besides everything under /admin (frontend/admin/lib).
ADMIN_ROOT_PATHS = {
    "/auth/admin",
    "/auth/refresh",
    "/auth/logout",
    "/auth/ws-token",
    "/.well-known/jwks.json",
    "/items/find",
    "/outbound/close",
    "/shopee/orders",
    "/shopee/reset-cache-state",
    "/meta",
}


def _is_v2(path: str) -> bool:
    return path == "/v2" or path.startswith("/v2/")


def _is_admin(path: str) -> bool:
    return path.startswith("/admin/") or path in ADMIN_ROOT_PATHS


SURFACES = {"v2.json": _is_v2, "admin.json": _is_admin}


def _refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs(value, found)


def export_surface(spec: dict[str, Any], keep) -> dict[str, Any]:
    """The spec reduced to the selected paths and the component schemas they reach."""
    paths = {p: copy.deepcopy(item) for p, item in spec["paths"].items() if keep(p)}
    schemas = spec.get("components", {}).get("schemas", {})
    needed: set[str] = set()
    _refs(paths, needed)
    pending = list(needed)
    while pending:
        name = pending.pop()
        inner: set[str] = set()
        _refs(schemas.get(name, {}), inner)
        for extra in inner - needed:
            needed.add(extra)
            pending.append(extra)
    components: dict[str, Any] = {
        "schemas": {n: schemas[n] for n in sorted(needed) if n in schemas}
    }
    if "securitySchemes" in spec.get("components", {}):
        components["securitySchemes"] = spec["components"]["securitySchemes"]
    info = {k: v for k, v in spec["info"].items() if k != "version"}  # no churn on version bumps
    return {"openapi": spec["openapi"], "info": info, "paths": paths, "components": components}


def render(spec: dict[str, Any], keep) -> str:
    return json.dumps(export_surface(spec, keep), indent=2, sort_keys=True) + "\n"


def test_exports_match_the_app():
    from src.main import app

    spec = app.openapi()
    stale = [
        name
        for name, keep in SURFACES.items()
        if not (EXPORT_DIR / name).exists() or (EXPORT_DIR / name).read_text() != render(spec, keep)
    ]
    assert not stale, (
        f"OpenAPI exports out of date: {stale}. Regenerate with "
        "`PYTHONPATH=. uv run python tests/test_openapi_exports.py --write`"
    )


def test_admin_export_covers_admin_paths_only():
    exported = json.loads((EXPORT_DIR / "admin.json").read_text())["paths"]
    assert "/admin/users" in exported and "/auth/admin" in exported
    assert not any(_is_v2(p) for p in exported)
    assert "/auth/register" not in exported


def test_export_keeps_referenced_schemas_only():
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": {"/v2/a": {"get": {"responses": {"200": {"$ref": "#/components/schemas/A"}}}}},
        "components": {
            "schemas": {
                "A": {"properties": {"b": {"$ref": "#/components/schemas/B"}}},
                "B": {},
                "Unused": {},
            }
        },
    }
    out = export_surface(spec, _is_v2)
    assert set(out["components"]["schemas"]) == {"A", "B"}
    assert "version" not in out["info"]


if __name__ == "__main__":
    if "--write" not in sys.argv:
        sys.exit("pass --write to regenerate the exports (deliberate API change only)")
    from src.main import app

    spec = app.openapi()
    EXPORT_DIR.mkdir(exist_ok=True)
    for name, keep in SURFACES.items():
        (EXPORT_DIR / name).write_text(render(spec, keep))
        print(f"wrote {EXPORT_DIR / name}")
