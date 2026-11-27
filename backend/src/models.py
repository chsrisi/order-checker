from __future__ import annotations
import re
from enum import Enum as PyEnum
from datetime import date, datetime, UTC
from typing import List, Optional, Union, Annotated, Any, Literal

from sqlalchemy import CheckConstraint, Integer, String, DateTime, ForeignKey, Boolean, BigInteger, Float, Index, text
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase
from sqlalchemy.ext.associationproxy import association_proxy, AssociationProxy
from pydantic import (
    AfterValidator,
    PlainSerializer,
    WithJsonSchema,
    BaseModel,
    ConfigDict,
    Discriminator,
    Tag,
    field_validator,
    model_validator,
    Field,
)

from .timezone import as_utc


def _iso_utc_z(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


# F-M6 / T4.6: every API and WS datetime is UTC with a ``Z`` suffix, e.g.
# ``2026-11-20T21:05:00.123456Z``, which Dart's DateTime.parse reads as UTC.
UTCDateTime = Annotated[
    datetime,
    AfterValidator(as_utc),
    PlainSerializer(_iso_utc_z, return_type=str, when_used="json"),
    # keep the documented contract shape (string, date-time) for the serialized form
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]


class Base(DeclarativeBase):
    pass


# Enums ----
class WSMessageType(str, PyEnum):
    OUTBOUNDS = "outbound_update"
    USERS = "users_update"
    SHOPEE_ORDERS = "shopee_orders_update"
    PICK_ITEM_ENTRIES = "pick_item_entries_update"
    STOCKS = "stocks_update"
    LOGIN_REQUESTS = "login_requests_update"
    DEVICES = "devices_update"  # admins only (T8.4a)
    ERROR = "error"


class ShopeeOrderStatus(str, PyEnum):
    UNPAID = "UNPAID"
    READY_TO_SHIP = "READY_TO_SHIP"
    PROCESSED = "PROCESSED"
    SHIPPED = "SHIPPED"
    TO_CONFIRM_RECEIVE = "TO_CONFIRM_RECEIVE"
    COMPLETED = "COMPLETED"
    RETRY_SHIP = "RETRY_SHIP"
    IN_CANCEL = "IN_CANCEL"
    CANCELLED = "CANCELLED"
    TO_RETURN = "TO_RETURN"


class ShopeeLogisticsStatus(str, PyEnum):
    NOT_START = "LOGISTICS_NOT_START"
    READY = "LOGISTICS_READY"
    REQUEST_CREATED = "LOGISTICS_REQUEST_CREATED"
    PICKUP_DONE = "LOGISTICS_PICKUP_DONE"
    DELIVERY_DONE = "LOGISTICS_DELIVERY_DONE"
    INVALID = "LOGISTICS_INVALID"
    REQUEST_CANCELLED = "LOGISTICS_REQUEST_CANCELLED"
    PICKUP_FAILED = "LOGISTICS_PICKUP_FAILED"
    PICKUP_RETRY = "LOGISTICS_PICKUP_RETRY"
    DELIVERY_FAILED = "LOGISTICS_DELIVERY_FAILED"
    LOST = "LOGISTICS_LOST"


# SQLAlchemy Models ----
# auth
class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}
    username: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String)  # TODO: refactor to use scope based permissions

    orders: Mapped[List["ShopeeOrder"]] = relationship("ShopeeOrder", back_populates="owner")
    pies: Mapped[List["PickItemEntry"]] = relationship("PickItemEntry", back_populates="owner")
    outbounds: Mapped[List["OutboundItem"]] = relationship("OutboundItem", back_populates="owner")


class AuthSession(Base):
    """One login (V2_DELTA D3.2, IMPLEMENTATION_PLAN T6.2). Its id is the ``sid`` claim of every
    access and refresh token issued for that login; rotation keeps it. A session is live while
    ``revoked_at`` is NULL. Revoking (logout, password reset, admin "log out everywhere")
    sets ``revoked_at`` and deletes its refresh tokens, so the next request with any of its
    tokens gets 401. Rows are removed by the refresh-cleanup task once ``expires_at`` passed."""

    __tablename__ = "sessions"
    __table_args__ = {"schema": "auth"}
    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(ForeignKey("auth.users.username"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[Optional[str]] = mapped_column(String)
    agent: Mapped[Optional[str]] = mapped_column(String)
    # The v2 device this session registered from (T6.6); NULL for v1 apps and the admin.
    device_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("auth.devices.id", ondelete="SET NULL"), index=True
    )


DEVICE_STATUSES = ("pending", "active", "revoked")


class Device(Base):
    """A v2 operator device, identified by its Android Keystore public key (V2_SPEC §4A,
    IMPLEMENTATION_PLAN T6.6). Registered as ``pending`` at the first login; approval,
    revocation and the device credential (``token_hash``) come in step 8."""

    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'revoked')", name="ck_devices_status"
        ),
        {"schema": "auth"},
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[Optional[str]] = mapped_column(String)
    model: Mapped[Optional[str]] = mapped_column(String)
    android_version: Mapped[Optional[str]] = mapped_column(String)
    app_version_code: Mapped[Optional[int]] = mapped_column(Integer)
    # Base64 DER SubjectPublicKeyInfo of the device's P-256 key.
    public_key: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    token_hash: Mapped[Optional[str]] = mapped_column(String)
    # The operator who last registered or used it. ("current_user" is reserved in SQL.)
    current_username: Mapped[Optional[str]] = mapped_column(
        ForeignKey("auth.users.username", ondelete="SET NULL")
    )
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class DeviceRegisterRequest(BaseModel):
    public_key: str = Field(
        max_length=1024, description="Base64 DER SubjectPublicKeyInfo of an EC P-256 key."
    )
    model: str = Field(max_length=128)
    android_version: str = Field(max_length=32)
    app_version_code: int = Field(ge=0)
    signature: str = Field(
        max_length=512,
        description=(
            "Base64 DER ECDSA signature (SHA-256) over the UTF-8 `sid` claim of the caller's "
            "access token, made with the Keystore private key."
        ),
    )


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    label: Optional[str] = None
    model: Optional[str] = None
    android_version: Optional[str] = None
    app_version_code: Optional[int] = None
    current_username: Optional[str] = None
    enrolled_at: UTCDateTime
    last_seen_at: Optional[UTCDateTime] = None


