import logging
from typing import Optional
from sqlalchemy import select
from ...models import Stock, StocksLog, WarehouseItem
from .engine import get_db
from .warehouse import resolve_barcode_to_item

logger = logging.getLogger("backend.services.queries.stocks")

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

    with get_db() as db:
        if move_to_clean is not None:
            if loc_clean == move_to_clean:
                stock_rec = (
                    db.execute(
                        select(Stock).filter(
                            Stock.sku == sku, Stock.location == loc_clean
                        )
                    )
                    .scalars()
                    .first()
                )
                if not stock_rec:
                    stock_rec = Stock(
                        sku=sku, stock=0, location=loc_clean
                    )
                    db.add(stock_rec)
                    db.flush()
                res = stock_rec
            else:
                source = (
                    db.execute(
                        select(Stock).filter(
                            Stock.sku == sku, Stock.location == loc_clean
                        )
                    )
                    .scalars()
                    .first()
                )
                if not source:
                    source = Stock(
                        sku=sku, stock=0, location=loc_clean
                    )
                    db.add(source)
                    db.flush()

                dest = (
                    db.execute(
                        select(Stock).filter(
                            Stock.sku == sku, Stock.location == move_to_clean
                        )
                    )
                    .scalars()
                    .first()
                )
                if not dest:
                    dest = Stock(
                        sku=sku, stock=0, location=move_to_clean
                    )
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
                location_val = (
                    loc_clean if is_location_set else item.location
                )
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


def get_or_merge_stock(
    sku: str, location: Optional[str], qty: int, username: str
) -> Stock:
    loc_clean = location.strip() if location and location.strip() else None
    with get_db() as db:
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
        
        log_entry = StocksLog(
            message=f"stock update/merge: sku={sku}, qty={qty}, user={username}"
        )
        db.add(log_entry)
        
        db.commit()
        db.refresh(db_stock)
        return db_stock
