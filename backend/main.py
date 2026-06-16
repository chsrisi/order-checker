import asyncio
import csv
import hashlib
import hmac
import io
import logging
import logging.handlers
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, cast, Generator

import aiohttp
import jwt
import jwt.exceptions as jwt_exc
from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security.http import HTTPBearer, HTTPAuthorizationCredentials
from jwt import PyJWK
from jwt.types import Options
from passlib.context import CryptContext
from sqlalchemy import (
    create_engine,
    select,
    delete,
    update,
    Sequence,
    or_,
)
from sqlalchemy.orm import Session, sessionmaker

from models import (
    RefreshToken,
    RefreshTokenRequest,
    OutboundItem,
    OutboundCreate,
    OutboundResponse,
    PickItemEntry,
    PickItemEntryCreate,
    PickItemEntryResponse,
    Token,
    User,
    UserAuth,
    WarehouseItem,
    WarehouseItemResponse,
    Stock,
    StockCreate,
    StockResponse,
    WSMessageType,
    ShopeeResponse,
    ShopeeTokenResponse,
    ShopeeOrder,
    ShopeeOrderInfo,
    ShopeeOrderItemList,
    ShopeeOrderRecipientAddress,
    ShopeeOrderResponse,
    ShopeeOrderItemBOMResponse,
    ShopeeOrderRecipientResponse,
    ShopeeOrderInfoResponse,
    ShpOrderList,
    OrderListT,
    ShpMassTrackingNumber,
    ShpOrderDetails,
    BOMHeader,
    BOMDetail,
    BOMHeaderMarketplace,
    BOMDetailMarketplace,
    ShopeeItem,
)
from keys import (
    KeyManager,
    ACCESS_TTL_SECONDS,
)
from cache import ShopeeOrderCache

load_dotenv()

# Logger configuration
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            "logs/backend.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
        ),
    ],
)
logger = logging.getLogger("backend")

# Database setup
SQLALCHEMY_DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
if not SQLALCHEMY_DATABASE_URL:
    # Use a default SQLite for local development if nothing is specified
    SQLALCHEMY_DATABASE_URL = "sqlite:///./local.db"
    logger.warning(
        "DATABASE_URL not found in env, defaulting to: %s", SQLALCHEMY_DATABASE_URL
    )

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Security Utils ----
ALGORITHM = "RS256"
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
key_manager = KeyManager()
shopee_cache = ShopeeOrderCache()


def get_password_hash(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(username: str):
    expire = datetime.now(UTC) + timedelta(seconds=ACCESS_TTL_SECONDS)
    to_encode = {
        "sub": username,
        "exp": expire,
        "type": "access",
        "jti": secrets.token_hex(16),
        "iat": datetime.now(UTC),
        "nbf": datetime.now(UTC),
        "aud": "api.bakingholic:v0.2a",
        "iss": "auth.bakingholic:v0.2a",
    }

    sig = key_manager.get_active_signer()

    encoded_jwt = jwt.encode(
        to_encode, sig.private_key, algorithm=ALGORITHM, headers={"kid": sig.kid}
    )
    logger.debug(f"Created access token for user: {username} with KID: {sig.kid}")
    return encoded_jwt


def create_refresh_token(username: str):
    expires_delta = timedelta(hours=24)
    expire = datetime.now(UTC) + expires_delta
    to_encode = {
        "sub": username,
        "type": "refresh",
        "jti": secrets.token_hex(16),
        "exp": expire,
        "iat": datetime.now(UTC),
        "nbf": datetime.now(UTC),
        "aud": "api.bakingholic:v0.2a",
        "iss": "auth.bakingholic:v0.2a",
    }

    sig = key_manager.get_active_signer()

    encoded_jwt = jwt.encode(
        to_encode, sig.private_key, algorithm=ALGORITHM, headers={"kid": sig.kid}
    )
    logger.debug(
        f"Created refresh token for user: {username}, expires at: {expire} with KID: {sig.kid}"
    )
    return encoded_jwt, to_encode["jti"], expire


# Dependencies
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    logger.debug("Database session opened")
    try:
        yield db
    finally:
        db.close()
        logger.debug("Database session closed")


@contextmanager
def ctx_get_db():
    return get_db()


def get_user(token: str, db: Session) -> User:
    kid = jwt.get_unverified_header(token).get("kid")
    if kid is None:
        raise jwt_exc.InvalidTokenError("Token must include kid")
    jwk = key_manager.get_public_key(kid)
    if jwk is None:
        raise jwt_exc.InvalidTokenError("Key not found")
    payload = jwt.decode(
        token,
        PyJWK.from_dict(jwk).key,
        audience="api.bakingholic:v0.2a",
        issuer="auth.bakingholic:v0.2a",
        options=Options(require=["exp", "nbf", "sub", "aud", "iss", "jti", "iat"]),
        algorithms=[ALGORITHM],
        leeway=30.0,
    )
    if payload.get("type") != "access":
        raise jwt_exc.InvalidTokenError("Invalid token type")
    username: str | None = payload.get("sub")
    if username is None:
        raise jwt_exc.InvalidTokenError("Token must include subject (sub)")

    user = db.execute(select(User).filter(User.username == username)).scalars().first()
    if not user:
        raise jwt_exc.InvalidTokenError("User not found in db")

    return user


async def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: Session = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user = get_user(token.credentials, db)
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise credentials_exception from exc

    logger.debug(f"User authenticated: {user.username}")
    return user


# background tasks ----
# periodic cleanup of expired/revoked refresh tokens
def _delete_outdated_refresh_tokens() -> int:
    with ctx_get_db() as db:
        result = db.execute(
            delete(RefreshToken).where(
                or_(
                    RefreshToken.expires_at < datetime.now(UTC),
                    RefreshToken.revoked_at.isnot(None),
                )
            )
        )
        db.commit()
        return len(result.all())


async def remove_outdated_refresh():
    try:
        while True:
            await asyncio.sleep(3600)
            count = await asyncio.to_thread(_delete_outdated_refresh_tokens)
            if count:
                logger.info(f"Deleted {count} outdated refresh tokens")
    except asyncio.CancelledError:
        logger.info("Remove outdated refresh task cancelled")
        raise


async def clean_expired_tickets():
    try:
        while True:
            await asyncio.sleep(60)
            ticket_manager.purge_expired()
    except asyncio.CancelledError:
        logger.info("Clean expired tickets task cancelled")
        raise


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup logic
    logger.info("Application starting up...")

    # Start background rotation task
    bg_tasks: list[asyncio.Task[Any]] = []
    bg_tasks.append(asyncio.create_task(key_manager.rotate_keys_task()))
    bg_tasks.append(asyncio.create_task(remove_outdated_refresh()))
    bg_tasks.append(asyncio.create_task(clean_expired_tickets()))

    # Initialize Persistent aiohttp Session
    _app.state.aiohttp_session = aiohttp.ClientSession()
    logger.info("Persistent aiohttp session initialized in app.state")

    with ctx_get_db() as db:
        admin_user = os.getenv("ADMIN_USERNAME")
        admin_pass = os.getenv("ADMIN_PASSWORD")

        admin = (
            db.execute(select(User).filter(User.username == admin_user))
            .scalars()
            .first()
        )
        if not admin:
            logger.info(f"Seeding admin user: {admin_user}")
            hashed_pw = get_password_hash(str(admin_pass))
            db_admin = User(username=admin_user, password_hash=hashed_pw, scope="admin")
            db.add(db_admin)
            db.commit()
        else:
            logger.debug("Admin user already exists")

    yield

    # Shutdown logic
    logger.info("Application shutting down...")

    for task in bg_tasks:
        task.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)
    logger.info("Background tasks cancelled")

    if hasattr(_app.state, "aiohttp_session"):
        await _app.state.aiohttp_session.close()
        logger.info("Persistent aiohttp session closed")


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next: Any):
    start_time = time.time()
    path = request.url.path
    method = request.method
    client_host = request.client.host if request.client else "unknown"

    logger.info(f"Incoming {method} request to {path} from {client_host}")

    response = await call_next(request)

    process_time = (time.time() - start_time) * 1000
    formatted_process_time = f"{process_time:.2f}"

    logger.info(
        f"Request {method} {path} completed with status {response.status_code} in {formatted_process_time}ms"
    )

    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Data helpers ----
def get_user_data(db: Session, username: str) -> User | None:
    user = db.execute(select(User).filter(User.username == username)).scalars().first()
    return user


