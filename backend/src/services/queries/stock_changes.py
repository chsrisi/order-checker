"""Stock change history for the console (IMPLEMENTATION_PLAN T7.13, V2_STOCK_DELTA S8).

Reads ``warehouse.stocks_log`` newest first, one page at a time. Rows written since T4.3 carry
the structured fields (reason, before, after, reference); older rows only have ``message``, and
are returned as they are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import String, and_, cast, func, select

from ...models import PickItemEntry, StocksLog, WarehouseItem
from ...timezone import as_utc
from .engine import get_db


@dataclass(frozen=True)
class StockChangeFilter:
    """``sku`` and ``actor`` match exactly (case-insensitive); ``reasons`` is any of; the time
    range is inclusive."""

    sku: Optional[str] = None
    actor: Optional[str] = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    since: Optional[datetime] = None
    until: Optional[datetime] = None

    def conditions(self) -> list:
        out = []
        if self.sku and self.sku.strip():
            out.append(func.lower(StocksLog.sku) == self.sku.strip().lower())
        if self.actor and self.actor.strip():
            out.append(func.lower(StocksLog.actor) == self.actor.strip().lower())
        if self.reasons:
            out.append(StocksLog.reason.in_(self.reasons))
        if self.since is not None:
            out.append(StocksLog.timestamp >= as_utc(self.since))
        if self.until is not None:
            out.append(StocksLog.timestamp <= as_utc(self.until))
        return out


def get_stock_changes(
    limit: int, offset: int = 0, f: StockChangeFilter = StockChangeFilter()
) -> tuple[list[dict], int]:
    """Returns ``(page, total)``: each row is the log entry plus the item's name and, for a pick
    or a pick's restore, the order its pick entry belongs to (null once the entry is gone)."""
    conditions = f.conditions()
    with get_db() as db:
        total = db.execute(
            select(func.count()).select_from(StocksLog).filter(*conditions)
        ).scalar_one()
        rows = db.execute(
            select(StocksLog, WarehouseItem.item_name, PickItemEntry.order_sn)
            .outerjoin(WarehouseItem, WarehouseItem.sku == StocksLog.sku)
            .outerjoin(
                PickItemEntry,
                and_(
                    StocksLog.ref_type == "pick_entry",
                    cast(PickItemEntry.id, String) == StocksLog.ref_id,
                ),
            )
            .filter(*conditions)
            .order_by(StocksLog.timestamp.desc(), StocksLog.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        page = [
            {
                "id": log.id,
                "timestamp": log.timestamp,
                "sku": log.sku,
                "item_name": name,
                "location": log.location,
                "delta": log.delta,
                "before": log.before,
                "after": log.after,
                "reason": log.reason,
                "actor": log.actor,
                "ref_type": log.ref_type,
                "ref_id": log.ref_id,
                "message": log.message,
                "order_sn": order_sn,
            }
            for log, name, order_sn in rows
        ]
        return page, total
