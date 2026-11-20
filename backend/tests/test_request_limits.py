"""T2.14: request size limits (boundaries) on client-used and admin request bodies."""

import pytest
from pydantic import ValidationError

from src.models import (
    CLOSE_MAX_ITEMS,
    LOCATION_MAX_LENGTH,
    ORDER_SN_MAX_LENGTH,
    SCAN_MAX_LENGTH,
    TAG_MAX_LENGTH,
    TAGS_MAX_ITEMS,
    OutboundCreate,
    PickItemEntryAssign,
    PickItemEntryCreate,
    PickItemEntryUnassign,
    StockCreate,
)

AT = "x" * SCAN_MAX_LENGTH
OVER = AT + "x"


def test_scan_fields_accept_limit_and_reject_over():
    assert OutboundCreate(content=AT).content == AT
    assert PickItemEntryCreate(sku=AT, qty=1).sku == AT
    assert StockCreate(sku=AT, stock=1).sku == AT
    for build in (
        lambda: OutboundCreate(content=OVER),
        lambda: PickItemEntryCreate(sku=OVER, qty=1),
        lambda: StockCreate(sku=OVER, stock=1),
        lambda: PickItemEntryUnassign(order_sn="SN", sku=OVER, qty=1),
    ):
        with pytest.raises(ValidationError):
            build()


def test_multiline_qr_payload_fits():
    qr = "A01_001*2 batch 7\n" + "supplier-data-" * 40
    assert len(qr) < SCAN_MAX_LENGTH
    assert PickItemEntryCreate(sku=qr, qty=1).sku == qr


def test_tags_order_sn_and_location_limits():
    OutboundCreate(content="c", tags=["t" * TAG_MAX_LENGTH] * TAGS_MAX_ITEMS)
    with pytest.raises(ValidationError):
        OutboundCreate(content="c", tags=["t"] * (TAGS_MAX_ITEMS + 1))
    with pytest.raises(ValidationError):
        OutboundCreate(content="c", tags=["t" * (TAG_MAX_LENGTH + 1)])
    with pytest.raises(ValidationError):
        PickItemEntryAssign(order_sn="S" * (ORDER_SN_MAX_LENGTH + 1))
    with pytest.raises(ValidationError):
        StockCreate(sku="s", stock=1, location="L" * (LOCATION_MAX_LENGTH + 1))


def test_close_body_limit_returns_422():
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from src.dependencies import require_admin
    from src.main import app

    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        username="boss", scope="admin"
    )
    try:
        resp = TestClient(app).post("/outbound/close", json=["x"] * (CLOSE_MAX_ITEMS + 1))
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()