def get_all_user_data(db: Session) -> Sequence[User]:
    users = db.execute(select(User).filter(User.scope == "client")).scalars().all()
    return users


def get_outbounds_data(db: Session, username: str) -> Sequence[OutboundItem]:
    query = (
        select(OutboundItem)
        .filter(OutboundItem.owner_user == username, OutboundItem.closed == False)  # noqa: E712
        .order_by(OutboundItem.created_at.desc())
    )
    items = db.execute(query).scalars().unique().all()
    return items


def get_all_outbound_data(db: Session) -> Sequence[OutboundItem]:
    query = (
        select(OutboundItem)
        .filter(OutboundItem.closed == False)  # noqa: E712
        .order_by(OutboundItem.created_at.desc())
    )
    items = db.execute(query).scalars().unique().all()
    return items


def get_shopee_order_data(db: Session, username: str) -> Sequence[ShopeeOrder]:
    orders = (
        db.execute(lection_query.filter(ShopeeOrder.owner_user == username))
        .scalars()
        .all()
    )
    return orders


def get_all_shopee_order_data(db: Session) -> Sequence[ShopeeOrder]:
    orders = db.execute(lection_query).scalars().all()
    return orders


def resolve_standard_bom(sku: str, qty: int, db: Session) -> List[tuple[str, int]]:
    # Check if this sku has a BOMHeader
    hdr = db.execute(select(BOMHeader).filter(BOMHeader.sku == sku)).scalar_one_or_none()
    if not hdr:
        return [(sku, qty)]

    # Get details
    details = db.execute(select(BOMDetail).filter(BOMDetail.bom_header_id == hdr.id)).scalars().all()
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
    db: Session
) -> List[tuple[str, int]]:
    # 1. Check Marketplace BOM
    # Shopee model_id or item_id (exclude 0 or None)
    shopee_id = model_id if (model_id and model_id != 0) else item_id
    if shopee_id:
        mp_hdr = db.execute(
            select(BOMHeaderMarketplace).filter(BOMHeaderMarketplace.shopee_id == shopee_id)
        ).scalar_one_or_none()

        if mp_hdr:
            mp_details = db.execute(
                select(BOMDetailMarketplace).filter(BOMDetailMarketplace.shopee_id == shopee_id)
            ).scalars().all()
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
        shopee_item = db.execute(
            select(ShopeeItem).filter(
                (ShopeeItem.model_id == str(shopee_id)) | (ShopeeItem.item_id == str(shopee_id))
            )
        ).scalars().first()
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
            db=db
        )
        for comp_sku, comp_qty in components:
            resolved_items[comp_sku] = resolved_items.get(comp_sku, 0) + comp_qty

    # Fetch names for component SKUs
    sku_list = list(resolved_items.keys())
    item_names = {}
    if sku_list:
        items_db = db.execute(
            select(WarehouseItem.sku, WarehouseItem.item_name).filter(WarehouseItem.sku.in_(sku_list))
        ).all()
        item_names = {row.sku: row.item_name for row in items_db}

    # Construct ShopeeOrderItemBOMResponse list
    item_responses = []
    for comp_sku, comp_qty in resolved_items.items():
        item_responses.append(
            ShopeeOrderItemBOMResponse(
                component_sku=comp_sku,
                component_name=item_names.get(comp_sku) or comp_sku,
                quantity=comp_qty,
            )
        )

    recipient_address = None
    if order.recipient_address:
        recipient_address = ShopeeOrderRecipientResponse.model_validate(order.recipient_address)

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
        info=info_list
    )


def get_pie_data(db: Session, username: str) -> List[PickItemEntryResponse]:
    query = (
        select(
            PickItemEntry.id,
            PickItemEntry.sku,
            PickItemEntry.qty,
            PickItemEntry.order_sn,
            PickItemEntry.timestamp,
            PickItemEntry.owner_user,
            WarehouseItem.item_name,
        )
        .outerjoin(WarehouseItem, PickItemEntry.sku == WarehouseItem.sku)
        .filter(PickItemEntry.owner_user == username)
        .order_by(PickItemEntry.timestamp.desc())
    )
    results = db.execute(query).all()
    return [
        PickItemEntryResponse(
            id=r.id,
            sku=r.sku,
            qty=r.qty,
            order_sn=r.order_sn,
            timestamp=r.timestamp,
            owner_user=r.owner_user,
            item_name=r.item_name,
        )
        for r in results
    ]


def get_all_pie_data(db: Session) -> List[PickItemEntryResponse]:
    query = (
        select(
            PickItemEntry.id,
            PickItemEntry.sku,
            PickItemEntry.qty,
            PickItemEntry.order_sn,
            PickItemEntry.timestamp,
            PickItemEntry.owner_user,
            WarehouseItem.item_name,
        )
        .outerjoin(WarehouseItem, PickItemEntry.sku == WarehouseItem.sku)
        .order_by(PickItemEntry.timestamp.desc())
    )
    results = db.execute(query).all()
    return [
        PickItemEntryResponse(
            id=r.id,
            sku=r.sku,
            qty=r.qty,
            order_sn=r.order_sn,
            timestamp=r.timestamp,
            owner_user=r.owner_user,
            item_name=r.item_name,
        )
        for r in results
    ]


def get_stocks_data(db: Session, join_warehouse: bool = False):
    query = select(Stock)
    if join_warehouse:
        # Join Stock with WarehouseItem to get item metadata.
        query = select(
            Stock.id, Stock.sku, Stock.stock, Stock.location, WarehouseItem.item_name
        ).join(WarehouseItem, Stock.sku == WarehouseItem.sku)
    results = db.execute(query)
    return results.all() if join_warehouse else results.scalars().all()


def get_all_stocks_data(db: Session, join_warehouse: bool = False):
    return get_stocks_data(db, join_warehouse=join_warehouse)


class TicketInfo:
    def __init__(self, username: str, expires_at: float):
        self.username = username
        self.expires_at = expires_at


class TicketManager:
    def __init__(self):
        self._tickets: Dict[str, TicketInfo] = {}
        self._lock = threading.Lock()

    def generate_ticket(self, username: str, ttl_seconds: int = 30) -> str:
        ticket = secrets.token_urlsafe(32)
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._tickets[ticket] = TicketInfo(username, expires_at)
        return ticket

    def consume_ticket(self, ticket: str) -> Optional[str]:
        with self._lock:
            info = self._tickets.pop(ticket, None)
            if info is None:
                return None
            if time.time() > info.expires_at:
                return None
            return info.username

    def purge_expired(self):
        now = time.time()
        with self._lock:
            expired_keys = [k for k, v in self._tickets.items() if now > v.expires_at]
            for k in expired_keys:
                self._tickets.pop(k, None)


ticket_manager = TicketManager()


