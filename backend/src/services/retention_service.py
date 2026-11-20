"""Recipient data retention (delta A-10b, D4.1; docs/OPERATIONS.md "Data Retention").

Shopee's DPP allows keeping buyer data for at most 90 days; this project keeps it for
``RECIPIENT_RETENTION_DAYS`` (default 30). Recipient data is only used for quick order
matching by workers, so it is removed once an order is well past fulfilment.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from .. import config
from ..config import get_config_int
from . import queries

logger = logging.getLogger("backend.services.retention")

RETENTION_INTERVAL_SECONDS = get_config_int("RECIPIENT_RETENTION_INTERVAL_SECONDS", 86400)


def purge_expired_recipient_data(now: Optional[datetime] = None) -> tuple[int, int]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=config.RECIPIENT_RETENTION_DAYS)
    addresses, notes = queries.purge_recipient_data(cutoff)
    # Counts only: recipient values must never reach the logs.
    logger.info(
        "recipient_retention_purged",
        extra={
            "event": "retention.recipient.purged",
            "addresses_deleted": addresses,
            "notes_cleared": notes,
            "retention_days": config.RECIPIENT_RETENTION_DAYS,
        },
    )
    return addresses, notes


async def recipient_retention_task():
    """Runs once at startup, then every RETENTION_INTERVAL_SECONDS."""
    try:
        while True:
            try:
                await asyncio.to_thread(purge_expired_recipient_data)
            except Exception:
                logger.exception(
                    "recipient_retention_failed", extra={"event": "retention.recipient.failed"}
                )
            await asyncio.sleep(RETENTION_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Recipient retention task cancelled")
        raise
