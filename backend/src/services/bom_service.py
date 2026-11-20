import logging
from typing import Optional

from . import queries

logger = logging.getLogger("backend.services.bom")


def get_standard_bom_node(
    sku: str,
    qty: int,
    is_not_primary_child: Optional[bool] = None,
) -> dict:
    return queries.get_standard_bom_node(sku, qty, is_not_primary_child)


def get_marketplace_bom_node(shopee_id: int, qty: int = 1) -> Optional[dict]:
    return queries.get_marketplace_bom_node(shopee_id, qty)
