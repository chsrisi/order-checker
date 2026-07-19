import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Stock

logger = logging.getLogger("backend.services.stock")


def get_or_merge_stock(
    db: Session, sku: str, location: Optional[str]
) -> Optional[Stock]:
    # Query all records matching sku and location
    if location:
        records = (
            db.execute(
                select(Stock).filter(Stock.sku == sku, Stock.location == location)
            )
            .scalars()
            .all()
        )
    else:
        records = (
            db.execute(
                select(Stock).filter(
                    Stock.sku == sku,
                    (Stock.location == None) | (Stock.location == ""),  # noqa: E711
                )
            )
            .scalars()
            .all()
        )

    if not records:
        return None

    primary = records[0]
    if len(records) > 1:
        total_stock = sum(r.stock for r in records)
        primary.stock = total_stock
        for r in records[1:]:
            db.delete(r)
        db.flush()
        db.refresh(primary)

    return primary