# WebSockets ----
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.user_scopes: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, username: str, scope: str):
        await websocket.accept()
        if username not in self.active_connections:
            self.active_connections[username] = []
        self.active_connections[username].append(websocket)
        self.user_scopes[websocket] = scope
        logger.info(f"WebSocket connected: {username} (scope: {scope})")
        logger.debug(
            f"User {username} now has {len(self.active_connections[username])} active sessions"
        )

    def disconnect(self, websocket: WebSocket, username: str):
        if username in self.active_connections:
            self.active_connections[username].remove(websocket)
            if not self.active_connections[username]:
                del self.active_connections[username]
        if websocket in self.user_scopes:
            del self.user_scopes[websocket]
        logger.info(f"WebSocket disconnected: {username}")
        if username in self.active_connections:
            logger.debug(
                f"User {username} has {len(self.active_connections[username])} sessions remaining"
            )
        else:
            logger.debug(f"User {username} has no sessions remaining")

    def _get_data(self, message_type: WSMessageType, db: Session, username: str):
        is_admin = False
        user = (
            db.execute(select(User).filter(User.username == username)).scalars().first()
        )
        if user:
            is_admin = user.scope == "admin"
        else:
            raise ValueError(f"User {username} not found")

        data = None

        if message_type == WSMessageType.USERS:
            data = get_all_user_data(db)
        elif message_type == WSMessageType.OUTBOUNDS:
            outbounds = (
                get_all_outbound_data(db)
                if is_admin
                else get_outbounds_data(db, username)
            )
            data = [OutboundResponse.model_validate(o) for o in outbounds]
        elif message_type == WSMessageType.SHOPEE_ORDERS:
            data = (
                get_all_shopee_order_data(db)
                if is_admin
                else get_shopee_order_data(db, username)
            )
            data = [build_shopee_order_response(o, db) for o in data]
        elif message_type == WSMessageType.PICK_ITEM_ENTRIES:
            data = get_all_pie_data(db) if is_admin else get_pie_data(db, username)
        elif message_type == WSMessageType.STOCKS:
            stocks = get_all_stocks_data(db, join_warehouse=True)
            data = [StockResponse.model_validate(dict(s._mapping)) for s in stocks]

        if data is not None:
            data = [jsonable_encoder(item) for item in data]

        return data

    async def _send_raw(
        self,
        message_type: WSMessageType,
        data: Any,
        websocket: WebSocket,
        username: str,
    ):
        try:
            await websocket.send_json({"type": message_type.value, "data": data})
        except Exception as e:
            logger.error(f"Error sending message to {username}: {str(e)}")
            self.disconnect(websocket, username)

    async def send_to_session(
        self,
        message_type: WSMessageType,
        db: Session,
        websocket: WebSocket,
        username: str,
        data: Any = None,
    ):
        if data is None:
            data = self._get_data(message_type, db, username)
        logger.debug(f"Sending {message_type.value} to {username} session")
        await self._send_raw(message_type, data, websocket, username)

    async def send_to_user(
        self, message_type: WSMessageType, db: Session, username: str
    ):
        if username in self.active_connections:
            data = self._get_data(message_type, db, username)
            connections = list(self.active_connections[username])
            logger.debug(
                f"Sending {message_type.value} to {username} ({len(connections)} sessions)"
            )
            tasks = [
                self._send_raw(message_type, data, ws, username) for ws in connections
            ]
            await asyncio.gather(*tasks)

    async def broadcast(
        self, message_type: WSMessageType, db: Session, scope: Optional[str] = None
    ):
        admin_data = None
        client_data_cache: dict[str, list[Any] | None] = {}

        tasks: list[Any] = []
        for username, connections in list(self.active_connections.items()):
            for ws in list(connections):
                user_scope = self.user_scopes.get(ws)
                if scope is None or user_scope == scope:
                    if user_scope == "admin":
                        if admin_data is None:
                            admin_data = self._get_data(message_type, db, username)
                        data = admin_data
                    else:
                        if username not in client_data_cache:
                            client_data_cache[username] = self._get_data(
                                message_type, db, username
                            )
                        data = client_data_cache[username]

                    tasks.append(self._send_raw(message_type, data, ws, username))

        logger.debug(
            f"Broadcasting {message_type.value} to {len(tasks)} sessions (scope: {scope})"
        )
        if tasks:
            await asyncio.gather(*tasks)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )

    username = ticket_manager.consume_ticket(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )

    with ctx_get_db() as db:
        user = get_user_data(db, username)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )

        await manager.connect(websocket, user.username or "", user.scope or "")
        try:
            while True:
                data = await websocket.receive_json()
                command = data.get("command")
                logger.debug(f"WS Command received from {user.username}: {command}")

                if command == "get_users":
                    if user.scope != "admin":
                        await manager.send_to_session(
                            WSMessageType.ERROR,
                            db,
                            websocket=websocket,
                            username=user.username,
                            data="Forbidden",
                        )
                    else:
                        await manager.send_to_session(
                            WSMessageType.USERS,
                            db,
                            websocket=websocket,
                            username=user.username,
                        )

                elif command == "get_items":
                    await manager.send_to_session(
                        WSMessageType.OUTBOUNDS,
                        db,
                        websocket=websocket,
                        username=user.username,
                    )

                elif command == "get_shopee_orders":
                    await manager.send_to_session(
                        WSMessageType.SHOPEE_ORDERS,
                        db,
                        websocket=websocket,
                        username=user.username,
                    )

                    await manager.send_to_session(
                        WSMessageType.PICK_ITEM_ENTRIES,
                        db,
                        websocket=websocket,
                        username=user.username,
                    )

                elif command == "get_stocks":
                    await manager.send_to_session(
                        WSMessageType.STOCKS,
                        db,
                        websocket=websocket,
                        username=user.username,
                    )

                else:
                    await manager.send_to_session(
                        WSMessageType.ERROR,
                        db,
                        websocket=websocket,
                        username=user.username,
                        data=f"Unknown command: {command}",
                    )

        except WebSocketDisconnect:
            manager.disconnect(websocket, user.username or "")
        except Exception as e:
            logger.error(f"WebSocket error for {user.username}: {str(e)}")
            manager.disconnect(websocket, user.username or "")


# Shopee OpenAPI Utils ----
async def refresh_shopee_token() -> tuple[str, str] | tuple[None, None]:
    logger.info("[TOKEN SYSTEM] Attempting to refresh Shopee access token...")
    shop_id_env = os.getenv("SHOP_ID")
    partner_id_env = os.getenv("PARTNER_ID")
    partner_key_env = os.getenv("PARTNER_KEY")
    refresh_token = os.getenv("REFRESH_TOKEN")

    if not all([shop_id_env, partner_id_env, partner_key_env, refresh_token]):
        logger.error(
            "[TOKEN SYSTEM] Missing Shopee environment variables for token refresh"
        )
        return None, None

    shop_id = int(cast(str, shop_id_env))
    partner_id = int(cast(str, partner_id_env))
    partner_key = cast(str, partner_key_env).encode()

    timest = int(time.time())
    host = os.getenv("SHOPEE_URL")
    path = "/api/v2/auth/access_token/get"
    body = {
        "shop_id": shop_id,
        "refresh_token": refresh_token,
        "partner_id": partner_id,
    }

    tmp_base_string = f"{partner_id}{path}{timest}"
    base_string = tmp_base_string.encode()
    sign = hmac.new(partner_key, base_string, hashlib.sha256).hexdigest()
    url = f"{host}{path}?partner_id={partner_id}&timestamp={timest}&sign={sign}"

    headers = {"Content-Type": "application/json"}
    try:
        async with app.state.aiohttp_session.post(
            url, json=body, headers=headers
        ) as resp:
            ret = ShopeeTokenResponse.model_validate(await resp.json())

            if ret.error:
                logger.error(
                    f"[TOKEN SYSTEM FAILED] Shopee Auth Server rejected refresh token: {ret.error} - {ret.message} (ReqID: {ret.request_id})"
                )
                return None, None

            if ret.access_token and ret.refresh_token:
                from dotenv import set_key  # Assumed from your setup

                set_key(".env", "ACCESS_TOKEN", ret.access_token)
                set_key(".env", "REFRESH_TOKEN", ret.refresh_token)

                os.environ["ACCESS_TOKEN"] = ret.access_token
                os.environ["REFRESH_TOKEN"] = ret.refresh_token
                logger.info(
                    "[TOKEN SYSTEM SUCCESS] Shopee tokens successfully updated in file and memory."
                )
                return ret.access_token, ret.refresh_token

    except Exception as e:
        logger.error(
            f"[TOKEN SYSTEM EXCEPTION] Exception during Shopee token refresh network call: {str(e)}"
        )
        return None, None

    return None, None


# Global lock to prevent concurrent workers from refreshing the token at the same time
TOKEN_REFRESH_LOCK = asyncio.Lock()


