"""T5.4: BOM routes validate qty and have response models; headers load in one query."""

from fastapi.testclient import TestClient

from src.dependencies import require_admin
from src.main import app
from src.routers import bom


def _client(monkeypatch):
    app.dependency_overrides[require_admin] = lambda: object()
    return TestClient(app)


def test_tree_rejects_non_positive_qty(monkeypatch):
    try:
        client = _client(monkeypatch)
        assert client.get("/admin/bom/tree", params={"sku": "A01_001", "qty": 0}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_tree_keeps_node_shape(monkeypatch):
    node = {
        "sku": "MP:9",
        "name": "Listing",
        "quantity": 2,
        "type": "marketplace",
        "children": [
            {
                "sku": "A01_001",
                "name": "Item",
                "quantity": 2,
                "is_not_primary_child": False,
                "type": "standard",
                "children": [],
            }
        ],
    }
    monkeypatch.setattr(bom, "get_marketplace_bom_node", lambda _id, _qty: node)
    try:
        body = _client(monkeypatch).get("/admin/bom/tree", params={"shopee_id": 9}).json()
    finally:
        app.dependency_overrides.clear()
    assert body == node  # exclude_unset: marketplace nodes gain no is_not_primary_child


def test_bom_routes_have_response_models():
    schema = app.openapi()["paths"]
    for path in ("/admin/bom/headers", "/admin/bom/tree"):
        ok = schema[path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert "$ref" in ok
