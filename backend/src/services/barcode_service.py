import logging
from typing import Optional

from . import queries
from ..models import WarehouseItem

logger = logging.getLogger("backend.services.barcode")


def resolve_barcode_to_item(barcode: str) -> Optional[WarehouseItem]:
    return queries.resolve_barcode_to_item(barcode)
