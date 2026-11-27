"""T9.2: task flows end to end over HTTP, on PostgreSQL, in both location modes."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.models import BOMDetail, BOMHeader, ShopeeOrderItemList, Task, User
from src.services import auth_service

from .factories import add_item, add_order, add_stock, add_user

V2 = {"X-Client-Version": "1"}
FLOUR, SUGAR, BUNDLE = "A01_001", "A01_002", "B01_001"


@pytest.fixture(params=["multi", "single"])
def mode(request, monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", request.param)
    monkeypatch.setenv("STOCK_STRICT", "0")
    return request.param


@pytest.fixture
def db(pg_session_factory):
    with pg_session_factory() as s:
        add_user(s, "eko")
        add_user(s, "boss", scope="admin")
        add_item(s, FLOUR, name="Flour")
        add_item(s, SUGAR, name="Sugar")
        add_item(s, BUNDLE, name="Cake kit")
        add_stock(s, FLOUR, 20, "A1")
        add_stock(s, SUGAR, 10, "A2")
        header = BOMHeader(sku=BUNDLE, quantity_standard=1)
        s.add(header)
        s.flush()
        s.add(BOMDetail(bom_header_id=header.id, component_sku=FLOUR, quantity_standard=2))
        s.add(BOMDetail(bom_header_id=header.id, component_sku=SUGAR, quantity_standard=1))
        s.commit()
    return pg_session_factory


@pytest.fixture
def as_user():
    """Log in as one user for the requests that follow (the override is app-wide)."""
    from src.main import app

    def login(username):
        scope = "admin" if username == "boss" else "client"
        app.dependency_overrides[auth_service.get_current_user] = lambda: User(
            username=username, password_hash="x", scope=scope
        )
        return TestClient(app)

    yield login
    app.dependency_overrides.pop(auth_service.get_current_user, None)


def test_a_pick_task_from_creation_to_done(db, mode, as_user):
    created = as_user("boss").post(
        "/admin/tasks/pick",
        json={"lines": [{"sku": BUNDLE, "qty": 1}], "assigned_to": "eko", "reference": "Toko"},
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]

    worker = as_user("eko")
    (mine,) = worker.get("/v2/tasks", headers=V2).json()["tasks"]
    leaves = {
        line["sku"]: (line["qty"], line["picked"])
        for line in mine["lines"]
        if line["kind"] == "leaf"
    }
    assert leaves == {FLOUR: (2, 0), SUGAR: (1, 0)}
    assert (mine["reference"], mine["in_progress"]) == ("Toko", False)

    first = worker.post(f"/v2/tasks/{task_id}/picks", json={"sku": FLOUR, "qty": 2}, headers=V2)
    assert first.json()["status"] == "open"
    assert worker.get("/v2/tasks", headers=V2).json()["tasks"][0]["in_progress"] is True
    last = worker.post(f"/v2/tasks/{task_id}/picks", json={"sku": SUGAR, "qty": 1}, headers=V2)
    assert last.json() == {
        "task_id": task_id,
        "sku": SUGAR,
        "qty": 1,
        "required": 1,
        "item_name": "Sugar",
        "status": "done",
    }

    assert worker.get("/v2/tasks", headers=V2).json()["tasks"] == []
    detail = as_user("boss").get(f"/admin/tasks/{task_id}").json()
    assert detail["status"] == "done"
    assert [(r["sku"], r["reason"], r["delta"]) for r in detail["stock_log"]] == [
        (FLOUR, "pick", -2),
        (SUGAR, "pick", -1),
    ]


def test_a_blind_count_and_its_difference_in_the_console(db, mode, as_user):
    body = {"sku": FLOUR, "assigned_to": "eko"}
    if mode == "multi":
        body["location"] = "A1"
    task_id = as_user("boss").post("/admin/tasks/count", json=body).json()["id"]

    worker = as_user("eko")
    (mine,) = worker.get("/v2/tasks", headers=V2).json()["tasks"]
    assert mine["current_location"] == "A1"
    # blind (T6): nothing in the worker's payload carries the recorded quantity
    assert "recorded_before" not in mine and "difference" not in mine
    assert (mine["lines"][0]["qty"], mine["lines"][0]["counted_qty"]) == (None, None)

    wrong = worker.post(
        f"/v2/tasks/{task_id}/count", json={"sku": SUGAR, "qty": 1, "location": "A1"}, headers=V2
    )
    assert wrong.status_code == 409
    done = worker.post(
        f"/v2/tasks/{task_id}/count", json={"sku": FLOUR, "qty": 17, "location": "A1"}, headers=V2
    )
    assert done.json()["status"] == "done"

    detail = as_user("boss").get(f"/admin/tasks/{task_id}").json()
    assert (detail["recorded_before"], detail["difference"]) == (20, -3)
    assert detail["lines"][0]["counted_qty"] == 17


def test_cant_finish_then_the_admin_closes_it_as_picked(db, mode, as_user):
    task_id = (
        as_user("boss")
        .post("/admin/tasks/pick", json={"lines": [{"sku": SUGAR, "qty": 5}], "assigned_to": "eko"})
        .json()["id"]
    )
    worker = as_user("eko")
    worker.post(f"/v2/tasks/{task_id}/picks", json={"sku": SUGAR, "qty": 3}, headers=V2)
    blocked = worker.post(f"/v2/tasks/{task_id}/block", json={"reason": "only 3"}, headers=V2)
    assert blocked.json()["status"] == "blocked"
    assert worker.get("/v2/tasks", headers=V2).json()["tasks"][0]["blocked_reason"] == "only 3"

    admin = as_user("boss")
    assert admin.post(f"/admin/tasks/{task_id}/close").json()["status"] == "done"
    assert admin.post(f"/admin/tasks/{task_id}/cancel", json={}).status_code == 409


def test_claimed_orders_are_tasks_until_picked(db, mode, as_user):
    with db() as s:
        add_order(s, "260101ORDER1", owner="eko")
        s.add(
            ShopeeOrderItemList(
                order_sn="260101ORDER1", model_sku=BUNDLE, model_quantity_purchased=1
            )
        )
        add_order(s, "260101ORDER2")  # not claimed: not a task
        s.commit()
    worker = as_user("eko")

    (order,) = worker.get("/v2/tasks", headers=V2).json()["order_tasks"]
    assert (order["order_sn"], order["state"], order["done_skus"], order["required_skus"]) == (
        "260101ORDER1",
        "not_started",
        0,
        2,
    )
    picks = "/v2/shopee/orders/260101ORDER1/picks"
    worker.post(picks, json={"sku": FLOUR, "qty": 2}, headers=V2)
    (admin_view,) = as_user("boss").get("/admin/order-tasks?assigned_to=eko").json()
    assert (admin_view["owner_user"], admin_view["state"], admin_view["done_skus"]) == (
        "eko",
        "partial",
        1,
    )

    worker = as_user("eko")  # the login override is app-wide
    worker.post(picks, json={"sku": SUGAR, "qty": 1}, headers=V2)
    final = worker.get("/v2/tasks", headers=V2)
    assert final.status_code == 200, final.text
    assert final.json()["order_tasks"] == []
    assert as_user("boss").get("/admin/order-tasks").json() == []


def test_the_default_admin_list_drops_tasks_closed_over_a_week_ago(db, mode, as_user):
    admin = as_user("boss")
    lines = {"lines": [{"sku": SUGAR, "qty": 1}], "assigned_to": "eko"}
    old, recent, open_ = (
        admin.post("/admin/tasks/pick", json=lines).json()["id"] for _ in range(3)
    )
    for task_id in (old, recent):
        admin.post(f"/admin/tasks/{task_id}/cancel", json={})
    with db() as s:
        s.get(Task, old).closed_at = datetime.now(UTC) - timedelta(days=8)
        s.commit()

    assert [t["id"] for t in admin.get("/admin/tasks").json()] == [recent, open_]
    cancelled = admin.get("/admin/tasks?status=cancelled").json()
    assert [t["id"] for t in cancelled] == [old, recent]
