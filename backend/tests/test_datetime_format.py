"""T4.6 / F-M6: API and WS datetimes are UTC with a Z suffix (Dart DateTime.parse -> UTC)."""

import json
import re
from datetime import datetime, timedelta, timezone

from fastapi.encoders import jsonable_encoder

from src.models import OutboundResponse, PickItemEntryResponse, ShopeeOrderResponse

# What Dart's DateTime.parse accepts as an explicit UTC instant.
DART_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")


def test_naive_values_are_serialized_as_utc_z():
    naive = datetime(2026, 11, 20, 21, 5, 0, 123456)
    out = OutboundResponse(id=1, content="x", tags=[], created_at=naive, owner_user="op")
    encoded = jsonable_encoder(out)
    assert encoded["created_at"] == "2026-11-20T21:05:00.123456Z"
    assert DART_UTC.match(json.loads(out.model_dump_json())["created_at"])
    assert encoded["closed_at"] is None


def test_offset_values_are_converted_to_utc():
    plus7 = datetime(2026, 11, 21, 4, 5, tzinfo=timezone(timedelta(hours=7)))
    order = ShopeeOrderResponse(order_sn="S", status="PROCESSED", ship_by=plus7)
    assert jsonable_encoder(order)["ship_by"] == "2026-11-20T21:05:00Z"


def test_python_side_values_stay_datetimes():
    pie = PickItemEntryResponse(
        id=1, sku="A01_001", qty=1, timestamp=datetime(2026, 1, 1), owner_user="op"
    )
    assert pie.timestamp.tzinfo is not None  # comparisons in Python are tz-aware
    assert DART_UTC.match(jsonable_encoder(pie)["timestamp"])
