"""Batched order payloads (IMPLEMENTATION_PLAN T4.5, F-H2).

``build_order_responses`` turns a list of loaded ``ShopeeOrder`` rows into API/WS payloads
with a bounded number of queries: marketplace BOMs (2), standard BOMs (2 per BOM depth
level), and warehouse items with their bins (2), independent of the number of orders.

The expansion matches the previous per-order implementation exactly:

* a sold item resolves to its marketplace BOM (by ``model_id`` or ``item_id``), else to the
  standard BOM of its SKU, else to the warehouse item itself
* BOM trees are flattened to leaves; a cycle or an empty BOM makes the node a leaf
* components are summed per ``(sku, name, location)`` in first-seen order
"""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    BOMDetail,
    BOMDetailMarketplace,
    BOMHeader,
    BOMHeaderMarketplace,
    ShopeeOrder,
    ShopeeOrderInfoResponse,
    ShopeeOrderItemBOMResponse,
    ShopeeOrderRecipientResponse,
    ShopeeOrderResponse,
    WarehouseItem,
)

Leaf = tuple[str, str, int, Optional[str]]  # sku, name, quantity, location


class _Catalog:
    """Per-request cache of BOMs and warehouse items."""

    def __init__(self, db: Session):
        self.db = db
        self.items: dict[str, Optional[WarehouseItem]] = {}
        # sku -> [(component_sku, quantity_standard)], [] for an empty BOM, None for no BOM
        self.standard: dict[str, Optional[list[tuple[str, int]]]] = {}
        # shopee_id -> (name, multiplier, [(component_sku, qty)]), None for no BOM
        self.marketplace: dict[int, Optional[tuple[str, int, list[tuple[str, int]]]]] = {}

    def load_marketplace(self, ids: Iterable[int]) -> None:
        missing = {i for i in ids if i and i not in self.marketplace}
        if not missing:
            return
        headers = self.db.execute(
            select(BOMHeaderMarketplace).filter(BOMHeaderMarketplace.shopee_id.in_(missing))
        ).scalars()
        found: dict[int, tuple[str, int, list[tuple[str, int]]]] = {
            h.shopee_id: (
                h.item_name or f"Marketplace Item {h.shopee_id}",
                h.quantity_standard or 1,
                [],
            )
            for h in headers
        }
        if found:
            details = self.db.execute(
                select(BOMDetailMarketplace)
                .filter(BOMDetailMarketplace.shopee_id.in_(list(found)))
                .order_by(BOMDetailMarketplace.id)
            ).scalars()
            for d in details:
                found[d.shopee_id][2].append((d.component_sku, d.quantity_standard or 1))
        for i in missing:
            self.marketplace[i] = found.get(i)

    def load_standard_closure(self, skus: Iterable[str]) -> None:
        """Load standard BOMs for ``skus`` and, level by level, for all their components."""
        frontier = {s for s in skus if s and s not in self.standard}
        while frontier:
            headers = {
                h.id: h.sku
                for h in self.db.execute(
                    select(BOMHeader).filter(BOMHeader.sku.in_(frontier))
                ).scalars()
            }
            found: dict[str, list[tuple[str, int]]] = {sku: [] for sku in headers.values()}
            if headers:
                details = self.db.execute(
                    select(BOMDetail)
                    .filter(BOMDetail.bom_header_id.in_(list(headers)))
                    .order_by(BOMDetail.id)
                ).scalars()
                for d in details:
                    found[headers[d.bom_header_id]].append((d.component_sku, d.quantity_standard))
            for sku in frontier:
                self.standard[sku] = found.get(sku)
            frontier = {
                child
                for children in found.values()
                for child, _ in children
                if child not in self.standard
            }

    def load_items(self, skus: Iterable[str]) -> None:
        missing = {s for s in skus if s and s not in self.items}
        if not missing:
            return
        # WarehouseItem.stocks is lazy="selectin": one extra query for all bins.
        rows = self.db.execute(select(WarehouseItem).filter(WarehouseItem.sku.in_(missing)))
        found = {i.sku: i for i in rows.scalars()}
        for sku in missing:
            self.items[sku] = found.get(sku)

    def all_standard_skus(self) -> set[str]:
        skus = set(self.standard)
        for children in self.standard.values():
            skus.update(child for child, _ in children or [])
        return skus

    # ------------------------------------------------------------------ expansion
    def _item_location(self, sku: str) -> Optional[str]:
        item = self.items.get(sku)
        return item.location if item else None

    def standard_leaves(self, sku: str, qty: int, visited: frozenset = frozenset()) -> list[Leaf]:
        children = self.standard.get(sku)
        if sku in visited or not children:
            item = self.items.get(sku)
            name = (item.item_name if item else None) or sku
            return [(sku, name, qty, self._item_location(sku))]
        leaves: list[Leaf] = []
        for child, quantity_standard in children:
            leaves.extend(self.standard_leaves(child, quantity_standard * qty, visited | {sku}))
        return leaves

    def marketplace_leaves(self, shopee_id: int, qty: int) -> Optional[list[Leaf]]:
        bom = self.marketplace.get(shopee_id)
        if bom is None:
            return None
        name, multiplier, children = bom
        total = qty * multiplier
        if not children:
            mp_sku = f"MP:{shopee_id}"
            return [(mp_sku, name, total, None)]
        leaves: list[Leaf] = []
        for child, quantity in children:
            leaves.extend(self.standard_leaves(child, quantity * total))
        return leaves


