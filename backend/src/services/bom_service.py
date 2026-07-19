import logging
from typing import List, Optional

from . import queries

logger = logging.getLogger("backend.services.bom")


def resolve_standard_bom(sku: str, qty: int) -> List[tuple[str, int]]:
    return queries.resolve_standard_bom(sku, qty)



def get_standard_bom_node(
    sku: str,
    qty: int,
    is_not_primary_child: Optional[bool] = None,
) -> dict:
    return queries.get_standard_bom_node(sku, qty, is_not_primary_child)


def get_marketplace_bom_node(shopee_id: int) -> Optional[dict]:
    return queries.get_marketplace_bom_node(shopee_id)
