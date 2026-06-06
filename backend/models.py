from __future__ import annotations
import re
from enum import Enum as PyEnum
from datetime import datetime, UTC
from typing import List, Optional, Union, Annotated, Any

from sqlalchemy import Integer, String, DateTime, ForeignKey, Boolean, BigInteger
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Tag,
    field_validator,
    Field,
)


class Base(DeclarativeBase):
    pass


class ScanTag(str, PyEnum):
    TEST1 = "test1"
    TEST2 = "test2"


class WSMessageType(str, PyEnum):
    OUTBOUNDS = "outbound_update"
    USERS = "users_update"
    SHOPEE_ORDERS = "shopee_orders_update"
    PICK_ITEM_ENTRIES = "pick_item_entries_update"
    STOCKS = "stocks_update"
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
    scope: Mapped[str] = mapped_column(
        String
    )  # TODO: refactor to use scope based permissions

    orders: Mapped[List["ShopeeOrder"]] = relationship(
        "ShopeeOrder", back_populates="owner"
    )
    pies: Mapped[List["PickItemEntry"]] = relationship(
        "PickItemEntry", back_populates="owner"
    )
    outbounds: Mapped[List["OutboundItem"]] = relationship(
        "OutboundItem", back_populates="owner"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": "auth"}
    jti: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(ForeignKey("auth.users.username"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ip_address: Mapped[Optional[str]] = mapped_column(String)
    agent: Mapped[Optional[str]] = mapped_column(String)


# shopee
class ShopeeOrder(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": "shopee"}
    order_sn: Mapped[str] = mapped_column(String, index=True, primary_key=True)
    split_up: Mapped[bool] = mapped_column(Boolean)
    ship_by: Mapped[datetime] = mapped_column(DateTime)
    owner_user: Mapped[Optional[str]] = mapped_column(ForeignKey("auth.users.username"))
    status: Mapped[str] = mapped_column(String)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    owner: Mapped[Optional["User"]] = relationship("User", back_populates="orders")
    item_list: Mapped[List["ShopeeOrderItemList"]] = relationship(
        "ShopeeOrderItemList", back_populates="order"
    )
    recipient_address: Mapped["ShopeeOrderRecipientAddress"] = relationship(
        "ShopeeOrderRecipientAddress", back_populates="order"
    )
    info: Mapped["ShopeeOrderInfo"] = relationship(
        "ShopeeOrderInfo", back_populates="order"
    )
    pies: Mapped[List["PickItemEntry"]] = relationship(
        "PickItemEntry", back_populates="order"
    )


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

    order: Mapped["ShopeeOrder"] = relationship(
        "ShopeeOrder", back_populates="recipient_address"
    )


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

    order: Mapped["ShopeeOrder"] = relationship(
        "ShopeeOrder", back_populates="item_list"
    )


# orders
class OutboundItem(Base):
    __tablename__ = "outbound_items"
    __table_args__ = {"schema": "orders"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    content: Mapped[str] = mapped_column(String, index=True)  # The scanned text
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    owner_user: Mapped[str] = mapped_column(ForeignKey("auth.users.username"))
    tag: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    owner: Mapped["User"] = relationship("User", back_populates="outbounds")


class PickItemEntry(Base):
    __tablename__ = "pick_item_entries"
    __table_args__ = {"schema": "orders"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sku: Mapped[str] = mapped_column(String, index=True)
    qty: Mapped[int] = mapped_column(Integer)
    order_sn: Mapped[Optional[str]] = mapped_column(
        ForeignKey("shopee.orders.order_sn"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    owner_user: Mapped[str] = mapped_column(ForeignKey("auth.users.username"))

    owner: Mapped["User"] = relationship("User", back_populates="pies")
    order: Mapped[Optional["ShopeeOrder"]] = relationship(
        "ShopeeOrder", back_populates="pies"
    )


class PickItemEntryLog(Base):
    __tablename__ = "pick_item_entries_log"
    __table_args__ = {"schema": "orders"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    message: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )


# warehouse
class WarehouseItem(Base):
    __tablename__ = "items"
    __table_args__ = {"schema": "warehouse"}
    sku: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    item_name: Mapped[Optional[str]] = mapped_column(String, index=True)
    location: Mapped[Optional[str]] = mapped_column(String)

    stock: Mapped["Stock"] = relationship("Stock", back_populates="item")


class Stock(Base):
    __tablename__ = "stocks"
    __table_args__ = {"schema": "warehouse"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sku: Mapped[str] = mapped_column(ForeignKey("warehouse.items.sku"))
    stock: Mapped[int] = mapped_column(Integer)
    location: Mapped[Optional[str]] = mapped_column(String)

    item: Mapped["WarehouseItem"] = relationship(
        "WarehouseItem", back_populates="stock"
    )


class StocksLog(Base):
    __tablename__ = "stocks_log"
    __table_args__ = {"schema": "warehouse"}
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    message: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )


# Pydantic Models ----
class OutboundCreate(BaseModel):
    content: str
    tag: Optional[str] = None


class OutboundResponse(BaseModel):
    id: int
    content: str
    tag: Optional[str] = None
    created_at: datetime
    owner_user: str
    closed: bool = False
    closed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class WarehouseItemResponse(BaseModel):
    sku: str
    item_name: Optional[str] = None
    location: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class UserAuth(BaseModel):
    username: str = Field(...)
    password: str = Field(...)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError(
                "Username can only contain alphanumeric characters, "
                "underscores, and hyphens."
            )
        return v


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ShopeeOrderCreate(BaseModel):
    label: str


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
    created_at: datetime
    owner_user: Optional[str] = None
    done: bool = False
    done_at: Optional[datetime] = None
    item_list: List[ShopeeOrderItemResponse] = []
    recipient_address: Optional[ShopeeOrderRecipientResponse] = None
    info: List[ShopeeOrderInfoResponse] = []

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


class PickItemEntryCreate(BaseModel):
    sku: str
    qty: int
    order_sn: Optional[str] = None


class PickItemEntryResponse(BaseModel):
    id: int
    sku: str
    qty: int
    order_sn: Optional[str] = None
    timestamp: datetime
    owner_user: str

    model_config = ConfigDict(from_attributes=True)


class StockCreate(BaseModel):
    sku: str
    stock: int
    mode: str = "set"  # "add" or "set"


class StockResponse(BaseModel):
    id: int
    sku: str
    stock: int
    location: Optional[str] = None
    item_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


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