def _components(order: ShopeeOrder, catalog: _Catalog) -> list[ShopeeOrderItemBOMResponse]:
    totals: dict[tuple[str, str, Optional[str]], int] = {}
    for raw in order.item_list or []:
        sku = raw.model_sku or raw.item_sku or ""
        shopee_id = raw.model_id or raw.item_id
        qty = raw.model_quantity_purchased or 1
        leaves = catalog.marketplace_leaves(shopee_id, qty) if shopee_id else None
        if leaves is None and sku and catalog.standard.get(sku) is not None:
            leaves = catalog.standard_leaves(sku, qty)
        if leaves is None:
            item = catalog.items.get(sku)
            name = (item.item_name if item else None) or raw.item_name or sku
            leaves = [(sku, name, qty, catalog._item_location(sku))]
        for leaf_sku, name, quantity, location in leaves:
            key = (leaf_sku, name, location)
            totals[key] = totals.get(key, 0) + quantity
    return [
        ShopeeOrderItemBOMResponse(
            component_sku=sku, component_name=name, quantity=qty, location=location
        )
        for (sku, name, location), qty in totals.items()
    ]


def build_order_responses(db: Session, orders: list[ShopeeOrder]) -> list[ShopeeOrderResponse]:
    catalog = _Catalog(db)
    raws = [raw for order in orders for raw in order.item_list or []]
    catalog.load_marketplace(raw.model_id or raw.item_id for raw in raws)
    mp_children = [c for bom in catalog.marketplace.values() if bom for c, _ in bom[2]]
    raw_skus = [raw.model_sku or raw.item_sku or "" for raw in raws]
    catalog.load_standard_closure([*mp_children, *raw_skus])
    catalog.load_items([*catalog.all_standard_skus(), *raw_skus])

    responses = []
    for order in orders:
        infos = sorted(order.info or [], key=lambda i: i.id)
        responses.append(
            ShopeeOrderResponse(
                order_sn=order.order_sn,
                split_up=order.split_up,
                status=order.status,
                ship_by=order.ship_by,
                owner_user=order.owner_user,
                shipping_carrier=order.shipping_carrier,
                done=order.done,
                done_at=order.done_at,
                info=[ShopeeOrderInfoResponse.model_validate(i) for i in infos],
                recipient_address=(
                    ShopeeOrderRecipientResponse.model_validate(order.recipient_address)
                    if order.recipient_address
                    else None
                ),
                item_list=_components(order, catalog),
            )
        )
    return responses
