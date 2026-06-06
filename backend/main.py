import asyncio
import csv
import hashlib
import hmac
import io
import logging
import logging.handlers
import os
import secrets
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, cast, Generator

import aiohttp
import jwt
import jwt.exceptions as jwt_exc
from dotenv import load_dotenv, set_key
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
from sqlalchemy import create_engine, select, delete, update, Sequence, or_
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
    ShpOrderList,
    OrderListT,
    ShpMassTrackingNumber,
)
from keys import (
    KeyManager,
    ACCESS_TTL_SECONDS,
)

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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup logic
    logger.info("Application starting up...")

    # Start background rotation task
    bg_tasks: list[asyncio.Task[Any]] = []
    bg_tasks.append(asyncio.create_task(key_manager.rotate_keys_task()))
    bg_tasks.append(asyncio.create_task(remove_outdated_refresh()))

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
    items = db.execute(query).scalars().all()
    return items


def get_all_outbound_data(db: Session) -> Sequence[OutboundItem]:
    query = (
        select(OutboundItem)
        .filter(OutboundItem.closed == False)  # noqa: E712
        .order_by(OutboundItem.created_at.desc())
    )
    items = db.execute(query).scalars().all()
    return items


def get_shopee_order_data(db: Session, username: str) -> Sequence[ShopeeOrder]:
    query = select(ShopeeOrder).filter(ShopeeOrder.owner_user == username)
    orders = db.execute(query).scalars().all()
    return orders


def get_all_shopee_order_data(db: Session) -> Sequence[ShopeeOrder]:
    query = select(ShopeeOrder)
    orders = db.execute(query).scalars().all()
    return orders


def get_pie_data(db: Session, username: str) -> Sequence[PickItemEntry]:
    query = (
        select(PickItemEntry)
        .filter(PickItemEntry.owner_user == username)
        .order_by(PickItemEntry.timestamp.desc())
    )
    entries = db.execute(query).scalars().all()
    return entries


def get_all_pie_data(db: Session) -> Sequence[PickItemEntry]:
    query = select(PickItemEntry).order_by(PickItemEntry.timestamp.desc())
    entries = db.execute(query).scalars().all()
    return entries


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
            data = (
                get_all_outbound_data(db)
                if is_admin
                else get_outbounds_data(db, username)
            )
        elif message_type == WSMessageType.SHOPEE_ORDERS:
            data = (
                get_all_shopee_order_data(db)
                if is_admin
                else get_shopee_order_data(db, username)
            )
            data = [ShopeeOrderResponse.model_validate(o) for o in data]
        elif message_type == WSMessageType.PICK_ITEM_ENTRIES:
            data = get_all_pie_data(db) if is_admin else get_pie_data(db, username)
        elif message_type == WSMessageType.STOCKS:
            data = get_all_stocks_data(db)

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
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    with ctx_get_db() as db:
        try:
            user = get_user(token, db)
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise

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
    logger.info("Refreshing Shopee access token")
    shop_id_env = os.getenv("SHOP_ID")
    partner_id_env = os.getenv("PARTNER_ID")
    partner_key_env = os.getenv("PARTNER_KEY")
    refresh_token = os.getenv("REFRESH_TOKEN")

    if not all([shop_id_env, partner_id_env, partner_key_env, refresh_token]):
        logger.error("Missing Shopee environment variables for token refresh")
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
            # Shopee always returns 200 with error/success info in the body
            ret = ShopeeTokenResponse.model_validate(await resp.json())

            if ret.error:
                logger.error(
                    f"Shopee Refresh Error: {ret.error} - {ret.message} (ReqID: {ret.request_id})"
                )
                return None, None

            if ret.access_token and ret.refresh_token:
                set_key(".env", "ACCESS_TOKEN", ret.access_token)
                set_key(".env", "REFRESH_TOKEN", ret.refresh_token)
                # Manually update environment variables so the current process has them
                os.environ["ACCESS_TOKEN"] = ret.access_token
                os.environ["REFRESH_TOKEN"] = ret.refresh_token
                logger.info("Shopee tokens updated in .env and environment")
                return ret.access_token, ret.refresh_token

    except Exception as e:
        logger.error(f"Exception during Shopee token refresh: {str(e)}")
        return None, None
    return None, None


