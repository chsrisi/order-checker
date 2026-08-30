import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...models import Stock, StocksLog, WarehouseItem
from ...config import get_config_bool
from .engine import get_db
from .warehouse import resolve_barcode_to_item

logger = logging.getLogger("backend.services.queries.stocks")

SINGLE_LOCATION_STOCK_BYPASS = get_config_bool("SINGLE_LOCATION_STOCK_BYPASS", False)


def _is_single_location_bypass_active() -> bool:
    return get_config_bool(
        "SINGLE_LOCATION_STOCK_BYPASS",
        get_config_bool("STOCK_SINGLE_LOCATION_BYPASS", SINGLE_LOCATION_STOCK_BYPASS),
    )


# ==============================================================================
# SINGLE-LOCATION STOCK BYPASS
# ==============================================================================
# The default data model allows a many-to-one relationship between stocks and items
# (i.e. an item can be distributed across multiple warehouse locations).
#
# When SINGLE_LOCATION_STOCK_BYPASS is enabled (SINGLE_LOCATION_STOCK_BYPASS=1/true):
#   1. An item stock can only exist in a single location in the database.
#   2. For add or set operations with NO location specified (location=None):
#      - If the item already has a stock record in some location, update the stock
#        in that sole existing location.
#      - If the item has no existing stock records, create the stock at the item's
#        default location (from WarehouseItem.location) or None.
#   3. For add or set operations WITH a location specified (location="..."):
#      - If existing stock exists at another location (or multiple locations),
#        transfer all existing stock to the new location first (removing the old
#        records), and then apply the add or set operation at the new location.
#   4. For transfer (move_to) operations:
#      - Transfers all stock of the item to move_to, ensuring the item remains in
#        only 1 location.
#
# When SINGLE_LOCATION_STOCK_BYPASS is disabled (SINGLE_LOCATION_STOCK_BYPASS=0, default),
# the standard multi-location stock behavior is preserved.
#
# HOW TO REMOVE THIS BYPASS COMPLETELY (Code Cleanup):
# To remove this bypass mechanism entirely without relying on environment variables:
# 1. In this file (`backend/src/services/queries/stocks.py`):
#    - Remove the `if _is_single_location_bypass_active():` branch in `update_or_move_stock`
#      and `get_or_merge_stock`, keeping only the standard multi-location logic.
#    - Remove `SINGLE_LOCATION_STOCK_BYPASS` and `_is_single_location_bypass_active()`.
# 2. In `backend/.env.example` and `backend/.env`:
#    - Remove the `SINGLE_LOCATION_STOCK_BYPASS` configuration variable.
# 3. In `docs/OPERATIONS.md`:
#    - Remove the single-location bypass section and configuration table entry.
# ==============================================================================


