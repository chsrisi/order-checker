from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.exceptions import DomainException
from src.services import outbound_service, pick_item_service, shopee_service, stock_service


@pytest.mark.asyncio
async def test_outbound_duplicate_becomes_conflict(monkeypatch):
    def duplicate(**_):
        raise ValueError("Duplicate scan detected")

    monkeypatch.setattr(outbound_service.queries, "create_outbound_item", duplicate)
    with pytest.raises(DomainException) as exc:
        await outbound_service.create_outbound_item("label", "operator", [])
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_outbound_create_broadcasts_to_admin_and_owner(monkeypatch):
    item = SimpleNamespace(id=1)
    monkeypatch.setattr(outbound_service.queries, "create_outbound_item", lambda **_: item)
    monkeypatch.setattr(outbound_service.conn_mgr, "broadcast", AsyncMock())
    monkeypatch.setattr(outbound_service.conn_mgr, "send_to_user", AsyncMock())
    assert await outbound_service.create_outbound_item("label", "operator", []) is item
    outbound_service.conn_mgr.broadcast.assert_awaited_once()
    outbound_service.conn_mgr.send_to_user.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_outbounds_returns_count_and_broadcasts(monkeypatch):
    monkeypatch.setattr(outbound_service.queries, "clear_all_outbound_items", lambda: 4)
    monkeypatch.setattr(outbound_service.conn_mgr, "broadcast", AsyncMock())
    assert await outbound_service.clear_outbound_items("admin") == 4
    outbound_service.conn_mgr.broadcast.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [(LookupError("missing"), 404), (ValueError("bad"), 400)],
)
async def test_stock_errors_become_domain_errors(monkeypatch, error, status_code):
    def fail(**_):
        raise error

    monkeypatch.setattr(stock_service.queries, "update_or_move_stock", fail)
    with pytest.raises(DomainException) as exc:
        await stock_service.update_or_move_stock("SKU", 1, "operator")
    assert exc.value.status_code == status_code


@pytest.mark.asyncio
async def test_pick_missing_item_becomes_not_found(monkeypatch):
    def fail(**_):
        raise LookupError("missing")

    monkeypatch.setattr(pick_item_service.queries, "create_pick_item_entry", fail)
    with pytest.raises(DomainException) as exc:
        await pick_item_service.create_pick_item_entry("SKU", 1, "operator")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_pick_enforces_query_result(monkeypatch):
    monkeypatch.setattr(pick_item_service.queries, "delete_pie", lambda **_: False)
    with pytest.raises(DomainException) as exc:
        await pick_item_service.delete_pie(1, "operator")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_acquire_order_rejects_existing_owner(monkeypatch):
    def conflict(*_):
        raise ValueError("Order is already assigned to another operator")

    monkeypatch.setattr(shopee_service.queries, "acquire_order", conflict)
    with pytest.raises(DomainException) as exc:
        await shopee_service.acquire_order("ORDER", "operator")
    assert exc.value.status_code == 409
