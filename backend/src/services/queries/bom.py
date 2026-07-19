import logging
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...models import (
    BOMHeader,
    BOMDetail,
    BOMHeaderMarketplace,
    BOMDetailMarketplace,
    WarehouseItem,
)
from .engine import get_db

logger = logging.getLogger("backend.services.queries.bom")


def get_standard_bom_node_internal(
    sku: str,
    qty: int,
    is_not_primary_child: Optional[bool],
    db: Session,
    visited: Optional[set] = None,
) -> dict:
    if visited is None:
        visited = set()

    item = db.execute(select(WarehouseItem).filter(WarehouseItem.sku == sku)).scalar_one_or_none()
    name = (item.item_name if item else None) or sku

    node = {
        "sku": sku,
        "name": name,
        "quantity": qty,
        "is_not_primary_child": is_not_primary_child or False,
        "type": "standard",
        "children": [],
    }

    if sku in visited:
        return node

    new_visited = visited | {sku}

    hdr = db.execute(select(BOMHeader).filter(BOMHeader.sku == sku)).scalar_one_or_none()
    if hdr:
        details = (
            db.execute(select(BOMDetail).filter(BOMDetail.bom_header_id == hdr.id)).scalars().all()
        )
        for detail in details:
            child_node = get_standard_bom_node_internal(
                detail.component_sku,
                detail.quantity_standard * qty,
                detail.is_not_primary_child,
                db,
                new_visited,
            )
            node["children"].append(child_node)

    return node


def get_bom_headers() -> List[dict]:
    with get_db() as db:
        headers = db.execute(select(BOMHeader)).scalars().all()
        result = []
        for h in headers:
            item = db.execute(
                select(WarehouseItem).filter(WarehouseItem.sku == h.sku)
            ).scalar_one_or_none()
            name = item.item_name if item else None
            note = item.note if item else None
            result.append({"id": h.id, "sku": h.sku, "item_name": name, "note": note})
        return result


def get_marketplace_bom_headers() -> List[dict]:
    with get_db() as db:
        headers = db.execute(select(BOMHeaderMarketplace)).scalars().all()
        return [
            {
                "shopee_id": h.shopee_id,
                "item_name": h.item_name,
                "quantity_standard": h.quantity_standard,
            }
            for h in headers
        ]


def resolve_standard_bom(sku: str, qty: int) -> List[tuple[str, int]]:
    with get_db() as db:
        hdr = db.execute(select(BOMHeader).filter(BOMHeader.sku == sku)).scalar_one_or_none()
        if not hdr:
            return [(sku, qty)]

        details = (
            db.execute(select(BOMDetail).filter(BOMDetail.bom_header_id == hdr.id)).scalars().all()
        )
        result: List[tuple[str, int]] = []
        for detail in details:
            sub_components = resolve_standard_bom_internal(
                detail.component_sku, detail.quantity_standard * qty, db
            )
            result.extend(sub_components)
        return result


def resolve_standard_bom_internal(sku: str, qty: int, db: Session) -> List[tuple[str, int]]:
    hdr = db.execute(select(BOMHeader).filter(BOMHeader.sku == sku)).scalar_one_or_none()
    if not hdr:
        return [(sku, qty)]

    details = (
        db.execute(select(BOMDetail).filter(BOMDetail.bom_header_id == hdr.id)).scalars().all()
    )
    result: List[tuple[str, int]] = []
    for detail in details:
        sub_components = resolve_standard_bom_internal(
            detail.component_sku, detail.quantity_standard * qty, db
        )
        result.extend(sub_components)
    return result


def get_standard_bom_node(sku: str, qty: int, is_not_primary_child: Optional[bool] = None) -> dict:
    with get_db() as db:
        return get_standard_bom_node_internal(sku, qty, is_not_primary_child, db)


def get_marketplace_bom_node(shopee_id: int) -> Optional[dict]:
    with get_db() as db:
        hdr = db.execute(
            select(BOMHeaderMarketplace).filter(BOMHeaderMarketplace.shopee_id == shopee_id)
        ).scalar_one_or_none()
        if not hdr:
            return None

        name = hdr.item_name or f"Marketplace Item {shopee_id}"
        node = {
            "sku": f"MP:{shopee_id}",
            "name": name,
            "quantity": hdr.quantity_standard or 1,
            "type": "marketplace",
            "children": [],
        }

        details = (
            db.execute(
                select(BOMDetailMarketplace).filter(BOMDetailMarketplace.shopee_id == shopee_id)
            )
            .scalars()
            .all()
        )
        for detail in details:
            child_node = get_standard_bom_node_internal(
                detail.component_sku,
                detail.quantity_standard or 1,
                detail.is_not_primary_child,
                db,
            )
            node["children"].append(child_node)

        return node