def update_or_move_stock(
    sku_in: str,
    stock_qty: int,
    username: str,
    mode: str = "set",
    location: Optional[str] = None,
    move_to: Optional[str] = None,
    is_location_set: bool = True,
) -> tuple[Stock, Optional[str]]:
    item = resolve_barcode_to_item(sku_in)
    if not item:
        raise LookupError(f"Item with SKU or barcode '{sku_in}' not found")
    sku = item.sku
    loc_clean = location if location != "" and location is not None else None
    move_to_clean = move_to if move_to != "" and move_to is not None else None

    if stock_qty < 0:
        raise ValueError("Stock quantity cannot be negative")

    with get_db() as db:
        if _is_single_location_bypass_active():
            existing_records = list(
                db.execute(select(Stock).filter(Stock.sku == sku)).scalars().all()
            )
            total_existing_stock = sum(r.stock for r in existing_records)

            if move_to_clean is not None:
                if loc_clean == move_to_clean:
                    target_rec = next(
                        (r for r in existing_records if r.location == loc_clean), None
                    )
                    if not target_rec:
                        target_rec = Stock(sku=sku, stock=0, location=loc_clean)
                        db.add(target_rec)
                        db.flush()
                    res = target_rec
                else:
                    if total_existing_stock <= 0:
                        raise ValueError("Source location has no stock")
                    if total_existing_stock < stock_qty:
                        raise ValueError("Insufficient stock at source location")

                    # In single-location mode, transfer all stock to move_to
                    for r in existing_records:
                        db.delete(r)
                    db.flush()

                    new_qty = total_existing_stock
                    if new_qty <= 0:
                        res = Stock(id=0, sku=sku, stock=0, location=move_to_clean)
                    else:
                        dest = Stock(sku=sku, stock=new_qty, location=move_to_clean)
                        db.add(dest)
                        db.flush()
                        res = dest
            else:
                # Add or Set operation in single-location bypass mode
                if loc_clean is None:
                    # No location provided -> update in that sole existing location
                    if existing_records:
                        target_location = existing_records[0].location
                        target_rec = existing_records[0]
                        for r in existing_records[1:]:
                            db.delete(r)

                        if mode == "add":
                            target_rec.stock = total_existing_stock + stock_qty
                        else:
                            target_rec.stock = stock_qty

                        if target_rec.stock <= 0:
                            db.delete(target_rec)
                            res = Stock(id=0, sku=sku, stock=0, location=target_location)
                        else:
                            res = target_rec
                    else:
                        # No existing stock -> create at item's default location or None
                        target_location = loc_clean if is_location_set else item.location
                        new_stock = stock_qty
                        if new_stock <= 0:
                            res = Stock(id=0, sku=sku, stock=0, location=target_location)
                        else:
                            stock_rec = Stock(
                                sku=sku,
                                stock=new_stock,
                                location=target_location,
                            )
                            db.add(stock_rec)
                            db.flush()
                            res = stock_rec
                else:
                    # Location is provided -> transfer all existing to new location, then do add/set op
                    for r in existing_records:
                        db.delete(r)
                    db.flush()

                    if mode == "add":
                        new_stock = total_existing_stock + stock_qty
                    else:
                        new_stock = stock_qty

                    if new_stock <= 0:
                        res = Stock(id=0, sku=sku, stock=0, location=loc_clean)
                    else:
                        dest = Stock(sku=sku, stock=new_stock, location=loc_clean)
                        db.add(dest)
                        db.flush()
                        res = dest
        else:
            # Standard multi-location mode
            if move_to_clean is not None:
                if loc_clean == move_to_clean:
                    stock_rec = (
                        db.execute(
                            select(Stock).filter(Stock.sku == sku, Stock.location == loc_clean)
                        )
                        .scalars()
                        .first()
                    )
                    if not stock_rec:
                        stock_rec = Stock(sku=sku, stock=0, location=loc_clean)
                        db.add(stock_rec)
                        db.flush()
                    res = stock_rec
                else:
                    source = (
                        db.execute(
                            select(Stock).filter(Stock.sku == sku, Stock.location == loc_clean)
                        )
                        .scalars()
                        .first()
                    )
                    if not source:
                        raise ValueError("Source location has no stock")
                    if source.stock < stock_qty:
                        raise ValueError("Insufficient stock at source location")

                    dest = (
                        db.execute(
                            select(Stock).filter(Stock.sku == sku, Stock.location == move_to_clean)
                        )
                        .scalars()
                        .first()
                    )
                    if not dest:
                        dest = Stock(sku=sku, stock=0, location=move_to_clean)
                        db.add(dest)
                        db.flush()

                    source.stock -= stock_qty
                    dest.stock += stock_qty

                    if source.stock <= 0:
                        db.delete(source)
                    if dest.stock <= 0:
                        db.delete(dest)
                        res = Stock(id=0, sku=sku, stock=0, location=move_to_clean)
                    else:
                        res = dest
            else:
                stock_rec = (
                    db.execute(
                        select(Stock).filter(
                            Stock.sku == sku,
                            Stock.location == loc_clean,
                        )
                    )
                    .scalars()
                    .first()
                )
                if stock_rec:
                    if mode == "add":
                        stock_rec.stock += stock_qty
                    else:
                        stock_rec.stock = stock_qty
                else:
                    location_val = loc_clean if is_location_set else item.location
                    stock_rec = Stock(
                        sku=sku,
                        stock=stock_qty,
                        location=location_val,
                    )
                    db.add(stock_rec)
                    db.flush()

                if stock_rec.stock <= 0:
                    db.delete(stock_rec)
                    res = Stock(id=0, sku=sku, stock=0, location=loc_clean)
                else:
                    res = stock_rec

        log_entry = StocksLog(
            message=f"stock update: sku={sku}, qty={stock_qty}, mode={mode}, user={username}"
        )
        db.add(log_entry)
        db.commit()
        return res, item.item_name