async def shopee_request(
    path: str,
    params: Optional[dict[str, Any]] = None,
    body: Optional[dict[str, Any]] = None,
    method: str = "GET",
    retry_on_expiry: bool = True,
    max_429_retries: int = 3,
) -> Optional[ShopeeResponse]:

    # 1. Top-Level Circuit Breaker Check
    if shopee_cache.is_token_fatal():
        logger.critical(
            f"[CIRCUIT BREAKER] Aborting request to {path}. Token infrastructure is flagged as completely dead."
        )
        raise HTTPException(
            status_code=500,
            detail="Shopee API authentication infrastructure is broken. Re-authorization required.",
        )

    backoff_delay = 1.5  # Starting delay for 429 backoff

    for attempt in range(max_429_retries + 1):
        host = os.getenv("SHOPEE_URL")
        partner_id_env = os.getenv("PARTNER_ID")
        partner_key_env = os.getenv("PARTNER_KEY")
        shop_id_env = os.getenv("SHOP_ID")
        access_token = os.getenv("ACCESS_TOKEN")

        if not all([partner_id_env, partner_key_env, shop_id_env, access_token]):
            logger.error("Missing Shopee environment variables for API request")
            return None

        partner_id = int(partner_id_env or "0")
        partner_key = (partner_key_env or "").encode()
        shop_id = int(shop_id_env or "0")
        timest = int(time.time())

        tmp_base_string = f"{partner_id}{path}{timest}{access_token}{shop_id}"
        base_string = tmp_base_string.encode()
        sign = hmac.new(partner_key, base_string, hashlib.sha256).hexdigest()

        query_params = {
            "partner_id": partner_id,
            "timestamp": timest,
            "access_token": access_token,
            "shop_id": shop_id,
            "sign": sign,
        }
        if params:
            query_params.update(params)

        url = f"{host}{path}"
        headers = {"Content-Type": "application/json"}

        logger.debug(
            f"[REQ ENQUEUE] {method} {path} | Token snippet: ...{access_token[-6:] if access_token else 'None'}"
        )

        try:
            if method.upper() == "GET":
                req_coro = app.state.aiohttp_session.get(
                    url, params=query_params, headers=headers
                )
            else:
                req_coro = app.state.aiohttp_session.post(
                    url, params=query_params, json=body, headers=headers
                )

            async with req_coro as resp:
                # Handle Gateway 429 errors
                if resp.status == 429:
                    if attempt < max_429_retries:
                        logger.warning(
                            f"[429 TOO MANY REQUESTS] Gateway rate limit hit on {path}. Retrying in {backoff_delay}s... (Attempt {attempt + 1}/{max_429_retries})"
                        )
                        await asyncio.sleep(backoff_delay)
                        backoff_delay *= 2
                        continue
                    else:
                        logger.error(
                            f"[429 EXHAUSTED] Max retries reached for rate limit on path: {path}"
                        )
                        return None

                ret = ShopeeResponse.model_validate(await resp.json())

                if ret.error:
                    logger.error(
                        f"[SHOPEE API ERROR] {ret.error} - {ret.message} (ReqID: {ret.request_id})"
                    )

                    # Handle Payload-level Rate Limits
                    if ret.error in ["request_limit_exceeded", "frequency_limited"]:
                        if attempt < max_429_retries:
                            logger.warning(
                                f"[429 API LIMIT] Application rate limit '{ret.error}' on {path}. Retrying in {backoff_delay}s..."
                            )
                            await asyncio.sleep(backoff_delay)
                            backoff_delay *= 2
                            continue
                        return ret

                    # Token Expiry handling with Double-Checked Locks and Circuit Breaking
                    if retry_on_expiry and ret.error in [
                        "invalid_access_token",
                        "invalid_acceess_token",
                        "error_access_token",
                    ]:
                        logger.warning(
                            f"[TOKEN EXPIRED] Detected expired token on task executing {path}."
                        )

                        async with TOKEN_REFRESH_LOCK:
                            # Worker check 1: Did a previous worker fail catastrophically while we were waiting?
                            if shopee_cache.is_token_fatal():
                                logger.critical(
                                    f"[FAIL FAST] Worker on {path} woke up and detected fatal token state. Aborting."
                                )
                                raise HTTPException(
                                    status_code=500,
                                    detail="Shopee authentication token refresh failed globally.",
                                )

                            # Worker check 2: Are we the chosen one to execute the refresh?
                            if os.getenv("ACCESS_TOKEN") == access_token:
                                logger.info(
                                    "[TOKEN REFRESH] Lock acquired. Executing token renewal..."
                                )
                                new_at, _ = await refresh_shopee_token()

                                if not new_at:
                                    logger.critical(
                                        "[FATAL AUTH FAILURE] Refresh token is invalid/expired! Tripping circuit breaker."
                                    )
                                    shopee_cache.set_token_fatal()
                                    raise HTTPException(
                                        status_code=500,
                                        detail="Shopee Refresh Token has expired or is invalid. Manual merchant re-auth required.",
                                    )
                            else:
                                logger.info(
                                    "[TOKEN REFRESH SKIPPED] Token was already successfully updated by a concurrent worker."
                                )

                        logger.info(
                            f"[RETRYING REQUEST] Re-executing {path} with the active token configuration."
                        )
                        return await shopee_request(
                            path, params, body, method, retry_on_expiry=False
                        )

                logger.debug(f"[REQ SUCCESS] {path} | ReqID: {ret.request_id}")
                return ret

        except HTTPException:
            # CRITICAL: Re-raise HTTPExceptions so they bypass the generic Exception block and hit FastAPI
            raise
        except Exception as e:
            logger.error(
                f"[EXCEPTION] Critical error during Shopee call to {path}: {str(e)}",
                exc_info=True,
            )
            return None

    return None