DEVICE_ASSIGN_MODES = ("direct", "preselect")


class AdminDeviceAssignment(BaseModel):
    """A worker switch waiting for the device (T8.4a)."""

    username: str
    mode: Literal["direct", "preselect"]
    admin: str
    created_at: UTCDateTime
    expires_at: UTCDateTime


class AdminDeviceLastAssignment(BaseModel):
    """What happened to the device's last assignment, kept for an hour."""

    username: str
    mode: Literal["direct", "preselect"]
    admin: str
    outcome: Literal["collected", "expired", "replaced", "cancelled", "invalid"] = Field(
        description="`invalid`: the worker was deleted, had their password reset or became "
        "an admin before the device collected it, or the device was revoked."
    )
    at: UTCDateTime


class AdminDeviceResponse(DeviceResponse):
    """Admin listing: the device plus whether one of its sessions has a live socket now
    (V2_DELTA D8 / Q35). ``last_seen_at`` only moves on HTTP requests, so an idle but connected
    device would otherwise look stale."""

    online: bool = False
    reachable: bool = Field(
        False,
        description=(
            "The device polled its state within the last 30 s (it is on its login screen). "
            "With `online` false: logged out but reachable (P-27)."
        ),
    )
    assignment: Optional[AdminDeviceAssignment] = Field(
        None, description="A worker switch waiting for the device to collect it."
    )
    last_assignment: Optional[AdminDeviceLastAssignment] = None


class AdminDeviceUpdate(BaseModel):
    label: Optional[str] = Field(
        None,
        max_length=40,
        description="The name the console shows, e.g. `MT67-2`. Empty or null clears it.",
    )

    @field_validator("label")
    @classmethod
    def strip_label(cls, v: Optional[str]) -> Optional[str]:
        v = v.strip() if v is not None else None
        return v or None


