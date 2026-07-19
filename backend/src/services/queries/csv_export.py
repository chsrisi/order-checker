import csv
import io
from sqlalchemy import select
from ...models import OutboundItem, Stock, WarehouseItem
from .engine import get_db


def get_export_scans_csv() -> str:
    with get_db() as db:
        items = (
            db.execute(select(OutboundItem).order_by(OutboundItem.created_at.desc()))
            .scalars()
            .all()
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "ID",
                "Content",
                "User",
                "Scanned At",
                "Closed",
                "Closed At",
                "Tags",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item.id,
                    item.content,
                    item.owner_user,
                    item.created_at.isoformat() if item.created_at else "",
                    item.closed,
                    item.closed_at.isoformat() if item.closed_at else "",
                    ",".join(item.tags or []),
                ]
            )
        return output.getvalue()


def get_export_stocks_csv() -> str:
    with get_db() as db:
        stocks = db.execute(
            select(
                Stock.id,
                Stock.sku,
                Stock.stock,
                Stock.location,
                WarehouseItem.item_name,
            )
            .outerjoin(WarehouseItem, Stock.sku == WarehouseItem.sku)
            .order_by(Stock.sku)
        ).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "SKU", "Item Name", "Stock", "Location"])
        for s in stocks:
            writer.writerow(
                [
                    s.id,
                    s.sku,
                    s.item_name or "",
                    s.stock,
                    s.location or "",
                ]
            )
        return output.getvalue()
