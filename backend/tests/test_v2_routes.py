"""``/v2`` operator-client surface and version gate (IMPLEMENTATION_PLAN T6.3, P-10, P-11)."""

from __future__ import annotations

import json

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src import config
from src.routers import v2
from src.services import client_releases


def _routes():
    from src.main import app
    from src.routers import auth, items, meta, outbound, pick_items, shopee, stocks

    v1 = [
        r
        for router in (auth, outbound, pick_items, shopee, items, stocks, meta)
        for r in router.router.routes
        if isinstance(r, APIRoute)
    ]
    v2_router = v2.build_v2_router(v1)
    return app, v1, [r for r in v2_router.routes if isinstance(r, APIRoute)]


def test_every_mirrored_operation_reuses_the_v1_handler():
    _, v1, v2_routes = _routes()
    by_key = {(m, r.path): r for r in v1 for m in r.methods}
    assert len(v2_routes) == len(v2.MIRRORED_OPERATIONS) + len(v2.UNGATED_OPERATIONS)
    for route in v2_routes:
        (method,) = route.methods
        twin = by_key[(method, route.path.removeprefix("/v2"))]
        assert route.endpoint is twin.endpoint
        assert route.response_model is twin.response_model
        assert route.tags == [f"v2 · {t}" for t in twin.tags]


def test_v2_does_not_mirror_registration_jwks_or_admin_operations():
    from src.main import app

    paths = {p for p in app.openapi()["paths"] if p.startswith("/v2")}
    assert "/v2/auth/register" not in paths
    assert "/v2/auth/admin" not in paths
    assert "/v2/.well-known/jwks.json" not in paths
    assert "/v2/outbound/close" not in paths
    assert not any(p.startswith("/v2/admin") for p in paths)


@pytest.fixture
def releases(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLIENT_RELEASES_DIR", str(tmp_path))

    def publish(**fields):
        (tmp_path / "latest.json").write_text(json.dumps({"version_code": 5, **fields}))

    return publish


@pytest.fixture
def client():
    from src.main import app

    return TestClient(app)


@pytest.mark.parametrize("header", [None, "", "abc", "-1", "1.5"])
def test_gate_rejects_missing_or_malformed_version(client, releases, header):
    headers = {} if header is None else {"X-Client-Version": header}
    response = client.get("/v2/items/find?query=x", headers=headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "X-Client-Version header required"}


def test_gate_answers_426_below_the_published_minimum(client, releases):
    releases(min_supported_version_code=3)
    response = client.get("/v2/items/find?query=x", headers={"X-Client-Version": "2"})
    assert response.status_code == 426
    assert response.json() == {
        "detail": "Client update required",
        "min_supported_version_code": 3,
    }


def test_gate_passes_at_or_above_the_minimum_and_without_a_release(client, releases):
    # The gate lets the request through; the missing bearer token answers next (401/403).
    assert client.get("/v2/items/find?query=x", headers={"X-Client-Version": "1"}).status_code in (
        401,
        403,
    )
    releases(min_supported_version_code=3)
    response = client.get("/v2/items/find?query=x", headers={"X-Client-Version": "3"})
    assert response.status_code in (401, 403)


def test_meta_is_exempt_from_the_gate(client, releases):
    releases(min_supported_version_code=99)
    response = client.get("/v2/meta")
    assert response.status_code == 200
    assert response.json()["client_contract"] == {"min": 1, "max": 2}


def test_v1_routes_are_never_gated(client, releases):
    releases(min_supported_version_code=99)
    assert client.get("/items/find?query=x").status_code in (401, 403)


def test_unreadable_release_metadata_means_no_minimum(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLIENT_RELEASES_DIR", str(tmp_path))
    (tmp_path / "latest.json").write_text("{not json")
    assert client_releases.latest() is None
    assert client_releases.min_supported_version_code() is None
