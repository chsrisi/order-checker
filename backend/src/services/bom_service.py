import logging
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    BOMHeader,
    BOMDetail,
    BOMHeaderMarketplace,
    BOMDetailMarketplace,
    WarehouseItem,
    ShopeeItem,
    ShopeeOrder,
    ShopeeOrderRecipientResponse,
    ShopeeOrderInfoResponse,
    ShopeeOrderResponse,
    ShopeeOrderItemBOMResponse,
)

logger = logging.getLogger("backend.services.bom")


def resolve_standard_bom(sku: str, qty: int, db: Session) -> List[tuple[str, int]]:
    # Check if this sku has a BOMHeader
    hdr = db.execute(
        select(BOMHeader).filter(BOMHeader.sku == sku)
    ).scalar_one_or_none()
    if not hdr:
        return [(sku, qty)]

    # Get details
    details = (
        db.execute(select(BOMDetail).filter(BOMDetail.bom_header_id == hdr.id))
        .scalars()
        .all()
    )
    if not details:
        return [(sku, qty)]

    resolved = []
    for detail in details:
        comp_sku = detail.component_sku
        comp_qty = qty * (detail.quantity_standard or 1)
        resolved.extend(resolve_standard_bom(comp_sku, comp_qty, db))
    return resolved


def resolve_shopee_item_bom(
    item_id: Optional[int],
    model_id: Optional[int],
    item_sku: Optional[str],
    model_sku: Optional[str],
    qty: int,
    db: Session,
) -> List[tuple[str, int]]:
    # 1. Check Marketplace BOM
    shopee_id = model_id if (model_id and model_id != 0) else item_id
    if shopee_id:
        mp_hdr = db.execute(
            select(BOMHeaderMarketplace).filter(
                BOMHeaderMarketplace.shopee_id == shopee_id
            )
        ).scalar_one_or_none()

        if mp_hdr:
            mp_details = (
                db.execute(
                    select(BOMDetailMarketplace).filter(
                        BOMDetailMarketplace.shopee_id == shopee_id
                    )
                )
                .scalars()
                .all()
            )
            if mp_details:
                resolved = []
                for detail in mp_details:
                    comp_sku = detail.component_sku
                    comp_qty = qty * (detail.quantity_standard or 1)
                    resolved.extend(resolve_standard_bom(comp_sku, comp_qty, db))
                return resolved

    # 2. Check Shopee Item Mapping (shopee_items table)
    mapped_sku = None
    if shopee_id:
        shopee_item = (
            db.execute(
                select(ShopeeItem).filter(
                    (ShopeeItem.model_id == str(shopee_id))
                    | (ShopeeItem.item_id == str(shopee_id))
                )
            )
            .scalars()
            .first()
        )
        if shopee_item and shopee_item.sku:
            mapped_sku = shopee_item.sku

    if not mapped_sku:
        # Fallback to model_sku / item_sku
        mapped_sku = model_sku if model_sku else item_sku

    if not mapped_sku:
        return []

    mapped_sku = mapped_sku.strip()
    return resolve_standard_bom(mapped_sku, qty, db)


def build_shopee_order_response(order: ShopeeOrder, db: Session) -> ShopeeOrderResponse:
    # Decompose items and group by SKU
    resolved_items = {}
    for item in order.item_list:
        components = resolve_shopee_item_bom(
            item_id=item.item_id,
            model_id=item.model_id,
            item_sku=item.item_sku,
            model_sku=item.model_sku,
            qty=item.model_quantity_purchased or 0,
            db=db,
        )
        for comp_sku, comp_qty in components:
            resolved_items[comp_sku] = resolved_items.get(comp_sku, 0) + comp_qty

    # Fetch names and locations for component SKUs
    sku_list = list(resolved_items.keys())
    item_details = {}
    if sku_list:
        items_db = (
            db.execute(
                select(WarehouseItem)
                .options(selectinload(WarehouseItem.stocks))
                .filter(WarehouseItem.sku.in_(sku_list))
            )
            .scalars()
            .all()
        )
        item_details = {item.sku: (item.item_name, item.location) for item in items_db}

    # Construct ShopeeOrderItemBOMResponse list
    item_responses = []
    for comp_sku, comp_qty in resolved_items.items():
        name, location = item_details.get(comp_sku, (None, None))
        item_responses.append(
            ShopeeOrderItemBOMResponse(
                component_sku=comp_sku,
                component_name=name or comp_sku,
                quantity=comp_qty,
                location=location,
            )
        )

    recipient_address = None
    if order.recipient_address:
        recipient_address = ShopeeOrderRecipientResponse.model_validate(
            order.recipient_address
        )

    info_list = []
    if order.info:
        info_list = [ShopeeOrderInfoResponse.model_validate(order.info)]

    return ShopeeOrderResponse(
        order_sn=order.order_sn,
        split_up=order.split_up,
        status=order.status,
        ship_by=order.ship_by,
        owner_user=order.owner_user,
        shipping_carrier=order.shipping_carrier,
        done=order.done,
        done_at=order.done_at,
        item_list=item_responses,
        recipient_address=recipient_address,
        info=info_list,
    )


def get_standard_bom_node(
    sku: str,
    qty: int,
    is_not_primary_child: Optional[bool],
    db: Session,
    visited: Optional[set] = None,
) -> dict:
    if visited is None:
        visited = set()

    item = db.execute(
        select(WarehouseItem).filter(WarehouseItem.sku == sku)
    ).scalar_one_or_none()
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
        node["name"] = f"{name} (Cycle Detected)"
        return node

    new_visited = visited | {sku}

    hdr = db.execute(
        select(BOMHeader).filter(BOMHeader.sku == sku)
    ).scalar_one_or_none()
    if hdr:
        details = (
            db.execute(select(BOMDetail).filter(BOMDetail.bom_header_id == hdr.id))
            .scalars()
            .all()
        )
        for detail in details:
            child_node = get_standard_bom_node(
                detail.component_sku,
                detail.quantity_standard or 1,
                detail.is_not_primary_child,
                db,
                new_visited,
            )
            node["children"].append(child_node)

    return node


def get_marketplace_bom_node(shopee_id: int, db: Session) -> Optional[dict]:
    hdr = db.execute(
        select(BOMHeaderMarketplace).filter(BOMHeaderMarketplace.shopee_id == shopee_id)
    ).scalar_one_or_none()
    if not hdr:
        return None

    name = f"{hdr.item_name or ''} - {hdr.model_name or ''}".strip()
    node = {
        "shopee_id": shopee_id,
        "name": name,
        "quantity": hdr.quantity_standard or 1,
        "type": "marketplace",
        "children": [],
    }

    details = (
        db.execute(
            select(BOMDetailMarketplace).filter(
                BOMDetailMarketplace.shopee_id == shopee_id
            )
        )
        .scalars()
        .all()
    )
    for detail in details:
        child_node = get_standard_bom_node(
            detail.component_sku,
            detail.quantity_standard or 1,
            detail.is_not_primary_child,
            db,
        )
        node["children"].append(child_node)

    return node