async def shopee_request(
    path: str,
    params: Optional[dict[str, Any]] = None,
    body: Optional[dict[str, Any]] = None,
    method: str = "GET",
    retry_on_expiry: bool = True,
) -> Optional[ShopeeResponse]:
    logger.info(f"Making Shopee API request to path: {path}")
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

    # Sign: partner_id + api path + timestamp + access_token + shop_id + partner_key
    tmp_base_string = f"{partner_id}{path}{timest}{access_token}{shop_id}"
    base_string = tmp_base_string.encode()
    sign = hmac.new(partner_key, base_string, hashlib.sha256).hexdigest()

    # Base params
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
            # Shopee always returns 200 with error/success info in the body
            ret = ShopeeResponse.model_validate(await resp.json())

            if ret.error:
                logger.error(
                    f"Shopee API Error: {ret.error} - {ret.message} (ReqID: {ret.request_id})"
                )

                # Auto-refresh on token expiry
                if retry_on_expiry and ret.error in ["invalid_acceess_token"]:
                    logger.info(
                        "Token might be expired, attempting one-time refresh..."
                    )
                    new_at, _ = await refresh_shopee_token()
                    if new_at:
                        return await shopee_request(
                            path,
                            params or {},
                            body or {},
                            method,
                            retry_on_expiry=False,
                        )

            logger.info(f"API success - Request ID: {ret.request_id}")
            return ret
    except HTTPException as e:
        logger.error(f"Exception during Shopee API request: {str(e)}")
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