def get_stocks_data(join_warehouse: bool = False):
    with get_db() as db:
        query = select(Stock)
        if join_warehouse:
            query = select(
                Stock.id,
                Stock.sku,
                Stock.stock,
                Stock.location,
                WarehouseItem.item_name,
            ).join(WarehouseItem, Stock.sku == WarehouseItem.sku)
        results = db.execute(query)
        return list(results.all() if join_warehouse else results.scalars().all())


def get_all_stocks_data(join_warehouse: bool = False):
    return get_stocks_data(join_warehouse=join_warehouse)


def get_or_merge_stock(sku: str, location: Optional[str], qty: int, username: str) -> Stock:
    loc_clean = location.strip() if location and location.strip() else None
    with get_db() as db:
        if _is_single_location_bypass_active():
            existing_records = list(
                db.execute(select(Stock).filter(Stock.sku == sku)).scalars().all()
            )
            target_location = loc_clean
            if target_location is None and existing_records:
                target_location = existing_records[0].location

            for r in existing_records:
                db.delete(r)
            db.flush()

            db_stock = Stock(
                sku=sku,
                location=target_location,
                stock=qty,
            )
            db.add(db_stock)

            log_entry = StocksLog(
                message=f"stock update/merge: sku={sku}, qty={qty}, user={username}"
            )
            db.add(log_entry)

            db.commit()
            db.refresh(db_stock)
            return db_stock

        existing = (
            db.execute(
                select(Stock).filter(
                    Stock.sku == sku,
                    Stock.location == loc_clean,
                )
            )
            .scalars()
            .first()
        )

        if existing:
            existing.stock = qty

            log_entry = StocksLog(
                message=f"stock update/merge: sku={sku}, qty={qty}, user={username}"
            )
            db.add(log_entry)

            db.commit()
            db.refresh(existing)
            return existing

        db_stock = Stock(
            sku=sku,
            location=loc_clean,
            stock=qty,
        )
        db.add(db_stock)

        log_entry = StocksLog(message=f"stock update/merge: sku={sku}, qty={qty}, user={username}")
        db.add(log_entry)

        db.commit()
        db.refresh(db_stock)
        return db_stock


def _reduce_stock_for_pick_db(sku: str, qty: int, username: str, db: Session) -> int:
    existing_records = list(db.execute(select(Stock).filter(Stock.sku == sku)).scalars().all())
    total_existing_stock = sum(r.stock for r in existing_records)

    if total_existing_stock < qty:
        logger.warning(
            f"Insufficient stock for SKU '{sku}' during pick by user '{username}': "
            f"requested {qty}, available {total_existing_stock}. Available qty set to 0."
        )
        for r in existing_records:
            db.delete(r)

        log_entry = StocksLog(
            message=f"stock pick: sku={sku}, qty={qty}, user={username}, warning=insufficient_stock"
        )
        db.add(log_entry)
        db.flush()
        return 0
    else:
        remaining_to_deduct = qty
        for r in existing_records:
            if remaining_to_deduct <= 0:
                break
            deduct = min(r.stock, remaining_to_deduct)
            r.stock -= deduct
            remaining_to_deduct -= deduct
            if r.stock <= 0:
                db.delete(r)

        log_entry = StocksLog(message=f"stock pick: sku={sku}, qty={qty}, user={username}")
        db.add(log_entry)
        db.flush()
        return total_existing_stock - qty


def reduce_stock_for_pick(
    sku: str,
    qty: int,
    username: str,
    db: Optional[Session] = None,
) -> int:
    """
    Reduces available stock for a given SKU based on pick quantity.
    If pick qty exceeds available stock (or no stock exists), logs a warning,
    clamps available stock to 0 without blocking the pick, and records to StocksLog.
    Returns the remaining available stock for the SKU (>= 0).
    """
    if qty <= 0:
        return 0

    if db is not None:
        return _reduce_stock_for_pick_db(sku=sku, qty=qty, username=username, db=db)
    with get_db() as db_session:
        res = _reduce_stock_for_pick_db(sku=sku, qty=qty, username=username, db=db_session)
        db_session.commit()
        return res
