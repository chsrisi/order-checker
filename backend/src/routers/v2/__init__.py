"""Operator-client contract v2 under ``/v2`` (V2-5, V2_DELTA D1, IMPLEMENTATION_PLAN T6.3).

The v2 surface mirrors the operations the v1 operator client calls, minus registration and
JWKS (P-11, Q11), plus ``/v2/meta``. Each operation is registered here one by one, **reusing
the v1 endpoint function and its OpenAPI metadata**, so the two contracts share handlers and
services (routers stay thin) and cannot drift apart by accident. Whole routers are not
re-included because they also hold admin operations.

Every gated operation requires ``X-Client-Version`` (the app's integer ``versionCode``):
missing or malformed → 400; below the published ``min_supported_version_code`` → 426, so the
app shows its update screen (P-10). ``/v2/meta`` and the OTA/device-registration endpoints are
exempt: a client that is too old must still find its update.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Header
from fastapi.routing import APIRoute

from ...exceptions import ClientUpgradeRequired, DomainException
from ...services import client_releases

V2_PREFIX = "/v2"

# (method, v1 path) mirrored at /v2<path>, gated by the client version.
MIRRORED_OPERATIONS: list[tuple[str, str]] = [
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/ws-token"),
    ("POST", "/outbound"),
    ("POST", "/pick-items"),
    ("POST", "/pick-items/{entry_id}/assign"),
    ("POST", "/pick-items/unassign"),
    ("DELETE", "/pick-items/{entry_id}"),
    ("GET", "/shopee/orders"),
    ("POST", "/shopee/orders/acquire"),
    ("GET", "/items/find"),
    ("POST", "/stocks/update"),
]

# Mirrored without the version gate.
UNGATED_OPERATIONS: list[tuple[str, str]] = [("GET", "/meta")]

GATE_RESPONSES = {
    400: {"description": "Missing or malformed X-Client-Version header"},
    426: {
        "description": (
            "Client update required: `{detail, min_supported_version_code}`; the app must "
            "update before it can continue"
        )
    },
}


def require_client_version(
    x_client_version: str | None = Header(
        None,
        alias="X-Client-Version",
        description="Required. The app's integer versionCode.",
    ),
) -> int:
    try:
        version = int(x_client_version or "")
    except ValueError:
        raise DomainException(status_code=400, detail="X-Client-Version header required")
    if version < 0:
        raise DomainException(status_code=400, detail="X-Client-Version header required")
    minimum = client_releases.min_supported_version_code()
    if minimum is not None and version < minimum:
        raise ClientUpgradeRequired(minimum)
    return version


def v2_tag(tag: str) -> str:
    return f"v2 · {tag}"


def _find_route(app_routes, method: str, path: str) -> APIRoute:
    for route in app_routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    raise LookupError(f"v1 operation {method} {path} not found; cannot mirror it under /v2")


def build_v2_router(app_routes) -> APIRouter:
    """Build the /v2 router from the v1 routes (each ``route.path`` includes its prefix)."""
    router = APIRouter(prefix=V2_PREFIX)
    for operations, gated in ((MIRRORED_OPERATIONS, True), (UNGATED_OPERATIONS, False)):
        for method, path in operations:
            src = _find_route(app_routes, method, path)
            responses = dict(src.responses)
            if gated:
                responses = {**GATE_RESPONSES, **responses}
            router.add_api_route(
                path,
                src.endpoint,
                methods=[method],
                response_model=src.response_model,
                status_code=src.status_code,
                summary=src.summary,
                description=src.description,
                responses=responses,
                tags=[v2_tag(t) for t in (src.tags or ["v2"])],
                dependencies=[Depends(require_client_version)] if gated else [],
                operation_id=None,
                name=f"v2_{src.name}",
            )
    return router


def include_v2(app: FastAPI, source_routers: list[APIRouter]) -> None:
    """Mount /v2, built from the v1 routers (FastAPI ≥ 0.139 keeps included routers wrapped,
    so the source routes are looked up there rather than in ``app.routes``)."""
    routes = [route for router in source_routers for route in router.routes]
    app.include_router(build_v2_router(routes))
