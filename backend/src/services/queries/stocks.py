"""Inventory engine (IMPLEMENTATION_PLAN T4.3, delta D4.3, STOCK_MODEL_DISCUSSION §8).

One engine for both stock location modes. The only mode-specific decisions live in a
``LocationPolicy``:

==================  ===========================================  ==============================
decision            ``multi`` (default)                          ``single``
==================  ===========================================  ==============================
target for set/add  requested location; else the SKU's only bin;   requested location; else the
                    else the unlocated bin                         SKU's current location
invariant           none                                           merge every other row into
                                                                   the target (``mode_merge``)
transfer source     the requested bin, requested quantity          all rows, everything
deduction order     ``location`` ascending, unlocated bin last     same (one row)
restore target      the allocation's original bin (recreated)      the current sole location
==================  ===========================================  ==============================

Shared rules:

* rows are locked ``ORDER BY sku, location FOR UPDATE`` (pick entry, then allocations, then
  stock, in pick paths)
* a row that reaches 0 is deleted; restores recreate it
* every change writes a structured ``StocksLog`` row (``REASONS``)
* functions taking ``db`` never commit: the caller owns the transaction (T4.2). The public
  ``update_or_move_stock`` is its own unit of work.

The schema has no per-item default location (``WarehouseItem.location`` is derived from the
existing bins), so the "item default first" deduction rule (Q3) reduces to location order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import stock_location_mode
from ...models import PickItemEntry, PickStockAllocation, Stock, StocksLog, WarehouseItem
from .engine import get_db
from .warehouse import resolve_barcode_to_item

logger = logging.getLogger("backend.services.queries.stocks")

REASONS = (
    "adjust_set",
    "adjust_add",
    "transfer_out",
    "transfer_in",
    "pick",
    "pick_shortfall",
    "pick_restore",
    "mode_merge",
    "cutover_clear",
    "migration_merge",
)


# ---------------------------------------------------------------------------- policies
def _location_key(row: Stock) -> tuple[bool, str]:
    return (row.location is None, row.location or "")


class LocationPolicy:
    name = "base"
    merge_into_target = False
    transfer_all = False

    def resolve_target(self, rows: list[Stock], requested: Optional[str]) -> Optional[str]:
        raise NotImplementedError

    def deduction_order(self, rows: list[Stock]) -> list[Stock]:
        return sorted(rows, key=_location_key)

    def restore_target(self, rows: list[Stock], original: Optional[str]) -> Optional[str]:
        raise NotImplementedError


class MultiLocationPolicy(LocationPolicy):
    name = "multi"

    def resolve_target(self, rows, requested):
        if requested is not None:
            return requested
        return rows[0].location if len(rows) == 1 else None

    def restore_target(self, rows, original):
        return original


class SingleLocationPolicy(LocationPolicy):
    name = "single"
    merge_into_target = True
    transfer_all = True

    def resolve_target(self, rows, requested):
        if requested is not None:
            return requested
        return self.deduction_order(rows)[0].location if rows else None

    def restore_target(self, rows, original):
        return self.deduction_order(rows)[0].location if rows else original


_POLICIES = {"multi": MultiLocationPolicy(), "single": SingleLocationPolicy()}


def location_policy() -> LocationPolicy:
    """Evaluated per call, so tests and an env change take effect without re-import."""
    return _POLICIES[stock_location_mode()]


# ------------------------------------------------------------------------ primitives
def _clean(location: Optional[str]) -> Optional[str]:
    if location is None:
        return None
    location = location.strip()
    return location or None


@dataclass
class StockChange:
    actor: str
    reason: str
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None


class _Bins:
    """The locked stock rows of one SKU, keyed by location, with logged mutations."""

    def __init__(self, db: Session, sku: str):
        self.db = db
        self.sku = sku
        rows = (
            db.execute(
                select(Stock)
                .filter(Stock.sku == sku)
                .order_by(Stock.sku, Stock.location, Stock.id)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        self.rows: dict[Optional[str], Stock] = {}
        for row in rows:
            if row.location in self.rows:  # pre-migration duplicate: fold silently
                self.rows[row.location].stock += row.stock
                db.delete(row)
            else:
                self.rows[row.location] = row

    def list(self) -> list[Stock]:
        return list(self.rows.values())

    def qty(self, location: Optional[str]) -> int:
        row = self.rows.get(location)
        return row.stock if row else 0

    def total(self) -> int:
        return sum(r.stock for r in self.rows.values())

    def change(self, location: Optional[str], delta: int, why: StockChange) -> Stock:
        """Apply ``delta`` at ``location`` and log it. Returns the row, or a transient
        ``Stock(id=0, stock=0)`` when the row reached 0 and was deleted."""
        before = self.qty(location)
        after = before + delta
        if after < 0:
            raise ValueError("Insufficient stock at source location")
        row = self.rows.get(location)
        if delta != 0 or why.reason.startswith("adjust"):
            self.db.add(
                StocksLog(
                    message=(
                        f"{why.reason}: sku={self.sku}, location={location}, "
                        f"delta={delta:+d}, user={why.actor}"
                    ),
                    sku=self.sku,
                    location=location,
                    delta=delta,
                    before=before,
                    after=after,
                    reason=why.reason,
                    actor=why.actor,
                    ref_type=why.ref_type,
                    ref_id=why.ref_id,
                )
            )
        if after == 0:
            if row is not None:
                self.db.delete(row)
                del self.rows[location]
                self.db.flush()  # before any re-insert of this (sku, location)
            return Stock(id=0, sku=self.sku, stock=0, location=location)
        if row is None:
            row = Stock(sku=self.sku, stock=after, location=location)
            self.db.add(row)
            self.rows[location] = row
        else:
            row.stock = after
        self.db.flush()
        return row

    def merge_into(self, target: Optional[str], actor: str) -> None:
        """``single`` invariant: move every other row into ``target`` (logged mode_merge)."""
        for location in [loc for loc in self.rows if loc != target]:
            qty = self.rows[location].stock
            why = StockChange(actor=actor, reason="mode_merge")
            self.change(location, -qty, why)
            self.change(target, qty, why)


def _log_note(db: Session, sku: str, reason: str, actor: str, message: str, **ref) -> None:
    db.add(StocksLog(message=message, sku=sku, delta=0, reason=reason, actor=actor, **ref))


# ------------------------------------------------------------------- adjust / transfer
def apply_stock_update(
    db: Session,
    sku: str,
    stock_qty: int,
    username: str,
    mode: str = "set",
    location: Optional[str] = None,
    move_to: Optional[str] = None,
) -> Stock:
    if stock_qty < 0:
        raise ValueError("Stock quantity cannot be negative")
    if mode not in ("set", "add"):
        raise ValueError("Invalid mode")
    policy = location_policy()
    bins = _Bins(db, sku)
    requested, move_to = _clean(location), _clean(move_to)

    if move_to is not None:
        source = policy.resolve_target(bins.list(), requested)
        if source == move_to:
            row = bins.rows.get(move_to)
            return row or Stock(id=0, sku=sku, stock=0, location=move_to)
        available = bins.total() if policy.transfer_all else bins.qty(source)
        if available <= 0:
            raise ValueError("Source location has no stock")
        if available < stock_qty:
            raise ValueError("Insufficient stock at source location")
        if policy.transfer_all:
            moves = [(loc, bins.qty(loc)) for loc in list(bins.rows) if loc != move_to]
        else:
            moves = [(source, stock_qty)]
        result = bins.rows.get(move_to) or Stock(id=0, sku=sku, stock=0, location=move_to)
        for loc, qty in moves:
            bins.change(loc, -qty, StockChange(username, "transfer_out", "transfer", move_to))
            result = bins.change(
                move_to, qty, StockChange(username, "transfer_in", "transfer", str(loc))
            )
        return result

    target = policy.resolve_target(bins.list(), requested)
    if policy.merge_into_target:
        bins.merge_into(target, username)
    current = bins.qty(target)
    delta = stock_qty if mode == "add" else stock_qty - current
    return bins.change(target, delta, StockChange(username, f"adjust_{mode}"))


def update_or_move_stock(
    sku_in: str,
    stock_qty: int,
    username: str,
    mode: str = "set",
    location: Optional[str] = None,
    move_to: Optional[str] = None,
    is_location_set: bool = True,  # accepted for compatibility; the policy decides
) -> tuple[Stock, Optional[str]]:
    item = resolve_barcode_to_item(sku_in)
    if not item:
        raise LookupError(f"Item with SKU or barcode '{sku_in}' not found")
    if stock_qty < 0:
        raise ValueError("Stock quantity cannot be negative")
    with get_db() as db:
        try:
            res = apply_stock_update(
                db, item.sku, stock_qty, username, mode=mode, location=location, move_to=move_to
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        return res, item.item_name


# ------------------------------------------------------------------------------ picks
def deduct_for_pick(db: Session, entry: PickItemEntry, qty: int, actor: str) -> int:
    """Deduct ``qty`` of ``entry.sku`` bin by bin, writing one allocation per bin.

    Never blocks the pick: unmet quantity is logged as ``pick_shortfall`` and stays
    unallocated (it is never restored). Returns the quantity actually deducted."""
    if qty <= 0:
        return 0
    if entry.id is None:
        db.flush()
    bins = _Bins(db, entry.sku)
    remaining = qty
    ref = {"ref_type": "pick_entry", "ref_id": str(entry.id)}
    for row in location_policy().deduction_order(bins.list()):
        if remaining <= 0:
            break
        take = min(row.stock, remaining)
        if take <= 0:
            continue
        location = row.location
        bins.change(location, -take, StockChange(actor, "pick", **ref))
        entry.allocations.append(PickStockAllocation(sku=entry.sku, location=location, qty=take))
        remaining -= take
    if remaining:
        logger.warning(
            "pick_shortfall",
            extra={"sku": entry.sku, "requested": qty, "unmet": remaining, "username": actor},
        )
        _log_note(
            db,
            entry.sku,
            "pick_shortfall",
            actor,
            f"pick_shortfall: sku={entry.sku}, requested={qty}, unmet={remaining}, user={actor}",
            **ref,
        )
    db.flush()
    return qty - remaining


def move_pick_quantity(db: Session, src: PickItemEntry, dst: PickItemEntry, qty: int) -> None:
    """Move ``qty`` from ``src`` to ``dst`` (assign/unassign split, Q1). Deducted quantity
    moves first, FIFO by allocation id; shortfall stays with the remainder. No stock change."""
    remaining = qty
    for alloc in list(src.allocations):
        if remaining <= 0:
            break
        if alloc.qty <= remaining:
            remaining -= alloc.qty
            alloc.entry = dst
        else:
            alloc.qty -= remaining
            dst.allocations.append(
                PickStockAllocation(
                    sku=alloc.sku,
                    location=alloc.location,
                    qty=remaining,
                    created_at=alloc.created_at,
                )
            )
            remaining = 0
    src.qty -= qty
    dst.qty = (dst.qty or 0) + qty
    db.flush()


def restore_for_pick(db: Session, entry: PickItemEntry, actor: str) -> int:
    """Return every allocation of ``entry`` to stock (delete path). Returns the quantity."""
    allocations = (
        db.execute(
            select(PickStockAllocation)
            .filter(PickStockAllocation.pick_entry_id == entry.id)
            .order_by(PickStockAllocation.id)
            .with_for_update()
        )
        .scalars()
        .all()
    )
    if not allocations:
        return 0
    bins = _Bins(db, entry.sku)
    policy = location_policy()
    restored = 0
    for alloc in allocations:
        target = policy.restore_target(bins.list(), alloc.location)
        bins.change(
            target,
            alloc.qty,
            StockChange(actor, "pick_restore", "pick_entry", str(entry.id)),
        )
        restored += alloc.qty
    return restored


# -------------------------------------------------------------------- maintenance/read
def merge_all_to_single(db: Session, actor: str = "maintenance") -> dict[str, int]:
    """A-8b: collapse every multi-row SKU onto its first bin (location order)."""
    skus = (
        db.execute(
            select(Stock.sku).group_by(Stock.sku).having(func.count() > 1).order_by(Stock.sku)
        )
        .scalars()
        .all()
    )
    merged: dict[str, int] = {}
    policy = SingleLocationPolicy()
    for sku in skus:
        bins = _Bins(db, sku)
        merged[sku] = len(bins.rows)
        bins.merge_into(policy.resolve_target(bins.list(), None), actor)
    return merged


def get_stocks_data(join_warehouse: bool = False):
    """Rows with ``_mapping`` (id, sku, stock, location[, item_name]) in both modes."""
    with get_db() as db:
        query = select(Stock.id, Stock.sku, Stock.stock, Stock.location)
        if join_warehouse:
            query = query.add_columns(WarehouseItem.item_name).join(
                WarehouseItem, Stock.sku == WarehouseItem.sku
            )
        return list(db.execute(query).all())