# JWT ----
@app.post("/.well-known/jwks.json")
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
    return orders


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
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Content", "Tag", "Created At", "Owner"])

    for item in items:
        writer.writerow(
            [
                item.id,
                item.content,
                item.tag or "",
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
        .first()
    )

    if existing:
        logger.warning(
            "Duplicate scan detected for user %s: %s",
            current_user.username,
            item.content,
        )
        raise HTTPException(status_code=409, detail="Duplicate scan detected")

    db_item = OutboundItem(
        content=item.content,
        owner_user=current_user.username,
        tag=item.tag,
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
        tag=db_item.tag if db_item.tag else None,
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
    result = (
        db.execute(
            update(OutboundItem)
            .filter(OutboundItem.content.in_(contents), OutboundItem.closed == False)  # noqa: E712
            .values(closed=True, closed_at=now)
        )
        .scalars()
        .all()
    )

    outbound_count = len(result)
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
        )
        orders_done_count = len(result_orders.scalars().all())

    db.commit()

    logger.info(
        f"Closed period: {outbound_count} outbound, {unknown_count} unknown, "
        f"{orders_done_count} orders done"
    )

    # Broadcast updates
    await manager.broadcast(WSMessageType.OUTBOUNDS, db, scope="admin")

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
@app.post("/stocks", response_model=StockResponse)
async def set_stock(
    stock_in: StockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(
        f"User {current_user.username} {stock_in.mode} stock for {stock_in.sku} value {stock_in.stock}"
    )
    # Verify item exists in warehouse_items
    item = (
        db.execute(select(WarehouseItem).filter(WarehouseItem.sku == stock_in.sku))
        .scalars()
        .first()
    )
    if not item:
        logger.warning(f"Stock update failed: SKU {stock_in.sku} not found")
        raise HTTPException(
            status_code=404, detail=f"Item with SKU {stock_in.sku} not found"
        )

    # Check if stock record exists
    db_stock = (
        db.execute(select(Stock).filter(Stock.sku == stock_in.sku)).scalars().first()
    )
    if db_stock:
        if stock_in.mode == "add":
            db_stock.stock += stock_in.stock
        else:
            db_stock.stock = stock_in.stock
        logger.info(f"Updated existing stock record for {stock_in.sku}")
    else:
        db_stock = Stock(
            sku=stock_in.sku,
            stock=stock_in.stock,
            location=item.location,
        )
        db.add(db_stock)
        logger.info(f"Created new stock record for {stock_in.sku}")

    db.commit()
    db.refresh(db_stock)

    # Broadcast update
    await manager.broadcast(WSMessageType.STOCKS, db)

    wh_item = (
        db.execute(select(WarehouseItem).filter(WarehouseItem.sku == db_stock.sku))
        .scalars()
        .first()
    )

    return StockResponse(
        id=db_stock.id,
        sku=db_stock.sku,
        stock=db_stock.stock,
        location=db_stock.location,
        item_name=wh_item.item_name if wh_item else None,
    )


# Shopee Orders Endpoints ----
@app.get("/shopee/orders", response_model=List[ShopeeOrderResponse])
async def get_shopee_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} fetching orders from Shopee API")

    now = int(time.time())
    time_from = now - (2 * 24 * 60 * 60)  # 2 days ago

    STATUSES = ["READY_TO_SHIP", "PROCESSED", "SHIPPED"]
    all_order_sns: list[str] = []

    for order_status in STATUSES:
        cursor = ""
        while True:
            params: dict[str, Any] = {
                "page_size": 100,
                "time_range_field": "create_time",
                "time_from": time_from,
                "time_to": now,
                "order_status": order_status,
            }
            if cursor:
                params["cursor"] = cursor

            shopee_resp = await shopee_request(
                path="/api/v2/order/get_order_list",
                params=params,
            )

            if not shopee_resp or shopee_resp.error:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to fetch {order_status} orders from Shopee",
                )

            resp_data = shopee_resp.response
            if not isinstance(resp_data, ShpOrderList):
                raise TypeError(
                    "Invalid response type from Shopee API for get_order_list"
                )

            all_order_sns.extend(item.order_sn for item in resp_data.order_list)

            if not resp_data.more:
                break
            cursor = resp_data.next_cursor or ""

    order_sns = list(dict.fromkeys(all_order_sns))

    if order_sns:
        # Fetch details in chunks of 50
        chunk_size = 50
        for i in range(0, len(order_sns), chunk_size):
            chunk = order_sns[i : i + chunk_size]
            sn_str = ",".join(chunk)

            detail_resp = await shopee_request(
                path="/api/v2/order/get_order_detail",
                params={
                    "order_sn_list": sn_str,
                    "response_optional_fields": "recipient_address,note,item_list,split_up,shipping_carrier,package_list,",
                },
            )

            if not detail_resp or detail_resp.error:
                logger.error(f"Failed to fetch Shopee details for chunk: {sn_str}")
                continue

            detail_data = detail_resp.response
            if not isinstance(detail_data, OrderListT):
                logger.error(
                    "Invalid response type from Shopee API for get_order_detail"
                )
                continue

            order_details_list = detail_data.order_list
            if not isinstance(order_details_list, list):
                logger.error("Invalid response order_list type from Shopee API")
                continue

            # Fetch tracking numbers/pickup codes for non-READY_TO_SHIP orders
            tracking_map = {}
            fail_pkgs = set()
            processed_packages: list[dict[str, str]] = []
            for order_detail in order_details_list:
                if (
                    order_detail.order_status != "READY_TO_SHIP"
                    and order_detail.package_list
                ):
                    for pkg in order_detail.package_list:
                        processed_packages.append(
                            {
                                "package_number": pkg.package_number,
                            }
                        )

            if processed_packages:
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

            for order_detail in order_details_list:
                db_order = (
                    db.execute(
                        select(ShopeeOrder).filter(
                            ShopeeOrder.order_sn == order_detail.order_sn
                        )
                    )
                    .scalars()
                    .first()
                )

                if not db_order:
                    db_order = ShopeeOrder(
                        order_sn=order_detail.order_sn, owner_user=None
                    )
                    db_order.split_up = order_detail.split_up
                    db_order.status = order_detail.order_status
                    db_order.ship_by = order_detail.ship_by_date
                    db.add(db_order)

                    if order_detail.recipient_address:
                        addr = ShopeeOrderRecipientAddress(
                            order_sn=order_detail.order_sn,
                            name=order_detail.recipient_address.name,
                            city=order_detail.recipient_address.city,
                        )
                        db.add(addr)

                    for item in order_detail.item_list:
                        if item.model_id == 0:
                            item.model_id = None
                            item.model_name = None
                            item.model_sku = None
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

                # Update ShopeeOrderInfo for each package
                if order_detail.package_list:
                    for pkg in order_detail.package_list:
                        if pkg.package_number in fail_pkgs:
                            continue

                        info = (
                            db.execute(
                                select(ShopeeOrderInfo).filter(
                                    ShopeeOrderInfo.package_number == pkg.package_number
                                )
                            )
                            .scalars()
                            .first()
                        )

                        tracking_number = None
                        pickup_code = None
                        if order_detail.order_status != "READY_TO_SHIP":
                            if pkg.package_number in tracking_map:
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
                        else:
                            info.logistics_status = pkg.logistics_status
                            if order_detail.order_status != "READY_TO_SHIP":
                                info.tracking_number = tracking_number
                                info.pickup_code = pickup_code
                            info.note = order_detail.note

        db.commit()

    orders_in_db: list[ShopeeOrder] = []
    if order_sns:
        orders_in_db = list(
            db.execute(select(ShopeeOrder).filter(ShopeeOrder.order_sn.in_(order_sns)))
            .scalars()
            .all()
        )

    await manager.broadcast(WSMessageType.SHOPEE_ORDERS, db, scope="admin")
    await manager.send_to_user(WSMessageType.SHOPEE_ORDERS, db, current_user.username)

    # Eagerly load or just use from_attributes via response_model
    # The relationships in ShopeeOrder might require a refresh or we return them as is
    return orders_in_db


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

    return {"message": "Order assigned successfully", "order_sn": order_sn}


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

    return PickItemEntryResponse(
        id=entry.id,
        sku=entry.sku or "",
        qty=entry.qty or 0,
        order_sn=entry.order_sn,
        timestamp=entry.timestamp,
        owner_user=entry.owner_user,
    )


@app.get("/pick-item", response_model=List[PickItemEntryResponse])
def read_pies(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    logger.info(f"User {current_user.username} fetching scan entries")
    entries = (
        db.execute(
            select(PickItemEntry)
            .filter(PickItemEntry.owner_user == current_user.username)
            .order_by(PickItemEntry.timestamp.desc())
        )
        .scalars()
        .all()
    )
    logger.debug(f"Found {len(entries)} scan entries")
    return entries


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
    return PickItemEntryResponse(
        id=new_entry.id,
        sku=new_entry.sku,
        qty=new_entry.qty,
        order_sn=new_entry.order_sn,
        timestamp=new_entry.timestamp,
        owner_user=new_entry.owner_user,
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