class AdminDeviceAssign(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    mode: Literal["direct", "preselect"] = Field(
        "direct",
        description=(
            "`direct`: the device is logged in as the worker without a password (needs an "
            "`active` device). `preselect`: the login screen selects the worker and asks for "
            "the password."
        ),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": "auth"}
    jti: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(ForeignKey("auth.users.username"))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("auth.sessions.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[Optional[str]] = mapped_column(String)
    agent: Mapped[Optional[str]] = mapped_column(String)


# shopee
class ShopeeOrder(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": "shopee"}
    order_sn: Mapped[str] = mapped_column(String, index=True, primary_key=True)
    split_up: Mapped[bool] = mapped_column(Boolean)
    ship_by: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    owner_user: Mapped[Optional[str]] = mapped_column(ForeignKey("auth.users.username"))
    status: Mapped[str] = mapped_column(String)
    shipping_carrier: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[Optional["User"]] = relationship("User", back_populates="orders")
    item_list: Mapped[List["ShopeeOrderItemList"]] = relationship(
        "ShopeeOrderItemList", back_populates="order"
    )
    recipient_address: Mapped["ShopeeOrderRecipientAddress"] = relationship(
        "ShopeeOrderRecipientAddress", back_populates="order"
    )
    # One row per package; split orders have several (T4.5).
    info: Mapped[List["ShopeeOrderInfo"]] = relationship(
        "ShopeeOrderInfo", back_populates="order", order_by="ShopeeOrderInfo.id"
    )
    pies: Mapped[List["PickItemEntry"]] = relationship("PickItemEntry", back_populates="order")


class ShopeeOrderInfo(Base):
    __tablename__ = "order_info"
    __table_args__ = {"schema": "shopee"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_sn: Mapped[str] = mapped_column(ForeignKey("shopee.orders.order_sn"))
    package_number: Mapped[Optional[str]] = mapped_column(String)
    logistics_status: Mapped[Optional[str]] = mapped_column(String)
    tracking_number: Mapped[Optional[str]] = mapped_column(String, index=True)
    pickup_code: Mapped[Optional[str]] = mapped_column(String)
    note: Mapped[Optional[str]] = mapped_column(String)

    order: Mapped["ShopeeOrder"] = relationship("ShopeeOrder", back_populates="info")


class ShopeeOrderRecipientAddress(Base):
    __tablename__ = "order_recipient_address"
    __table_args__ = {"schema": "shopee"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_sn: Mapped[str] = mapped_column(ForeignKey("shopee.orders.order_sn"))
    name: Mapped[Optional[str]] = mapped_column(String)
    city: Mapped[Optional[str]] = mapped_column(String)

    order: Mapped["ShopeeOrder"] = relationship("ShopeeOrder", back_populates="recipient_address")


class ShopeeOrderItemList(Base):
    __tablename__ = "order_item_list"
    __table_args__ = {"schema": "shopee"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_sn: Mapped[str] = mapped_column(ForeignKey("shopee.orders.order_sn"))
    item_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    item_name: Mapped[Optional[str]] = mapped_column(String)
    item_sku: Mapped[Optional[str]] = mapped_column(String)
    model_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    model_name: Mapped[Optional[str]] = mapped_column(String)
    model_sku: Mapped[Optional[str]] = mapped_column(String)
    model_quantity_purchased: Mapped[Optional[int]] = mapped_column(Integer)
    image_url: Mapped[Optional[str]] = mapped_column(String)

    order: Mapped["ShopeeOrder"] = relationship("ShopeeOrder", back_populates="item_list")


# orders
class OutboundItem(Base):
    __tablename__ = "outbound_items"
    __table_args__ = {"schema": "orders"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    content: Mapped[str] = mapped_column(String, index=True)  # The scanned text
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    owner_user: Mapped[str] = mapped_column(ForeignKey("auth.users.username"))
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped["User"] = relationship("User", back_populates="outbounds")
    tags_rel: Mapped[List["OutboundTag"]] = relationship(
        "OutboundTag",
        back_populates="outbound",
        cascade="all, delete-orphan",
        lazy="joined",
    )
    tags: AssociationProxy[List[str]] = association_proxy(
        "tags_rel", "content", creator=lambda c: OutboundTag(content=c)
    )


class OutboundTag(Base):
    __tablename__ = "tags"
    __table_args__ = {"schema": "orders"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    outbound_id: Mapped[int] = mapped_column(
        ForeignKey("orders.outbound_items.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(String, index=True)

    outbound: Mapped["OutboundItem"] = relationship("OutboundItem", back_populates="tags_rel")


class PickItemEntry(Base):
    __tablename__ = "pick_item_entries"
    __table_args__ = {"schema": "orders"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sku: Mapped[str] = mapped_column(String, index=True)
    qty: Mapped[int] = mapped_column(Integer)
    order_sn: Mapped[Optional[str]] = mapped_column(
        ForeignKey("shopee.orders.order_sn"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    owner_user: Mapped[str] = mapped_column(ForeignKey("auth.users.username"))

    owner: Mapped["User"] = relationship("User", back_populates="pies")
    order: Mapped[Optional["ShopeeOrder"]] = relationship("ShopeeOrder", back_populates="pies")
    allocations: Mapped[List["PickStockAllocation"]] = relationship(
        "PickStockAllocation",
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="PickStockAllocation.id",
    )


class PickStockAllocation(Base):
    """Where a pick entry's deducted stock came from (delta D4.3 rule 1): the restore source.

    ``sum(qty)`` can be lower than the entry's ``qty`` when the pick found too little stock
    (shortfall); only allocated quantity is ever restored."""

    __tablename__ = "pick_stock_allocations"
    __table_args__ = {"schema": "orders"}
    id: Mapped[int] = mapped_column(primary_key=True)
    pick_entry_id: Mapped[int] = mapped_column(
        ForeignKey("orders.pick_item_entries.id", ondelete="CASCADE"), index=True
    )
    sku: Mapped[str] = mapped_column(String)
    location: Mapped[Optional[str]] = mapped_column(String)
    qty: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    entry: Mapped["PickItemEntry"] = relationship("PickItemEntry", back_populates="allocations")


# warehouse
class WarehouseItem(Base):
    __tablename__ = "items"
    __table_args__ = {"schema": "warehouse"}
    sku: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    item_name: Mapped[Optional[str]] = mapped_column(String, index=True)
    uom: Mapped[Optional[str]] = mapped_column(String)
    manufacturer: Mapped[Optional[str]] = mapped_column(String)
    item_name_manufacturer: Mapped[Optional[str]] = mapped_column(String)
    dimension_notes: Mapped[Optional[str]] = mapped_column(String)
    sell_price: Mapped[Optional[float]] = mapped_column(Float)
    manufacturer_price: Mapped[Optional[float]] = mapped_column(Float)
    price_before_discount_tax: Mapped[Optional[float]] = mapped_column(Float)
    jar_length: Mapped[Optional[float]] = mapped_column(Float)  # dim 1
    jar_width: Mapped[Optional[float]] = mapped_column(Float)  # dim 1
    jar_height: Mapped[Optional[float]] = mapped_column(Float)  # dim 1
    box_length: Mapped[Optional[float]] = mapped_column(Float)
    box_width: Mapped[Optional[float]] = mapped_column(Float)
    box_height: Mapped[Optional[float]] = mapped_column(Float)
    qty_per_box: Mapped[Optional[str]] = mapped_column(String)
    qty_per_pack: Mapped[Optional[float]] = mapped_column(Float)
    boxes_per_bundle: Mapped[Optional[float]] = mapped_column(Float)
    whole_uom: Mapped[Optional[str]] = mapped_column(String)
    whole_deno: Mapped[Optional[float]] = mapped_column(Float)
    jar_group: Mapped[Optional[str]] = mapped_column(String)
    moq: Mapped[Optional[float]] = mapped_column(Float)
    price_list_name: Mapped[Optional[str]] = mapped_column(String)
    item_group: Mapped[Optional[str]] = mapped_column(String)
    sell_price_bh: Mapped[Optional[float]] = mapped_column(Float)
    weight_per_pcs: Mapped[Optional[float]] = mapped_column(Float)
    hide_in_price_list: Mapped[Optional[bool]] = mapped_column(Boolean)
    sku_factory: Mapped[Optional[str]] = mapped_column(String)
    is_parent: Mapped[Optional[bool]] = mapped_column(Boolean)
    is_child: Mapped[Optional[bool]] = mapped_column(Boolean)
    sell_price_tokped: Mapped[Optional[float]] = mapped_column(Float)
    jar_type: Mapped[Optional[str]] = mapped_column(String)
    jar_capacity_gr: Mapped[Optional[float]] = mapped_column(Float)
    top_length: Mapped[Optional[float]] = mapped_column(Float)  # dim 2
    top_width: Mapped[Optional[float]] = mapped_column(Float)  # dim 2
    bottom_length: Mapped[Optional[float]] = mapped_column(Float)  # dim 2
    bottom_width: Mapped[Optional[float]] = mapped_column(Float)  # dim 2
    height: Mapped[Optional[float]] = mapped_column(Float)  # dim 2
    sales_commission_percent: Mapped[Optional[float]] = mapped_column(Float)
    salesman_base_kelp_order: Mapped[Optional[float]] = mapped_column(Float)
    salesman_base_uom_order: Mapped[Optional[str]] = mapped_column(String)
    salesman_base_price_list_intv: Mapped[Optional[float]] = mapped_column(Float)
    salesman_whole_uom_order: Mapped[Optional[str]] = mapped_column(String)
    salesman_group_barang: Mapped[Optional[str]] = mapped_column(String)
    exclude_stock_control: Mapped[Optional[bool]] = mapped_column(Boolean)
    note: Mapped[Optional[str]] = mapped_column(String)
    update_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    volume_m3: Mapped[Optional[float]] = mapped_column(Float)
    picture: Mapped[Optional[str]] = mapped_column(String)
    lid_type: Mapped[Optional[str]] = mapped_column(String)
    category: Mapped[Optional[str]] = mapped_column(String)
    desc_label: Mapped[Optional[str]] = mapped_column(String)
    supplier_barcode: Mapped[Optional[str]] = mapped_column(String)
    item_value_intv: Mapped[Optional[float]] = mapped_column(Float)
    item_value_target: Mapped[Optional[float]] = mapped_column(Float)
    photo: Mapped[Optional[str]] = mapped_column(String)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float)

    stocks: Mapped[List["Stock"]] = relationship("Stock", back_populates="item", lazy="selectin")

    @property
    def location(self) -> Optional[str]:
        if self.stocks:
            unique_locs = sorted(list({s.location for s in self.stocks if s.location}))
            if unique_locs:
                return ", ".join(unique_locs)
        return None


class Stock(Base):
    # one (WarehouseItem) to many (Stock); at most one row per (sku, location), NULL included
    __tablename__ = "stocks"
    __table_args__ = (
        Index(
            "uq_stocks_sku_location",
            "sku",
            text("coalesce(location, '')"),
            unique=True,
        ),
        {"schema": "warehouse"},
    )
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sku: Mapped[str] = mapped_column(ForeignKey("warehouse.items.sku"))
    stock: Mapped[int] = mapped_column(Integer)
    location: Mapped[Optional[str]] = mapped_column(String)

    item: Mapped["WarehouseItem"] = relationship("WarehouseItem", back_populates="stocks")


class StocksLog(Base):
    """Stock audit trail. ``message`` is the legacy free-text form; rows written since T4.3
    also carry the structured fields (``reason`` values: see queries/stocks.py REASONS)."""

    __tablename__ = "stocks_log"
    __table_args__ = {"schema": "warehouse"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    message: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    sku: Mapped[Optional[str]] = mapped_column(String, index=True)
    location: Mapped[Optional[str]] = mapped_column(String)
    delta: Mapped[Optional[int]] = mapped_column(Integer)
    before: Mapped[Optional[int]] = mapped_column(Integer)
    after: Mapped[Optional[int]] = mapped_column(Integer)
    reason: Mapped[Optional[str]] = mapped_column(String)
    actor: Mapped[Optional[str]] = mapped_column(String)
    ref_type: Mapped[Optional[str]] = mapped_column(String)
    ref_id: Mapped[Optional[str]] = mapped_column(String)


class BOMHeader(Base):
    __tablename__ = "bom_headers"
    __table_args__ = {"schema": "warehouse"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String, ForeignKey("warehouse.items.sku"), unique=True)
    quantity_standard: Mapped[Optional[int]] = mapped_column(Integer)
    factor_f5: Mapped[Optional[float]] = mapped_column(Float)


class BOMDetail(Base):
    __tablename__ = "bom_details"
    __table_args__ = {"schema": "warehouse"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_header_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouse.bom_headers.id"))
    component_sku: Mapped[str] = mapped_column(String, ForeignKey("warehouse.items.sku"))
    quantity_standard: Mapped[int] = mapped_column(Integer)
    is_not_primary_child: Mapped[Optional[bool]] = mapped_column(Boolean)


class BOMHeaderMarketplace(Base):
    __tablename__ = "bom_headers_marketplace"
    __table_args__ = {"schema": "warehouse"}
    shopee_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_name: Mapped[Optional[str]] = mapped_column(String)
    model_name: Mapped[Optional[str]] = mapped_column(String)
    quantity_standard: Mapped[Optional[int]] = mapped_column(Integer)
    marketplace: Mapped[Optional[str]] = mapped_column(String)
    created_date: Mapped[Optional[datetime]] = mapped_column(DateTime)


class BOMDetailMarketplace(Base):
    __tablename__ = "bom_details_marketplace"
    __table_args__ = {"schema": "warehouse"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shopee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("warehouse.bom_headers_marketplace.shopee_id"),
    )
    component_sku: Mapped[str] = mapped_column(String, ForeignKey("warehouse.items.sku"))
    quantity_standard: Mapped[Optional[int]] = mapped_column(Integer)
    is_not_primary_child: Mapped[Optional[bool]] = mapped_column(Boolean)
    created_date: Mapped[Optional[datetime]] = mapped_column(DateTime)


class ShopeeItem(Base):
    __tablename__ = "shopee_items"
    __table_args__ = {"schema": "warehouse"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[Optional[str]] = mapped_column(String)
    item_name: Mapped[Optional[str]] = mapped_column(String)
    model_id: Mapped[Optional[str]] = mapped_column(String)
    model_name: Mapped[Optional[str]] = mapped_column(String)
    has_variant: Mapped[Optional[bool]] = mapped_column(Boolean)
    sku: Mapped[Optional[str]] = mapped_column(String, ForeignKey("warehouse.items.sku"))
    sell_price_factor: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    factor_x: Mapped[Optional[float]] = mapped_column(Float)
    factor_plus: Mapped[Optional[float]] = mapped_column(Float)


# Pydantic Models ----
# Request size limits (IMPLEMENTATION_PLAN T2.14). They bound abusive input; real scanner
# payloads (including multi-line QR content) stay far below them.
SCAN_MAX_LENGTH = 1024
ORDER_SN_MAX_LENGTH = 64
LOCATION_MAX_LENGTH = 128
TAG_MAX_LENGTH = 64
TAGS_MAX_ITEMS = 16
CLOSE_MAX_ITEMS = 10_000

class OutboundCreate(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=SCAN_MAX_LENGTH,
        description="Order number or shipping label value.",
        examples=["240719ABC123"],
    )
    tags: Optional[List[Annotated[str, Field(max_length=TAG_MAX_LENGTH)]]] = Field(
        default=None,
        max_length=TAGS_MAX_ITEMS,
        description="Optional scanner-supplied classification tags.",
    )


class OutboundResponse(BaseModel):
    id: int
    content: str
    tags: List[str] = Field(default_factory=list)
    created_at: UTCDateTime
    owner_user: str
    closed: bool = False
    closed_at: Optional[UTCDateTime] = None

    model_config = ConfigDict(from_attributes=True)


class WarehouseItemResponse(BaseModel):
    sku: str
    item_name: Optional[str] = None
    location: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str = Field(description="Short-lived RS256 bearer token.")
    refresh_token: str = Field(description="Single-use-on-refresh token valid for 24 hours.")
    token_type: Literal["bearer"] = "bearer"


class UserAuth(BaseModel):
    username: str = Field(min_length=1, max_length=64, examples=["operator_1"])
    password: str = Field(min_length=1, max_length=256, examples=["correct-horse-battery-staple"])

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username can only contain alphanumeric characters, and underscores.")
        return v


NONCE_PATTERN = r"^[A-Za-z0-9_-]{16,64}$"


# Device state polls (T8.4a, P-25): the device's Unix time, a dash, then random characters.
DEVICE_NONCE_PATTERN = r"^[0-9]{10}-[A-Za-z0-9_]{8,48}$"


class DeviceStateRequest(BaseModel):
    """A signature by the registered device key over ``oc-device:state:<device_id>:<nonce>``."""

    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    nonce: str = Field(
        pattern=DEVICE_NONCE_PATTERN,
        description=(
            "`<unix seconds>-<8–48 random [A-Za-z0-9_]>`, fresh per call. Refused when the time "
            "is more than 5 minutes off the server's, or the nonce was used before."
        ),
    )
    signature: str = Field(
        max_length=512,
        description=(
            "Base64 DER ECDSA signature (SHA-256) over the UTF-8 string "
            "`oc-device:state:<device_id>:<nonce>`."
        ),
    )


class DeviceStateAssignment(BaseModel):
    username: str
    mode: Literal["direct", "preselect"] = Field(
        description="`direct`: `tokens` hold the new session. `preselect`: select the worker "
        "and ask for the password."
    )
    tokens: Optional[Token] = Field(None, description="Only with `direct`, handed over once.")


class DeviceLogoutReason(BaseModel):
    kind: Literal["logout", "switch"] = Field(
        description="`logout`: the admin logged this device out. `switch`: the admin switched "
        "it to `username`."
    )
    username: Optional[str] = None


class DeviceStateResponse(BaseModel):
    assignment: Optional[DeviceStateAssignment] = Field(
        None, description="A worker switch by the admin, handed over once."
    )
    logout_reason: Optional[DeviceLogoutReason] = Field(
        None,
        description="Why the device was last logged out by the admin, given once (W8).",
    )


class LoginRequestProof(BaseModel):
    """A signature by the device key over ``oc-login-request:<action>:<subject>:<nonce>``:
    action ``create`` (subject: the username), ``poll`` or ``cancel`` (subject: the id)."""

    nonce: str = Field(pattern=NONCE_PATTERN, description="Fresh per call; never reused.")
    signature: str = Field(
        max_length=512,
        description=(
            "Base64 DER ECDSA signature (SHA-256) over the UTF-8 string "
            "`oc-login-request:<create|poll|cancel>:<username or request id>:<nonce>`."
        ),
    )


class LoginRequestCreate(LoginRequestProof):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    public_key: str = Field(
        max_length=1024, description="Base64 DER SubjectPublicKeyInfo of the registered key."
    )


class LoginRequestCreated(BaseModel):
    id: str
    match_code: str = Field(description="Two digits, also shown to the admin.")
    expires_in: int = Field(description="Seconds an admin has to decide.")


class LoginRequestPoll(BaseModel):
    status: str = Field(
        description="`pending`, `approved`, `denied` or `expired` (also: cancelled, collected)."
    )
    tokens: Optional[Token] = Field(None, description="Only with `approved`, once.")


class AdminLoginRequest(BaseModel):
    id: str
    username: str
    match_code: str
    device_id: str
    device_name: str
    ip_address: Optional[str] = None
    created_at: UTCDateTime
    expires_at: UTCDateTime


class AdminUserCreate(UserAuth):
    """Admin-side operator creation (A-3). Reuses the ``UserAuth`` username rule."""

    password: str = Field(
        min_length=1,
        # HARDENING(password-min-length): to enforce, delete the line above and uncomment below.
        # min_length=8,
        max_length=256,
        examples=["correct-horse-battery-staple"],
    )


class AdminPasswordReset(BaseModel):
    password: str = Field(
        min_length=1,
        # HARDENING(password-min-length): to enforce, delete the line above and uncomment below.
        # min_length=8,
        max_length=256,
        examples=["correct-horse-battery-staple"],
    )


class UserResponse(BaseModel):
    username: str
    scope: str

    model_config = ConfigDict(from_attributes=True)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(
        min_length=1, description="Refresh token returned by login or registration."
    )


class BOMStandardHeaderResponse(BaseModel):
    id: int
    sku: str
    item_name: Optional[str] = None
    note: Optional[str] = None


class BOMMarketplaceHeaderResponse(BaseModel):
    shopee_id: int
    item_name: Optional[str] = None
    quantity_standard: Optional[int] = None


class BOMHeadersResponse(BaseModel):
    standard: List[BOMStandardHeaderResponse]
    marketplace: List[BOMMarketplaceHeaderResponse]


class BOMNodeResponse(BaseModel):
    """A resolved BOM node. ``is_not_primary_child`` exists on standard nodes only."""

    sku: str
    name: str
    quantity: int
    type: Literal["standard", "marketplace"]
    is_not_primary_child: Optional[bool] = None
    children: List["BOMNodeResponse"] = Field(default_factory=list)


class ShopeeOrderItemResponse(BaseModel):
    id: int
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    item_sku: Optional[str] = None
    model_id: Optional[int] = None
    model_name: Optional[str] = None
    model_sku: Optional[str] = None
    model_quantity_purchased: Optional[int] = None
    image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ShopeeOrderItemBOMResponse(BaseModel):
    component_sku: str
    component_name: Optional[str] = None
    quantity: int
    location: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ShopeeOrderRecipientResponse(BaseModel):
    id: int
    name: Optional[str] = None
    city: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ShopeeOrderInfoResponse(BaseModel):
    id: int
    package_number: Optional[str] = None
    logistics_status: Optional[str] = None
    tracking_number: Optional[str] = None
    pickup_code: Optional[str] = None
    note: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ShopeeOrderResponse(BaseModel):
    order_sn: str
    split_up: Optional[bool] = None
    status: str
    ship_by: UTCDateTime
    owner_user: Optional[str] = None
    shipping_carrier: Optional[str] = None
    done: bool = False
    done_at: Optional[UTCDateTime] = None
    item_list: List[ShopeeOrderItemBOMResponse] = Field(default_factory=list)
    recipient_address: Optional[ShopeeOrderRecipientResponse] = None
    info: List[ShopeeOrderInfoResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("info", mode="before")
    @classmethod
    def convert_info_to_list(cls, v: Any) -> Any:
        if v is None:
            _t: list[Any] = []
            return _t
        if not isinstance(v, list):
            return [v]
        return v


class ShopeeConfigUnlockRequest(BaseModel):
    password: str = Field(
        min_length=1, max_length=256, description="Current administrator password."
    )


class ShopeeConfigUpdateRequest(BaseModel):
    access_token: str = Field(
        min_length=1, description="Shopee access token; never returned in logs."
    )
    refresh_token: str = Field(
        min_length=1, description="Shopee refresh token; never returned in logs."
    )


class PickItemEntryCreate(BaseModel):
    sku: str = Field(
        min_length=1, max_length=SCAN_MAX_LENGTH, description="Warehouse SKU or recognized barcode."
    )
    qty: int = Field(gt=0, description="Quantity to add to the pick list.")
    order_sn: Optional[str] = Field(default=None, max_length=ORDER_SN_MAX_LENGTH)


class PickItemEntryResponse(BaseModel):
    id: int
    sku: str
    qty: int
    order_sn: Optional[str] = None
    timestamp: UTCDateTime
    owner_user: str
    item_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OrderPickRequest(BaseModel):
    """v2: add to, or take off, one order (the order is in the path)."""

    sku: str = Field(
        min_length=1, max_length=SCAN_MAX_LENGTH, description="Warehouse SKU or recognized barcode."
    )
    qty: int = Field(gt=0)


class OrderPickResponse(BaseModel):
    order_sn: str
    sku: str = Field(description="The resolved warehouse SKU.")
    qty: int = Field(ge=0, description="What the order now has of this SKU.")
    item_name: Optional[str] = None


class PickItemEntryAssign(BaseModel):
    order_sn: str = Field(
        min_length=1, max_length=ORDER_SN_MAX_LENGTH, description="Claimed Shopee order number."
    )
    qty: Optional[int] = Field(
        default=None, gt=0, description="Quantity to assign; defaults to the full entry."
    )

    model_config = ConfigDict(from_attributes=True)


class StockCreate(BaseModel):
    sku: str = Field(
        min_length=1, max_length=SCAN_MAX_LENGTH, description="Warehouse SKU or recognized barcode."
    )
    stock: int = Field(ge=0, description="Quantity to set/add, or transfer amount.")
    mode: Literal["add", "set"] = Field(
        default="set", description="Adjustment behavior when not transferring."
    )
    location: Optional[str] = Field(default=None, max_length=LOCATION_MAX_LENGTH)
    move_to: Optional[str] = Field(default=None, max_length=LOCATION_MAX_LENGTH)

    @model_validator(mode="after")
    def validate_transfer(self):
        if self.move_to is not None:
            if self.stock <= 0:
                raise ValueError("Transfer quantity must be positive")
            if self.location == self.move_to:
                raise ValueError("Source and destination locations must differ")
        return self


class StockResponse(BaseModel):
    id: int
    sku: str
    stock: int
    location: Optional[str] = None
    item_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PickItemEntryUnassign(BaseModel):
    order_sn: str = Field(min_length=1, max_length=ORDER_SN_MAX_LENGTH)
    sku: str = Field(min_length=1, max_length=SCAN_MAX_LENGTH)
    qty: int = Field(gt=0)


class MessageResponse(BaseModel):
    message: str


class DeleteCountResponse(MessageResponse):
    deleted: int = Field(ge=0)


class WebSocketTicketResponse(BaseModel):
    token: str = Field(description="One-use WebSocket ticket.")
    expires_in: int = Field(description="Ticket lifetime in seconds.", examples=[30])


class TemporaryTokenResponse(BaseModel):
    token: str = Field(description="Short-lived token for a protected follow-up operation.")
    expires_in: int = Field(description="Token lifetime in seconds.", examples=[120])


class ShopeeConfigResponse(BaseModel):
    access_token: str
    refresh_token: str
    current_ip: str


class AdminLookupResponse(BaseModel):
    """Where an exact label is (V2_ORDERS_DELTA Q49): its orders and its scans, open or closed."""

    label: str
    orders: List[ShopeeOrderResponse] = Field(
        description="Orders whose SN or a tracking number is the label (ongoing or done)."
    )
    scans: List[OutboundResponse] = Field(
        description="Scans of the label, open and closed, newest first."
    )
    day: Optional[date] = Field(None, description="The History day it left on, if it left.")


class AdminDayResponse(BaseModel):
    """One business day of History (V2_ORDERS_DELTA C2): scans count on the day they were made."""

    day: date
    outbound: int = Field(ge=0, description="Scans closed.")
    orders_done: int = Field(ge=0, description="Completed orders with a scan of that day.")
    tags: List[str] = Field(description="Distinct tags of the closed scans.")


class AdminDayDetailResponse(BaseModel):
    day: date
    orders: List[ShopeeOrderResponse]
    scans: List[OutboundResponse]


class OutboundCloseResponse(BaseModel):
    outbound: int = Field(ge=0, description="Scans closed.")
    unknown: int = Field(ge=0, description="Submitted values without an open scan.")
    orders_done: int = Field(ge=0, description="Orders marked complete.")


class StockChangeResponse(BaseModel):
    """One ``warehouse.stocks_log`` row for the console (T7.13). Rows from before T4.3 have only
    ``message``; the structured fields are then null."""

    id: int
    timestamp: UTCDateTime
    sku: Optional[str] = None
    item_name: Optional[str] = None
    location: Optional[str] = None
    delta: Optional[int] = None
    before: Optional[int] = None
    after: Optional[int] = None
    reason: Optional[str] = Field(
        default=None,
        description=(
            "adjust_set, adjust_add, transfer_out, transfer_in, pick, pick_shortfall, "
            "pick_restore, mode_merge, cutover_clear, migration_merge; null on legacy rows."
        ),
    )
    actor: Optional[str] = None
    ref_type: Optional[str] = Field(default=None, description="For example pick_entry or transfer.")
    ref_id: Optional[str] = None
    message: str
    order_sn: Optional[str] = Field(
        default=None, description="For picks: the order of the pick entry, while it exists."
    )


class StockUpdateResponse(BaseModel):
    success: bool
    sku: str
    stock: int
    item_name: Optional[str] = None
    location: Optional[str] = None


class ShopeeAcquireResponse(MessageResponse):
    order_sn: str


# Shopee Response Models ----
class ILImageInfo(BaseModel):
    image_url: str


class ODItemList(BaseModel):
    item_id: int
    item_name: str
    item_sku: str
    model_id: Optional[int] = None
    model_name: Optional[str] = None
    model_sku: Optional[str] = None
    model_quantity_purchased: int
    image_info: ILImageInfo


class ODRecipientAddress(BaseModel):
    name: str
    city: str


class ODPackageList(BaseModel):
    package_number: str
    logistics_status: str
    shipping_carrier: str


class ShpOrderDetails(BaseModel):
    order_sn: str
    order_status: str
    ship_by_date: datetime
    note: Optional[str] = None
    item_list: List[ODItemList]
    package_list: List[ODPackageList]
    split_up: bool
    recipient_address: ODRecipientAddress


class ShpOrderListItem(BaseModel):
    order_sn: str
    order_status: Optional[str] = None


class ShpOrderList(BaseModel):
    more: bool
    next_cursor: Optional[str] = None
    order_list: List[ShpOrderListItem]


class MTNFailList(BaseModel):
    package_number: str
    fail_reason: str


class MTNSuccessList(BaseModel):
    package_number: str
    tracking_number: str
    pickup_code: Optional[str] = None


class ShpMassTrackingNumber(BaseModel):
    success_list: List[MTNSuccessList]
    fail_list: List[MTNFailList]


class OrderListT(BaseModel):
    order_list: List[ShpOrderDetails]


class ShopeeTokenResponse(BaseModel):
    """Response model for /api/v2/auth/access_token/get"""

    error: Optional[str] = None
    message: Optional[str] = None
    request_id: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expire_in: Optional[int] = None


def get_payload(v: Any) -> str:
    if isinstance(v, ShpOrderList):
        return "ol"
    if isinstance(v, ShpMassTrackingNumber):
        return "mtn"
    if isinstance(v, OrderListT):
        return "olT"

    if isinstance(v, BaseModel):
        return v.__class__.__name__

    if isinstance(v, dict):
        if "order_list" in v and "more" in v:
            return "ol"
        if "success_list" in v and "fail_list" in v:
            return "mtn"
        if "order_list" in v:
            return "olT"

    raise TypeError(f"Unexpected payload type: {type(v)}")


PayloadType = Annotated[
    Union[
        Annotated[ShpOrderList, Tag("ol")],
        Annotated[ShpMassTrackingNumber, Tag("mtn")],
        Annotated[OrderListT, Tag("olT")],
    ],
    Discriminator(get_payload),
]


class ShopeeResponse(BaseModel):
    error: Optional[str] = None
    message: Optional[str] = None
    request_id: str
    response: Optional[PayloadType] = None
    warning: Optional[str] = None
