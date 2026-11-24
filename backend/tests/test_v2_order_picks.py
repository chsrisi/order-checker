"""T6.18: v2 order picks over HTTP, and order work closed to admins."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.models import User
from src.services import auth_service, pick_item_service, queries
from src.services.queries.pick_items import OrderLine

HEADERS = {"X-Client-Version": "1"}
PICKS = "/v2/shopee/orders/260101ORDER1/picks"
BODY = {"sku": "A01_001", "qty": 2}


@pytest.fixture
def client(monkeypatch):
    from src.main import app

    for name in ("send_to_user", "broadcast"):
        monkeypatch.setattr(pick_item_service.conn_mgr, name, AsyncMock())

    def login(scope="client"):
        app.dependency_overrides[auth_service.get_current_user] = lambda: User(
            username="op", password_hash="x", scope=scope
        )
        return TestClient(app)

    yield login
    app.dependency_overrides.pop(auth_service.get_current_user, None)


@pytest.mark.parametrize(
    "path, query", [(PICKS, "pick_for_order"), (f"{PICKS}/unassign", "unassign_from_order")]
)
def test_success_returns_the_line_and_notifies(client, monkeypatch, path, query):
    calls = []

    def fake(*args):
        calls.append(args)
        return OrderLine("260101ORDER1", "A01_001", 0, "Flour")

    monkeypatch.setattr(queries, query, fake)
    response = client().post(path, json=BODY, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {
        "order_sn": "260101ORDER1",
        "sku": "A01_001",
        "qty": 0,
        "item_name": "Flour",
    }
    assert calls == [("260101ORDER1", "A01_001", 2, "op")]
    assert pick_item_service.conn_mgr.send_to_user.await_count == 1
    assert pick_item_service.conn_mgr.broadcast.await_count == 2


@pytest.mark.parametrize(
    "error, status",
    [
        (LookupError("missing"), 404),
        (queries.OrderClosedError("closed"), 409),
        (queries.InsufficientStockError("short"), 409),
        (queries.PickQuantityError("too many"), 409),
    ],
)
@pytest.mark.parametrize(
    "suffix, query", [("", "pick_for_order"), ("/unassign", "unassign_from_order")]
)
def test_errors_keep_their_text_and_notify_nobody(
    client, monkeypatch, error, status, suffix, query
):
    def fail(*_):
        raise error

    monkeypatch.setattr(queries, query, fail)
    response = client().post(PICKS + suffix, json=BODY, headers=HEADERS)
    assert response.status_code == status
    assert response.json() == {"detail": str(error)}
    pick_item_service.conn_mgr.send_to_user.assert_not_awaited()


@pytest.mark.parametrize("body", [{"sku": "", "qty": 1}, {"sku": "A", "qty": 0}, {"sku": "A"}])
def test_invalid_bodies_are_422(client, body):
    assert client().post(PICKS, json=body, headers=HEADERS).status_code == 422
    assert client().post(f"{PICKS}/unassign", json=body, headers=HEADERS).status_code == 422


def test_the_version_gate_covers_picks(client):
    assert client().post(PICKS, json=BODY).status_code == 400


@pytest.mark.parametrize(
    "path, kwargs",
    [
        (PICKS, {"json": BODY}),
        (f"{PICKS}/unassign", {"json": BODY}),
        ("/v2/shopee/orders/acquire", {"params": {"order_sn": "260101ORDER1"}}),
        ("/v2/outbound", {"json": {"content": "label"}}),
    ],
)
def test_admins_cannot_work_on_orders_in_v2(client, path, kwargs):
    response = client("admin").post(path, headers=HEADERS, **kwargs)
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin accounts cannot work on orders"}


def test_v1_order_work_stays_open_to_admins(client, monkeypatch):
    """Q74: the root routes are untouched until v1 retires."""
    from src.routers import shopee

    monkeypatch.setattr(shopee.shopee_service, "acquire_order", AsyncMock())
    response = client("admin").post("/shopee/orders/acquire", params={"order_sn": "260101ORDER1"})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "method, path",
    [
        ("POST", "/v2/pick-items"),
        ("POST", "/v2/pick-items/1/assign"),
        ("POST", "/v2/pick-items/unassign"),
        ("DELETE", "/v2/pick-items/1"),
    ],
)
def test_v1_style_picks_left_v2(client, method, path):
    assert client().request(method, path, headers=HEADERS).status_code == 404


def test_meta_reports_strict_stock(client, monkeypatch):
    for value, expected in (("1", True), ("0", False)):
        monkeypatch.setenv("STOCK_STRICT", value)
        assert client().get("/v2/meta").json()["features"]["strict_stock"] is expected
