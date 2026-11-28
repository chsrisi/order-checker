"""T9.2: task routes over HTTP (error mapping, access, events) and tasks_update delivery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.models import User, WSMessageType
from src.services import auth_service, queries, task_service
from src.services.managers.connection_manager import ConnectionManager
from src.services.queries import tasks as task_queries

HEADERS = {"X-Client-Version": "1"}
PICK = {"sku": "A01_001", "qty": 2}


@pytest.fixture
def client(monkeypatch):
    from src.main import app

    for name in ("send_to_user", "broadcast"):
        monkeypatch.setattr(task_service.conn_mgr, name, AsyncMock())
    monkeypatch.setattr(task_service, "_one", AsyncMock(return_value=_response()))

    def login(scope="client", username="eko"):
        app.dependency_overrides[auth_service.get_current_user] = lambda: User(
            username=username, password_hash="x", scope=scope
        )
        return TestClient(app)

    yield login
    app.dependency_overrides.pop(auth_service.get_current_user, None)


def _response():
    return {
        "id": 7,
        "type": "pick",
        "status": "open",
        "in_progress": False,
        "assigned_to": "eko",
        "assigned_name": "eko",
        "created_by": "boss",
        "created_at": "2026-11-27T10:00:00Z",
        "lines": [],
    }


def _task(assigned_to="eko"):
    return SimpleNamespace(id=7, assigned_to=assigned_to)


def _pick_result(status="open"):
    return task_queries.PickResult(7, "A01_001", 2, 5, "Flour", status)


WORKER_CALLS = [
    ("/v2/tasks/7/picks", PICK, "pick_for_task"),
    ("/v2/tasks/7/picks/unassign", PICK, "unassign_from_task"),
    ("/v2/tasks/7/count", {"sku": "A01_001", "qty": 3, "location": "A1"}, "count_task"),
    ("/v2/tasks/7/block", {"reason": "only 3 on the shelf"}, "block_task"),
]


@pytest.mark.parametrize("path, body, query", WORKER_CALLS)
def test_worker_calls_reach_the_query_as_the_caller_and_notify_v2_only(
    client, monkeypatch, path, body, query
):
    calls = []

    def fake(*args):
        calls.append(args)
        return _pick_result() if "picks" in path else _task()

    monkeypatch.setattr(task_queries, query, fake)
    response = client().post(path, json=body, headers=HEADERS)

    assert response.status_code == 200, response.text
    assert calls and calls[0][:2] == (7, "eko")
    task_service.conn_mgr.send_to_user.assert_awaited_with(
        WSMessageType.TASKS, username="eko", min_contract=2
    )
    task_service.conn_mgr.broadcast.assert_any_await(WSMessageType.TASKS, scope="admin")


def test_a_pick_returns_the_line_and_the_task_status(client, monkeypatch):
    monkeypatch.setattr(task_queries, "pick_for_task", lambda *_: _pick_result("done"))

    response = client().post("/v2/tasks/7/picks", json=PICK, headers=HEADERS)

    assert response.json() == {
        "task_id": 7,
        "sku": "A01_001",
        "qty": 2,
        "required": 5,
        "item_name": "Flour",
        "status": "done",
    }
    task_service.conn_mgr.broadcast.assert_any_await(WSMessageType.STOCKS)


@pytest.mark.parametrize(
    "error, status",
    [
        (LookupError("Task not found or not assigned to you"), 404),
        (task_queries.TaskStateError("Task is done"), 409),
        (task_queries.TaskScanError("Wrong item"), 409),
        (task_queries.PickQuantityError("Only 1 picked"), 409),
        (queries.InsufficientStockError("short"), 409),
        (ValueError("A reason is required"), 400),
    ],
)
@pytest.mark.parametrize("path, body, query", WORKER_CALLS)
def test_worker_errors_keep_their_text_and_notify_nobody(
    client, monkeypatch, error, status, path, body, query
):
    def fail(*_):
        raise error

    monkeypatch.setattr(task_queries, query, fail)
    response = client().post(path, json=body, headers=HEADERS)

    assert response.status_code == status
    assert response.json() == {"detail": str(error)}
    task_service.conn_mgr.send_to_user.assert_not_awaited()
    task_service.conn_mgr.broadcast.assert_not_awaited()


@pytest.mark.parametrize("path, body, _", WORKER_CALLS)
def test_admins_are_refused_on_v2_tasks(client, path, body, _):
    admin = client(scope="admin", username="boss")
    assert admin.post(path, json=body, headers=HEADERS).status_code == 403
    assert admin.get("/v2/tasks", headers=HEADERS).status_code == 403


def test_v2_tasks_are_behind_the_version_gate(client):
    assert client().get("/v2/tasks").status_code == 400
    assert client().post("/v2/tasks/7/picks", json=PICK).status_code == 400


@pytest.mark.parametrize(
    "path, body",
    [
        ("/v2/tasks/7/picks", {"sku": "A", "qty": 0}),
        ("/v2/tasks/7/count", {"sku": "A", "qty": -1}),
        ("/v2/tasks/7/block", {"reason": ""}),
        ("/v2/tasks/0/block", {"reason": "x"}),
    ],
)
def test_invalid_worker_bodies_are_422(client, path, body):
    assert client().post(path, json=body, headers=HEADERS).status_code == 422


ADMIN_CALLS = [
    ("/admin/tasks/count", {"sku": "A01_001", "assigned_to": "eko"}, "create_count_task"),
    (
        "/admin/tasks/pick",
        {"lines": [{"sku": "B01_001", "qty": 2}], "assigned_to": "eko", "reference": "Toko"},
        "create_pick_task",
    ),
    ("/admin/tasks/7/cancel", {"return_stock": False}, "cancel_task"),
    ("/admin/tasks/7/reassign", {"assigned_to": "ani"}, "reassign_task"),
    ("/admin/tasks/7/close", None, "close_as_picked"),
]


@pytest.mark.parametrize("path, body, query", ADMIN_CALLS)
def test_admin_calls_run_as_the_admin_and_notify_the_worker(client, monkeypatch, path, body, query):
    calls = []

    def fake(*args):
        calls.append(args)
        return _task("ani" if "reassign" in path else "eko")

    monkeypatch.setattr(task_queries, query, fake)
    monkeypatch.setattr(task_queries, "get_task", lambda _: _task("eko"))

    response = client(scope="admin", username="boss").post(path, json=body)

    assert response.status_code == 200, response.text
    assert "boss" in calls[0]
    notified = [c.kwargs["username"] for c in task_service.conn_mgr.send_to_user.await_args_list]
    assert notified == (["eko", "ani"] if "reassign" in path else ["eko"])


def test_cancel_defaults_to_returning_stock(client, monkeypatch):
    calls = []
    monkeypatch.setattr(task_queries, "cancel_task", lambda *a: calls.append(a) or _task())

    client(scope="admin", username="boss").post("/admin/tasks/7/cancel", json={})

    assert calls == [(7, "boss", True)]
    task_service.conn_mgr.broadcast.assert_any_await(WSMessageType.STOCKS)


@pytest.mark.parametrize("path, body, _", ADMIN_CALLS)
def test_operators_are_refused_on_admin_tasks(client, path, body, _):
    assert client().post(path, json=body).status_code == 403
    assert client().get("/admin/tasks").status_code == 403
    assert client().get("/admin/order-tasks").status_code == 403


def test_admin_list_passes_its_filters(client, monkeypatch):
    calls = []
    monkeypatch.setattr(task_service, "admin_tasks", lambda *a: calls.append(a) or [])

    response = client(scope="admin").get(
        "/admin/tasks?assigned_to=eko&type=pick&status=open&status=blocked"
    )

    assert response.status_code == 200
    assert calls == [("eko", "pick", ["open", "blocked"])]
    assert client(scope="admin").get("/admin/tasks?status=lost").status_code == 422


# ---------------------------------------------------------------------- tasks_update
class Socket:
    def __init__(self):
        self.frames = []

    async def accept(self):
        pass

    async def send_json(self, frame):
        self.frames.append(frame)


async def test_tasks_update_reaches_only_the_workers_v2_sockets(monkeypatch):
    mgr = ConnectionManager()
    v1, v2 = Socket(), Socket()
    await mgr.connect(v1, "eko", "client", contract=1)
    await mgr.connect(v2, "eko", "client", contract=2)
    monkeypatch.setattr(task_service, "worker_tasks", lambda username: [])

    await mgr.send_to_user(WSMessageType.TASKS, username="eko", min_contract=2)

    assert v1.frames == []
    assert [f["type"] for f in v2.frames] == ["tasks_update"]
    assert v2.frames[0]["data"] == []


async def test_tasks_update_to_admins_skips_operators(monkeypatch):
    mgr = ConnectionManager()
    admin, worker = Socket(), Socket()
    await mgr.connect(admin, "boss", "admin")
    await mgr.connect(worker, "eko", "client", contract=2)
    monkeypatch.setattr(task_service, "admin_tasks", lambda: [])

    await mgr.broadcast(WSMessageType.TASKS, scope="admin")

    assert [f["type"] for f in admin.frames] == ["tasks_update"]
    assert worker.frames == []
