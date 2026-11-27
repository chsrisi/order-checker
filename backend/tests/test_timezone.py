"""V2_ORDERS_DELTA Q54 / C3: business offset, local days and the nightly pause."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from src import timezone as tz


def test_default_business_zone_decides_the_day():
    assert tz.business_time(datetime(2026, 11, 24, 16, 59, tzinfo=UTC)).date() == date(2026, 11, 24)
    assert tz.business_time(datetime(2026, 11, 24, 17, 0)).date() == date(2026, 11, 25)  # naive=UTC
    assert tz.day_start(date(2026, 11, 24)) == datetime(2026, 11, 23, 17, tzinfo=UTC)


def test_offsets():
    assert tz.parse_utc_offset("-03:30") == timezone(-timedelta(hours=3, minutes=30))
    for bad in ("7", "+7:00", "+07:60", "+15:00", "Asia/Jakarta", ""):
        with pytest.raises(ValueError):
            tz.parse_utc_offset(bad)


@pytest.mark.parametrize(
    "local,paused",
    [("20:59", False), ("21:00", True), ("23:59", True), ("00:00", True), ("05:59", True),
     ("06:00", False), ("12:00", False)],
)  # fmt: skip
def test_pause_runs_past_midnight_in_business_time(local, paused):
    now = datetime.fromisoformat(f"2026-11-24T{local}+07:00").astimezone(UTC)
    assert tz.in_daily_window(tz.parse_daily_window("21:00-06:00"), now) is paused


def test_pause_within_one_day_empty_and_invalid(monkeypatch):
    noon = datetime.fromisoformat("2026-11-24T12:00+07:00")
    assert tz.in_daily_window(tz.parse_daily_window("11:00-13:00"), noon)
    assert tz.parse_daily_window("") is None and not tz.in_daily_window(None, noon)
    monkeypatch.setenv("SHOPEE_AUTO_SYNC_PAUSE", "late")
    window = tz._configured("SHOPEE_AUTO_SYNC_PAUSE", "21:00-06:00", tz.parse_daily_window)
    assert window == tz.parse_daily_window("21:00-06:00")
