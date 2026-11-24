"""Time zones (V2_ORDERS_DELTA Q54, R4.3).

Timestamps are stored and served in UTC. The *business* zone is one fixed offset
(``BUSINESS_UTC_OFFSET``, no daylight saving) that decides which local day an instant belongs
to and when the Shopee auto-sync pauses.
"""

import logging
import re
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Optional

from .config import get_config_value

logger = logging.getLogger("backend.timezone")

DEFAULT_UTC_OFFSET = "+07:00"
DEFAULT_AUTO_SYNC_PAUSE = "21:00-06:00"


def as_utc(value: datetime) -> datetime:
    """Aware UTC; a naive value is taken as UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def parse_utc_offset(raw: str) -> timezone:
    match = re.fullmatch(r"([+-])(\d{2}):([0-5]\d)", raw.strip())
    offset = match and timedelta(hours=int(match[2]), minutes=int(match[3]))
    if not match or offset > timedelta(hours=14):
        raise ValueError(f"not a UTC offset like +07:00: {raw!r}")
    return timezone(-offset if match[1] == "-" else offset)


Window = tuple[time, time]


def parse_daily_window(raw: str) -> Optional[Window]:
    """``21:00-06:00`` as (start, end); empty is None. The end may be past midnight."""
    if not raw.strip():
        return None
    start, sep, end = raw.partition("-")
    if not sep:
        raise ValueError(f"not a daily window like 21:00-06:00: {raw!r}")
    return time.fromisoformat(start.strip()), time.fromisoformat(end.strip())


def _configured(key: str, default: str, parse):
    raw = get_config_value(key, default)
    try:
        return parse(raw)
    except ValueError as exc:
        logger.warning("Invalid %s (%s); using %s", key, exc, default)
        return parse(default)


BUSINESS_TZ: timezone = _configured("BUSINESS_UTC_OFFSET", DEFAULT_UTC_OFFSET, parse_utc_offset)
# When the Shopee auto-sync rests, in business time: start included, end excluded.
SHOPEE_AUTO_SYNC_PAUSE: Optional[Window] = _configured(
    "SHOPEE_AUTO_SYNC_PAUSE", DEFAULT_AUTO_SYNC_PAUSE, parse_daily_window
)


def business_time(value: Optional[datetime] = None) -> datetime:
    """``value`` (default: now) on the business clock."""
    return as_utc(value or datetime.now(UTC)).astimezone(BUSINESS_TZ)


def day_start(day: date) -> datetime:
    """The instant ``day`` starts in the business zone."""
    return datetime.combine(day, time.min, tzinfo=BUSINESS_TZ)


def in_daily_window(window: Optional[Window], now: Optional[datetime] = None) -> bool:
    if window is None:
        return False
    start, end = window
    clock = business_time(now).time()
    if start <= end:
        return start <= clock < end
    return clock >= start or clock < end