# Auth Endpoints ----
def _get_tokens(user: User, db: Session):
    logger.info(f"Generating tokens for user: {user.username} (scope: {user.scope})")
    access_token = create_access_token(user.username)
    refresh_token, jti, expire = create_refresh_token(user.username)

    # Store refresh token in DB
    db_refresh_token = RefreshToken(jti=jti, username=user.username, expires_at=expire)
    db.add(db_refresh_token)
    db.commit()
    logger.debug(
        f"Refresh token stored in DB for user {user.username}, expires at {expire}"
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@app.post("/auth/register", response_model=Token)
async def register_client(auth: UserAuth, db: Session = Depends(get_db)):
    logger.info(f"Registration attempt for username: {auth.username}")
    user = (
        db.execute(select(User).filter(User.username == auth.username))
        .scalars()
        .first()
    )
    if user:
        logger.warning(f"Registration failed: Username {auth.username} already exists")
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = get_password_hash(auth.password)

    new_user = User(
        username=auth.username, password_hash=hashed_password, scope="client"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info(f"User {auth.username} successfully registered")

    await manager.broadcast(WSMessageType.USERS, db, scope="admin")
    return _get_tokens(new_user, db)


@app.post("/auth/login", response_model=Token)
def login_client(auth: UserAuth, db: Session = Depends(get_db)):
    logger.info(f"Login attempt for client: {auth.username}")
    user = (
        db.execute(select(User).filter(User.username == auth.username))
        .scalars()
        .first()
    )
    if not user:
        logger.warning(f"Login failed: User {auth.username} not found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    if not verify_password(auth.password, user.password_hash or ""):
        logger.warning(f"Login failed: Incorrect password for user {auth.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    logger.info(f"Client {auth.username} logged in successfully")
    return _get_tokens(user, db)


@app.post("/auth/logout")
def logout(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    token = body.refresh_token
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        if kid is None:
            raise jwt_exc.InvalidTokenError("Token must include kid")
        jwk = key_manager.get_public_key(kid)
        if jwk is None:
            raise jwt_exc.InvalidTokenError("Key not found")
        payload = jwt.decode(
            token,
            PyJWK.from_dict(jwk).key,
            audience="api.bakingholic:v0.2a",
            issuer="auth.bakingholic:v0.2a",
            options=Options(require=["exp", "nbf", "sub", "aud", "iss", "jti", "iat"]),
            algorithms=[ALGORITHM],
            leeway=30.0,
        )
        if payload.get("type") != "refresh":
            raise jwt_exc.InvalidTokenError("Invalid token type")
        jti = payload.get("jti")
        if not jti:
            raise jwt_exc.InvalidTokenError("Token must include jti")
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise HTTPException(status_code=400, detail="Bad Request") from exc

    db_token = (
        db.execute(select(RefreshToken).filter(RefreshToken.jti == jti))
        .scalars()
        .first()
    )
    if db_token:
        logger.info(f"Revoking refresh token for user: {db_token.username}")
        db.delete(db_token)
        db.commit()
    else:
        logger.debug("Logout: Token not found or already revoked")
    return {"message": "Logged out successfully"}


@app.post("/auth/admin", response_model=Token)
def login_admin(auth: UserAuth, db: Session = Depends(get_db)):
    logger.info(f"Admin login attempt for: {auth.username}")
    user = (
        db.execute(select(User).filter(User.username == auth.username))
        .scalars()
        .first()
    )
    if (
        not user
        or user.scope != "admin"
        or not verify_password(auth.password, user.password_hash or "")
    ):
        logger.warning(f"Admin login failed for: {auth.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    logger.info(f"Admin {auth.username} logged in successfully")
    return _get_tokens(user, db)


@app.post("/auth/ws-token")
def create_ws_token(
    current_user: User = Depends(get_current_user),
):
    ticket = ticket_manager.generate_ticket(current_user.username, ttl_seconds=30)
    return {"token": ticket, "expires_in": 30}


# JWT ----
@app.get("/.well-known/jwks.json")
def jwks_endpoint():
    """Returns the JSON Web Key Set containing the public key for verifying JWTs."""
    return {"keys": key_manager.get_jwks()}


@app.post("/auth/refresh", response_model=Token)
def refresh(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
    )
    token = body.refresh_token
    logger.info("Token refresh requested")
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        if kid is None:
            raise jwt_exc.InvalidTokenError("Token must include kid")
        jwk = key_manager.get_public_key(kid)
        if jwk is None:
            raise jwt_exc.InvalidTokenError("Key not found")
        payload = jwt.decode(
            token,
            PyJWK.from_dict(jwk).key,
            audience="api.bakingholic:v0.2a",
            issuer="auth.bakingholic:v0.2a",
            options=Options(require=["exp", "nbf", "sub", "aud", "iss", "jti", "iat"]),
            algorithms=[ALGORITHM],
            leeway=30.0,
        )
        if payload.get("type") != "refresh":
            raise jwt_exc.InvalidTokenError("Invalid token type")
        jti = payload.get("jti")
        if not jti:
            raise jwt_exc.InvalidTokenError("Token must include jti")
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise credentials_exception from exc

    # Check if token exists in DB
    db_token = (
        db.execute(select(RefreshToken).filter(RefreshToken.jti == jti))
        .scalars()
        .first()
    )
    if not db_token:
        logger.error("Token nonexistent")
        raise credentials_exception

    # Check revoke from DB
    if db_token.revoked_at and db_token.revoked_at.replace(tzinfo=UTC) < datetime.now(
        UTC
    ):
        logger.error("Token revoked")
        db.delete(db_token)
        db.commit()
        raise credentials_exception

    # Check expiry from DB
    if db_token.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        logger.error("Token expired in DB")
        db.delete(db_token)
        db.commit()
        raise credentials_exception

    user = (
        db.execute(select(User).filter(User.username == db_token.username))
        .scalars()
        .first()
    )
    if not user:
        logger.error("User not found")
        raise credentials_exception

    # Rotate refresh token
    logger.info(f"Rotating refresh token for user: {user.username}")
    db.delete(db_token)
    db.commit()

    return _get_tokens(user, db)


# Admin Management Endpoints ----
# user
@app.get("/admin/users")
def get_users(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        logger.warning(
            f"Unauthorized access attempt to /admin/users by user: {current_user.username}"
        )
        raise HTTPException(status_code=403, detail="Not authorized")

    users = db.execute(select(User).filter(User.scope == "client")).scalars().all()
    logger.info(f"Admin {current_user.username} fetched {len(users)} client users")
    return users


@app.delete("/admin/users")
async def delete_user(
    username: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        logger.warning(
            f"Unauthorized delete attempt for user {username} by: {current_user.username}"
        )
        raise HTTPException(status_code=403, detail="Not authorized")

    user = (
        db.execute(
            select(User).filter(User.username == username, User.scope == "client")
        )
        .scalars()
        .first()
    )
    if not user:
        logger.warning(
            f"Admin {current_user.username} tried to delete non-existent user: {username}"
        )
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(f"Admin {current_user.username} deleting user {user.username}")
    # Delete associated items and tokens
    scans_result = (
        db.execute(delete(OutboundItem).filter(OutboundItem.owner_user == username))
        .scalars()
        .all()
    )
    tokens_result = (
        db.execute(delete(RefreshToken).filter(RefreshToken.username == username))
        .scalars()
        .all()
    )
    db.delete(user)
    db.commit()
    logger.info(
        "Deleted user %s, %s scans, and %s refresh tokens",
        user.username,
        len(scans_result),
        len(tokens_result),
    )
    await manager.broadcast(WSMessageType.USERS, db, scope="admin")
    return {"message": "User and associated data deleted successfully"}


# history
@app.get("/admin/history/outbound", response_model=List[OutboundResponse])
def get_outbound_history(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    items = (
        db.execute(
            select(OutboundItem)
            .filter(OutboundItem.closed == True)  # noqa: E712
            .order_by(OutboundItem.created_at.desc())
        )
        .scalars()
        .unique()
        .all()
    )
    return items


@app.get("/admin/history/shopee/orders", response_model=List[ShopeeOrderResponse])
def get_shopee_orders_history(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    orders = (
        db.execute(
            select(ShopeeOrder)
            .filter(ShopeeOrder.done == True)  # noqa: E712
            .order_by(ShopeeOrder.ship_by.desc())
        )
        .scalars()
        .all()
    )
    return [build_shopee_order_response(o, db) for o in orders]


# exports
@app.get("/admin/export/scans")
def export_scanned_items(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        logger.warning(f"Unauthorized export attempt by user: {current_user.username}")
        raise HTTPException(status_code=403, detail="Not authorized")

    items = (
        db.execute(
            select(OutboundItem)
            .filter(OutboundItem.closed == False)  # noqa: E712
            .order_by(OutboundItem.created_at.desc())
        )
        .scalars()
        .unique()
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Content", "Tags", "Created At", "Owner"])

    for item in items:
        writer.writerow(
            [
                item.id,
                item.content,
                ", ".join(item.tags),
                item.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                item.owner_user,
            ]
        )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=scanned_items_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )


@app.get("/admin/export/stocks")
def export_stocks(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.scope != "admin":
        logger.warning(
            f"Unauthorized stock export attempt by user: {current_user.username}"
        )
        raise HTTPException(status_code=403, detail="Not authorized")

    # Join Stock with WarehouseItem to get item metadata.
    query = (
        select(Stock.sku, Stock.stock, WarehouseItem.item_name)
        .join(WarehouseItem, Stock.sku == WarehouseItem.sku)
        .order_by(Stock.sku)
    )
    results = db.execute(query).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["SKU", "Description", "Stock"])

    for r in results:
        writer.writerow(
            [
                r.sku,
                r.item_name or "",
                r.stock,
            ]
        )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=inventory_stocks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )


# Outbound Endpoints ----
@app.post("/outbound", response_model=OutboundResponse)
async def create_outbound(
    item: OutboundCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} scanning item: {item.content}")
    # Duplicate detection (same user, same content)
    existing = (
        db.execute(
            select(OutboundItem).filter(
                OutboundItem.content == item.content,
                OutboundItem.owner_user == current_user.username,
                OutboundItem.closed == False,  # noqa: E712
            )
        )
        .scalars()
        .unique()
        .first()
    )

    if existing:
        logger.warning(
            "Duplicate scan detected for user %s: %s",
            current_user.username,
            item.content,
        )
        raise HTTPException(status_code=409, detail="Duplicate scan detected")

    content_clean = item.content.strip()
    matched_order = (
        db.execute(
            select(ShopeeOrder)
            .outerjoin(
                ShopeeOrderInfo, ShopeeOrder.order_sn == ShopeeOrderInfo.order_sn
            )
            .filter(
                or_(
                    ShopeeOrder.order_sn == content_clean,
                    ShopeeOrderInfo.tracking_number == content_clean,
                )
            )
        )
        .scalars()
        .first()
    )

    tags: list[str] = list(item.tags) if item.tags else []
    if matched_order and matched_order.shipping_carrier:
        if matched_order.shipping_carrier not in tags:
            tags.append(matched_order.shipping_carrier)

    db_item = OutboundItem(
        content=item.content,
        owner_user=current_user.username,
        tags=tags,
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    logger.info(f"Item {db_item.id} saved for user {current_user.username}")
    # Broadcast full list to admins
    await manager.broadcast(WSMessageType.OUTBOUNDS, db, scope="admin")
    # Send user-specific list to the owner
    await manager.send_to_user(
        WSMessageType.OUTBOUNDS, db, username=current_user.username
    )
    return OutboundResponse(
        id=db_item.id,
        content=db_item.content or "",
        tags=db_item.tags,
        created_at=db_item.created_at,
        owner_user=db_item.owner_user,
        closed=db_item.closed,
        closed_at=db_item.closed_at,
    )


@app.get("/outbound", response_model=List[OutboundResponse])
def read_outbounds(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    logger.info(f"User {current_user.username} fetching outbound history")
    if current_user.scope == "admin":
        items = (
            db.execute(
                select(OutboundItem)
                .filter(OutboundItem.closed == False)  # noqa: E712
                .order_by(OutboundItem.created_at.desc())
            )
            .scalars()
            .unique()
            .all()
        )
    else:
        items = (
            db.execute(
                select(OutboundItem)
                .filter(
                    OutboundItem.owner_user == current_user.username,
                    OutboundItem.closed == False,  # noqa: E712
                )
                .order_by(OutboundItem.created_at.desc())
            )
            .scalars()
            .unique()
            .all()
        )
    logger.debug(f"Fetched {len(items)} items for user {current_user.username}")
    return items


@app.post("/outbound/close")
async def close_outbound_period(
    contents: List[str],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    logger.info(
        f"Admin {current_user.username} closing period for {len(contents)} items"
    )

    now = datetime.now(UTC)

    # Mark outbounds as closed
    result = db.execute(
        update(OutboundItem)
        .filter(OutboundItem.content.in_(contents), OutboundItem.closed == False)  # noqa: E712
        .values(closed=True, closed_at=now)
        .returning(OutboundItem.id)
    )

    outbound_count = len(result.all())
    unknown_count = len(contents) - outbound_count

    # Mark matched ShopeeOrders as done
    # Batch 1: match content as order_sn
    matched_order_sns: set[str] = set(
        db.execute(
            select(ShopeeOrder.order_sn).filter(ShopeeOrder.order_sn.in_(contents))
        )
        .scalars()
        .all()
    )

    # Batch 2: remaining content strings — try as tracking_number
    remaining = [c for c in contents if c not in matched_order_sns]
    if remaining:
        tracking_matches = (
            db.execute(
                select(ShopeeOrderInfo.order_sn).filter(
                    ShopeeOrderInfo.tracking_number.in_(remaining),
                    ShopeeOrderInfo.tracking_number.isnot(None),
                )
            )
            .scalars()
            .all()
        )
        matched_order_sns.update(tracking_matches)

    orders_done_count = 0
    if matched_order_sns:
        result_orders = db.execute(
            update(ShopeeOrder)
            .filter(
                ShopeeOrder.order_sn.in_(list(matched_order_sns)),
                ShopeeOrder.done == False,  # noqa: E712
            )
            .values(done=True, done_at=now)
            .returning(ShopeeOrder.order_sn)
        )
        orders_done_count = len(result_orders.all())

    db.commit()
    shopee_cache.invalidate()

    logger.info(
        f"Closed period: {outbound_count} outbound, {unknown_count} unknown, "
        f"{orders_done_count} orders done"
    )

    # Broadcast updates
    await manager.broadcast(WSMessageType.OUTBOUNDS, db, scope="admin")
    await manager.broadcast(WSMessageType.SHOPEE_ORDERS, db, scope="admin")

    return {
        "outbound": outbound_count,
        "unknown": unknown_count,
        "orders_done": orders_done_count,
    }


# Items Endpoints ----
@app.get("/items/find", response_model=List[WarehouseItemResponse])
def find_warehouse_items(
    query: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} searching for: {query}")
    search = f"%{query}%"
    results = (
        db.execute(
            select(WarehouseItem)
            .filter(
                (WarehouseItem.sku.ilike(search))
                | (WarehouseItem.item_name.ilike(search))
            )
            .limit(50)
        )
        .scalars()
        .all()
    )
    logger.debug(f"Found {len(results)} matches for query '{query}'")
    return results


# Stocks Endpoints ----
def get_or_merge_stock(db: Session, sku: str, location: Optional[str]) -> Optional[Stock]:
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
                    (Stock.location == None) | (Stock.location == ""),
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


@app.post("/stocks", response_model=StockResponse)
async def set_stock(
    stock_in: StockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sku = stock_in.sku
    location = stock_in.location if stock_in.location != "" else None
    move_to = stock_in.move_to if stock_in.move_to != "" else None

    logger.info(
        f"User {current_user.username} {stock_in.mode} stock for {sku} value {stock_in.stock} at {location} (move_to: {move_to})"
    )

    # Verify item exists in warehouse_items
    item = (
        db.execute(select(WarehouseItem).filter(WarehouseItem.sku == sku))
        .scalars()
        .first()
    )
    if not item:
        logger.warning(f"Stock update failed: SKU {sku} not found")
        raise HTTPException(
            status_code=404, detail=f"Item with SKU {sku} not found"
        )

    if move_to is not None:
        # Move operation
        if location == move_to:
            db_stock = get_or_merge_stock(db, sku, location)
            if not db_stock:
                db_stock = Stock(sku=sku, stock=0, location=location)
                db.add(db_stock)
                db.flush()
            db_stock_res = db_stock
        else:
            source_stock = get_or_merge_stock(db, sku, location)
            if not source_stock:
                source_stock = Stock(sku=sku, stock=0, location=location)
                db.add(source_stock)
                db.flush()

            dest_stock = get_or_merge_stock(db, sku, move_to)
            if not dest_stock:
                dest_stock = Stock(sku=sku, stock=0, location=move_to)
                db.add(dest_stock)
                db.flush()

            # Perform move
            source_stock.stock -= stock_in.stock
            dest_stock.stock += stock_in.stock

            # Clean up if source stock becomes <= 0
            if source_stock.stock <= 0:
                db.delete(source_stock)

            # Clean up if dest stock becomes <= 0
            if dest_stock.stock <= 0:
                db.delete(dest_stock)
                db_stock_res = Stock(id=0, sku=sku, stock=0, location=move_to)
            else:
                db_stock_res = dest_stock
    else:
        # Standard update/set operation
        db_stock = get_or_merge_stock(db, sku, location)
        if db_stock:
            if stock_in.mode == "add":
                db_stock.stock += stock_in.stock
            else:
                db_stock.stock = stock_in.stock
            logger.info(f"Updated existing stock record for {sku} at {location}")
        else:
            location_val = location if "location" in stock_in.model_fields_set else item.location
            db_stock = Stock(
                sku=sku,
                stock=stock_in.stock,
                location=location_val,
            )
            db.add(db_stock)
            db.flush()
            logger.info(f"Created new stock record for {sku} at {location_val}")

        # Clean up if stock becomes <= 0
        if db_stock.stock <= 0:
            db.delete(db_stock)
            db_stock_res = Stock(id=0, sku=sku, stock=0, location=location)
        else:
            db_stock_res = db_stock

    db.commit()

    if db_stock_res.id and db_stock_res.stock > 0:
        db.refresh(db_stock_res)

    # Broadcast update
    await manager.broadcast(WSMessageType.STOCKS, db)

    return StockResponse(
        id=db_stock_res.id if db_stock_res.id else 0,
        sku=db_stock_res.sku,
        stock=db_stock_res.stock,
        location=db_stock_res.location,
        item_name=item.item_name,
    )



# Shopee Orders Endpoints ----
# Limit concurrent Shopee requests to respect rate limits (e.g., max 5 at once)
SHOPEE_SEMAPHORE = asyncio.Semaphore(3)


async def fetch_sns_for_status(status: str, time_from: int, now: int) -> list[str]:
    """Worker to fetch order SNs for a specific status with pagination."""
    cursor = ""
    status_sns = []

    while True:
        params: dict[str, Any] = {
            "page_size": 100,
            "time_range_field": "create_time",
            "time_from": time_from,
            "time_to": now,
            "order_status": status,
        }
        if cursor:
            params["cursor"] = cursor

        async with SHOPEE_SEMAPHORE:
            shopee_resp = await shopee_request(
                path="/api/v2/order/get_order_list",
                params=params,
            )

        if (
            not shopee_resp
            or shopee_resp.error
            or not isinstance(shopee_resp.response, ShpOrderList)
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Failed to fetch {status} orders from Shopee",
            )

        resp_data = shopee_resp.response
        status_sns.extend(item.order_sn for item in resp_data.order_list)

        if not resp_data.more:
            break
        cursor = resp_data.next_cursor or ""

    return status_sns


async def fetch_chunk_details(
    chunk: list[str],
) -> tuple[list[ShpOrderDetails], dict[str, tuple[str, str | None]], set[str]]:
    """Worker to fetch details and tracking numbers for a chunk of 50 orders."""
    sn_str = ",".join(chunk)

    async with SHOPEE_SEMAPHORE:
        detail_resp = await shopee_request(
            path="/api/v2/order/get_order_detail",
            params={
                "order_sn_list": sn_str,
                "response_optional_fields": "recipient_address,note,item_list,split_up,shipping_carrier,package_list,",
            },
        )

    if (
        not detail_resp
        or detail_resp.error
        or not isinstance(detail_resp.response, OrderListT)
    ):
        logger.error(f"Failed to fetch Shopee details for chunk: {sn_str}")
        return [], {}, set()

    order_details_list = detail_resp.response.order_list
    if not isinstance(order_details_list, list):
        return [], {}, set()

    # Prepare batch tracking payload
    processed_packages = [
        {"package_number": pkg.package_number}
        for detail in order_details_list
        if detail.order_status != "READY_TO_SHIP" and detail.package_list
        for pkg in detail.package_list
    ]

    tracking_map = {}
    fail_pkgs = set()

    if processed_packages:
        async with SHOPEE_SEMAPHORE:
            tracking_resp = await shopee_request(
                path="/api/v2/logistics/get_mass_tracking_number",
                method="POST",
                body={"package_list": processed_packages},
            )

        if tracking_resp and not tracking_resp.error and tracking_resp.response:
            if isinstance(tracking_resp.response, ShpMassTrackingNumber):
                for success_item in tracking_resp.response.success_list:
                    tracking_map[success_item.package_number] = (
                        success_item.tracking_number,
                        success_item.pickup_code,
                    )
                for fail_item in tracking_resp.response.fail_list:
                    fail_pkgs.add(fail_item.package_number)

    return order_details_list, tracking_map, fail_pkgs


lection_query = (
    select(ShopeeOrder)
    .outerjoin(ShopeeOrderInfo, ShopeeOrder.order_sn == ShopeeOrderInfo.order_sn)
    .filter(
        ShopeeOrder.done == False,  # noqa: E712
        ShopeeOrder.status.in_(["READY_TO_SHIP", "PROCESSED", "RETRY_SHIP"]),
        ShopeeOrder.ship_by >= datetime.now(UTC),
    )
    .order_by(ShopeeOrder.ship_by.desc())
)


@app.get("/shopee/orders", response_model=List[ShopeeOrderResponse])
async def get_shopee_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    start_time = time.perf_counter()
    logger.info(
        f"[START] User '{current_user.username}' requested Shopee synchronization."
    )

    # 1. Fast path check
    if shopee_cache.is_valid():
        logger.info(
            "[CACHE HIT] Local order cache valid. Serving directly from database."
        )
        res = get_all_shopee_order_data(db)
        logger.info(
            f"[END] Cache hit pipeline complete. Returned {len(res)} orders in {time.perf_counter() - start_time:.4f}s."
        )
        return [build_shopee_order_response(o, db) for o in res]

    logger.debug(
        "[CACHE MISS] Cache is invalid or expired. Attempting synchronization lock..."
    )

    async with shopee_cache.lock:
        lock_acquired_time = time.perf_counter()
        logger.debug(
            f"[LOCK ACQUIRED] Sync lock locked successfully in {lock_acquired_time - start_time:.4f}s."
        )

        # Double-Checked Locking check
        if shopee_cache.is_valid():
            logger.info(
                "[CACHE HIT] Cache valid inside lock block (parallel sync resolved). Avoiding dual sync."
            )
            return [build_shopee_order_response(o, db) for o in get_all_shopee_order_data(db)]

        now = int(time.time())
        time_from = now - (2 * 24 * 60 * 60)
        STATUSES = ["READY_TO_SHIP", "PROCESSED", "SHIPPED"]

        # Step A: Parallel Fetching of Order SNs
        logger.info(
            f"[STAGE 1] Querying order lists for statuses: {STATUSES} in parallel..."
        )
        stage1_start = time.perf_counter()

        tasks = [fetch_sns_for_status(status, time_from, now) for status in STATUSES]
        results = await asyncio.gather(*tasks)

        all_order_sns = []
        for status, res_list in zip(STATUSES, results):
            logger.debug(
                f" -> Found {len(res_list)} matching items for status [{status}]"
            )
            all_order_sns.extend(res_list)

        order_sns = list(dict.fromkeys(all_order_sns))
        logger.info(
            f"[STAGE 1 DONE] Discovered {len(order_sns)} unique order SNs across statuses in {time.perf_counter() - stage1_start:.4f}s."
        )

        if order_sns:
            # Step B: Parallel Fetching of Detailed Info
            chunk_size = 50
            chunks = [
                order_sns[i : i + chunk_size]
                for i in range(0, len(order_sns), chunk_size)
            ]
            logger.info(
                f"[STAGE 2] Segmented orders into {len(chunks)} chunks of max {chunk_size}. Processing chunk payloads concurrently..."
            )

            stage2_start = time.perf_counter()
            chunk_tasks = [fetch_chunk_details(chunk) for chunk in chunks]
            chunk_results = await asyncio.gather(*chunk_tasks)
            logger.info(
                f"[STAGE 2 DONE] Fetched details for all chunks in {time.perf_counter() - stage2_start:.4f}s."
            )

            # --- Database Processing Phase (Batching) ---
            logger.info(
                "[STAGE 3] Loading state tables to complete batch processing strategy..."
            )
            stage3_start = time.perf_counter()

            existing_orders = {
                o.order_sn: o
                for o in db.execute(
                    select(ShopeeOrder).filter(ShopeeOrder.order_sn.in_(order_sns))
                )
                .scalars()
                .all()
            }
            logger.debug(
                f" -> Cached {len(existing_orders)} pre-existing ShopeeOrder records from local storage map."
            )

            all_package_nums = [
                pkg.package_number
                for details, _, _ in chunk_results
                for detail in details
                if detail.package_list
                for pkg in detail.package_list
            ]
            existing_infos = {
                info.package_number: info
                for info in db.execute(
                    select(ShopeeOrderInfo).filter(
                        ShopeeOrderInfo.package_number.in_(all_package_nums)
                    )
                )
                .scalars()
                .all()
            }
            logger.debug(
                f" -> Cached {len(existing_infos)} pre-existing ShopeeOrderInfo package rows from local storage map."
            )

            # Analytics Counters
            inserted_orders = updated_orders = inserted_packages = updated_packages = 0

            for chunk_idx, (order_details_list, tracking_map, fail_pkgs) in enumerate(
                chunk_results, start=1
            ):
                logger.debug(
                    f" Processing dataset chunk {chunk_idx}/{len(chunks)} ({len(order_details_list)} records)"
                )

                for order_detail in order_details_list:
                    db_order = existing_orders.get(order_detail.order_sn)

                    if not db_order:
                        db_order = ShopeeOrder(
                            order_sn=order_detail.order_sn, owner_user=None
                        )
                        db_order.split_up = order_detail.split_up
                        db_order.status = order_detail.order_status
                        db_order.ship_by = order_detail.ship_by_date
                        db_order.shipping_carrier = (
                            order_detail.package_list[0].shipping_carrier
                            if order_detail.package_list
                            else None
                        )
                        db.add(db_order)
                        inserted_orders += 1

                        if order_detail.recipient_address:
                            addr = ShopeeOrderRecipientAddress(
                                order_sn=order_detail.order_sn,
                                name=order_detail.recipient_address.name,
                                city=order_detail.recipient_address.city,
                            )
                            db.add(addr)

                        for item in order_detail.item_list:
                            if item.model_id == 0:
                                item.model_id = item.model_name = item.model_sku = None
                            db_item = ShopeeOrderItemList(
                                order_sn=order_detail.order_sn,
                                item_id=item.item_id,
                                item_name=item.item_name,
                                item_sku=item.item_sku,
                                model_id=item.model_id,
                                model_name=item.model_name,
                                model_sku=item.model_sku,
                                model_quantity_purchased=item.model_quantity_purchased,
                                image_url=item.image_info.image_url
                                if item.image_info
                                else None,
                            )
                            db.add(db_item)
                    else:
                        db_order.status = order_detail.order_status
                        db_order.shipping_carrier = (
                            order_detail.package_list[0].shipping_carrier
                            if order_detail.package_list
                            else None
                        )
                        updated_orders += 1

                    if order_detail.package_list:
                        for pkg in order_detail.package_list:
                            if pkg.package_number in fail_pkgs:
                                continue

                            info = existing_infos.get(pkg.package_number)
                            tracking_number = pickup_code = None

                            if (
                                order_detail.order_status != "READY_TO_SHIP"
                                and pkg.package_number in tracking_map
                            ):
                                tracking_number, pickup_code = tracking_map[
                                    pkg.package_number
                                ]

                            if not info:
                                info = ShopeeOrderInfo(
                                    order_sn=order_detail.order_sn,
                                    package_number=pkg.package_number,
                                    logistics_status=pkg.logistics_status,
                                    tracking_number=tracking_number,
                                    pickup_code=pickup_code,
                                    note=order_detail.note,
                                )
                                db.add(info)
                                inserted_packages += 1
                            else:
                                info.logistics_status = pkg.logistics_status
                                if order_detail.order_status != "READY_TO_SHIP":
                                    info.tracking_number = tracking_number
                                    info.pickup_code = pickup_code
                                info.note = order_detail.note
                                updated_packages += 1

            logger.info(
                f"[DB MAP COMPLETE] Analytics: Orders (+{inserted_orders}/~{updated_orders}) | Packages (+{inserted_packages}/~{updated_packages})"
            )

            logger.debug(
                "Executing bulk commit operation onto database transaction context..."
            )
            db.commit()
            logger.info(
                f"[STAGE 3 DONE] Persisted all changes to relational storage engine in {time.perf_counter() - stage3_start:.4f}s."
            )

        # Messaging systems
        logger.debug("Broadcasting socket frames out to application listeners...")
        await manager.broadcast(WSMessageType.SHOPEE_ORDERS, db, scope="admin")
        await manager.send_to_user(
            WSMessageType.SHOPEE_ORDERS, db, current_user.username
        )

        shopee_cache.mark_synced()

        final_orders = get_all_shopee_order_data(db)
        logger.info(
            f"[END] Full sync routine terminated successfully. Total runtime: {time.perf_counter() - start_time:.4f}s. Returning {len(final_orders)} data objects."
        )
        return [build_shopee_order_response(o, db) for o in final_orders]


@app.post("/shopee/orders/acquire")
async def acquire_order(
    order_sn: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} acquiring order {order_sn}")

    db_order = (
        db.execute(select(ShopeeOrder).filter(ShopeeOrder.order_sn == order_sn))
        .scalars()
        .first()
    )

    if not db_order:
        raise HTTPException(
            status_code=404,
            detail="Order not found in database. Please fetch orders first.",
        )

    db_order.owner_user = current_user.username
    db.commit()
    shopee_cache.invalidate()

    # broadcast WS updates
    await manager.send_to_user(WSMessageType.SHOPEE_ORDERS, db, current_user.username)
    await manager.broadcast(WSMessageType.SHOPEE_ORDERS, db, scope="admin")

    return {"message": "Order assigned successfully", "order_sn": order_sn}


@app.post("/shopee/reset-cache-state")
async def reset_shopee_cache_state(
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    logger.warning(f"Admin {current_user.username} resetting Shopee cache state")
    shopee_cache.set_token_fatal(False)
    shopee_cache.invalidate()
    return {"message": "Shopee cache state reset successfully"}


# PickItemEntry Endpoints
def merge_or_create_pie(
    db: Session,
    username: str,
    sku: str,
    qty: int,
    order_sn: Optional[str] = None,
) -> PickItemEntry:
    """
    Finds an existing PickItemEntry for the same SKU and order, or creates a new one.
    Sums quantities if merging.
    """
    existing = (
        db.execute(
            select(PickItemEntry).filter(
                PickItemEntry.owner_user == username,
                PickItemEntry.sku == sku,
                PickItemEntry.order_sn == order_sn,
            )
        )
        .scalars()
        .first()
    )

    if existing:
        existing.qty = (existing.qty or 0) + qty
        db.add(existing)
        logger.info(
            f"Merged {qty} into existing PickItemEntry {existing.id} (Total: {existing.qty}) for SKU {sku}"
        )
        return existing
    new_entry = PickItemEntry(
        sku=sku,
        qty=qty,
        order_sn=order_sn,
        owner_user=username,
    )
    db.add(new_entry)
    db.flush()  # To get the ID
    logger.info(
        f"Created new PickItemEntry {new_entry.id} for SKU {sku} (Order: {order_sn})"
    )
    return new_entry


@app.post("/pick-item", response_model=PickItemEntryResponse)
async def create_pie(
    entry_in: PickItemEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Using the merge logic
    entry = merge_or_create_pie(
        db,
        current_user.username,
        entry_in.sku,
        entry_in.qty,
        order_sn=entry_in.order_sn,
    )

    db.commit()
    db.refresh(entry)

    await manager.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, db, username=current_user.username or ""
    )
    await manager.broadcast(WSMessageType.PICK_ITEM_ENTRIES, db, scope="admin")

    item_name = db.execute(
        select(WarehouseItem.item_name).filter(WarehouseItem.sku == entry.sku)
    ).scalar()

    return PickItemEntryResponse(
        id=entry.id,
        sku=entry.sku or "",
        qty=entry.qty or 0,
        order_sn=entry.order_sn,
        timestamp=entry.timestamp,
        owner_user=entry.owner_user,
        item_name=item_name,
    )


@app.get("/pick-item", response_model=List[PickItemEntryResponse])
def read_pies(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    logger.info(f"User {current_user.username} fetching scan entries")
    return get_pie_data(db, current_user.username)


@app.delete("/pick-item")
async def delete_pie(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} deleting scan entry {entry_id}")
    entry = (
        db.execute(
            select(PickItemEntry).filter(
                PickItemEntry.id == entry_id,
                PickItemEntry.owner_user == current_user.username,
            )
        )
        .scalars()
        .first()
    )
    if not entry:
        logger.warning(
            f"Scan entry {entry_id} not found for user {current_user.username}"
        )
        raise HTTPException(status_code=404, detail="Scan entry not found")

    db.delete(entry)
    logger.info(f"Scan entry {entry_id} deleted")

    db.commit()

    await manager.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, db, username=current_user.username
    )

    await manager.broadcast(WSMessageType.PICK_ITEM_ENTRIES, db, scope="admin")
    return {"message": "PickItemEntry deleted"}


@app.post("/pick-item/assign", response_model=PickItemEntryResponse)
async def assign_pie(
    entry_id: int,
    order_sn: str,
    qty: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = (
        db.execute(
            select(PickItemEntry).filter(
                PickItemEntry.id == entry_id,
                PickItemEntry.owner_user == current_user.username,
            )
        )
        .scalars()
        .first()
    )
    order = (
        db.execute(
            select(ShopeeOrder).filter(
                ShopeeOrder.order_sn == order_sn,
                ShopeeOrder.owner_user == current_user.username,
            )
        )
        .scalars()
        .first()
    )

    if not entry or not order:
        raise HTTPException(status_code=404, detail="Entry or Order not found")

    sku = entry.sku
    total_qty = entry.qty

    assign_qty = qty if qty is not None else total_qty
    assign_qty = min(assign_qty, total_qty)

    if assign_qty <= 0:
        raise HTTPException(status_code=400, detail="Invalid quantity")

    if assign_qty >= total_qty:
        db.delete(entry)
    else:
        entry.qty -= assign_qty
        db.add(entry)

    new_entry = merge_or_create_pie(
        db,
        current_user.username,
        sku,
        assign_qty,
        order_sn=order_sn,
    )

    db.commit()
    db.refresh(new_entry)

    await manager.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, db, username=current_user.username
    )
    await manager.broadcast(WSMessageType.PICK_ITEM_ENTRIES, db, scope="admin")

    item_name = db.execute(
        select(WarehouseItem.item_name).filter(WarehouseItem.sku == new_entry.sku)
    ).scalar()

    return PickItemEntryResponse(
        id=new_entry.id,
        sku=new_entry.sku,
        qty=new_entry.qty,
        order_sn=new_entry.order_sn,
        timestamp=new_entry.timestamp,
        owner_user=new_entry.owner_user,
        item_name=item_name,
    )


@app.post("/pick-item/unassign")
async def unassign_pie(
    order_sn: str,
    sku: str,
    qty: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Find entries for this SKU and Label
    entry = (
        db.execute(
            select(PickItemEntry).filter(
                PickItemEntry.owner_user == current_user.username,
                PickItemEntry.sku == sku,
                PickItemEntry.order_sn == order_sn,
            )
        )
        .scalars()
        .first()
    )

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    take_qty = min(qty, entry.qty or 0)

    # 1. Reduce from original
    entry.qty = (entry.qty or 0) - take_qty
    if entry.qty <= 0:
        db.delete(entry)
    else:
        db.add(entry)

    # 2. Merge/Create as unassigned
    merge_or_create_pie(
        db,
        current_user.username,
        sku,
        take_qty,
        order_sn=None,
    )

    db.commit()

    await manager.send_to_user(
        WSMessageType.PICK_ITEM_ENTRIES, db, username=current_user.username
    )
    await manager.broadcast(WSMessageType.PICK_ITEM_ENTRIES, db, scope="admin")

    return {"message": "SKU unassigned successfully"}
