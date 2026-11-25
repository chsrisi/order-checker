import asyncio
import logging
import time
import uuid
from typing import Any
from contextlib import asynccontextmanager

import aiohttp
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .exceptions import (
    ClientUpgradeRequired,
    DomainException,
    client_upgrade_required_handler,
    domain_exception_handler,
)
from .logging_config import configure_logging, request_id_context

from .config import API_VERSION, EXPOSE_API_DOCS, PRODUCTION_RULES, get_config_value
from .settings_guard import enforce_startup_rules
from .services.redis_service import redis_mgr
from .services import auth_service, managers, queries, retention_service, shopee_service
from .services.shopee_service import shopee_client_session
from .routers import (
    auth,
    admin,
    outbound,
    items,
    stocks,
    shopee,
    pick_items,
    websocket,
    meta,
    client_release,
    device,
)
from .routers.v2 import include_v2, login_requests, order_picks

load_dotenv(find_dotenv())
configure_logging()
logger = logging.getLogger("backend")

OPENAPI_TAGS = [
    {
        "name": "authentication",
        "description": "Account login, token rotation, and public signing keys.",
    },
    {"name": "admin", "description": "Administrator-only user, history, and export operations."},
    {
        "name": "shopee configuration",
        "description": "Protected management of Shopee access credentials.",
    },
    {"name": "BOM", "description": "Administrator-only bill-of-material queries."},
    {"name": "outbound", "description": "Outbound label scanning and period closure."},
    {"name": "items", "description": "Warehouse SKU and barcode lookup."},
    {"name": "stocks", "description": "Inventory reads, adjustments, and location transfers."},
    {"name": "Shopee", "description": "Shopee order synchronization and assignment."},
    {"name": "pick items", "description": "Per-user picking list operations."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup logic
    logger.info("application_starting", extra={"event": "application.start"})
    enforce_startup_rules()  # before any background task or seeding

    # Start background rotation and token cleanup tasks
    bg_tasks: list[asyncio.Task[Any]] = []
    bg_tasks.append(asyncio.create_task(managers.key_mgr.rotate_keys_task()))
    bg_tasks.append(asyncio.create_task(auth_service.remove_outdated_refresh_task()))
    bg_tasks.append(asyncio.create_task(retention_service.recipient_retention_task()))
    bg_tasks.append(asyncio.create_task(shopee_service.auto_sync_task()))

    # Initialize Persistent aiohttp Session
    session = aiohttp.ClientSession()
    _app.state.aiohttp_session = session
    shopee_client_session.session = session
    logger.info("Persistent aiohttp session initialized in app.state and shopee_service")

    # Seed admin user via queries service
    admin_username = get_config_value("ADMIN_USERNAME", "admin") or "admin"
    admin_pass = get_config_value("ADMIN_PASSWORD", "admin") or "admin"
    if admin_pass == "admin":
        logger.warning(
            "default_admin_password_in_use",
            extra={"event": "security.default_admin_password"},
        )
    hashed_pw = auth_service.get_password_hash(admin_pass)
    queries.seed_admin_user(admin_username, hashed_pw)

    yield

    # Shutdown logic
    logger.info("Application shutting down...")

    for task in bg_tasks:
        task.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)
    logger.info("Background tasks cancelled")

    if shopee_client_session.session:
        await shopee_client_session.session.close()
        logger.info("Persistent aiohttp session closed")

    await redis_mgr.close()
    logger.info("Redis client connection pool closed")


app = FastAPI(
    title="Bakingholic Order Checker API",
    summary="Order fulfillment, warehouse inventory, and Shopee synchronization API.",
    description=(
        "Backend for the Bakingholic operator and administrator applications. "
        "Authenticate with an RS256 bearer token. WebSocket clients first request "
        "a one-use ticket from `POST /auth/ws-token`; the WebSocket protocol is "
        "documented in the project API guide because OpenAPI does not describe it."
    ),
    version=API_VERSION,
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
    license_info={"name": "Proprietary"},
    # Interactive docs and the schema are off under production rules unless
    # EXPOSE_API_DOCS=1. Contract tests call app.openapi() directly, so they are unaffected.
    docs_url="/docs" if EXPOSE_API_DOCS else None,
    redoc_url="/redoc" if EXPOSE_API_DOCS else None,
    openapi_url="/openapi.json" if EXPOSE_API_DOCS else None,
)


@app.middleware("http")
async def log_requests(request: Request, call_next: Any):
    started_at = time.perf_counter()
    path = request.url.path
    method = request.method
    client_host = request.client.host if request.client else "unknown"
    supplied_request_id = request.headers.get("X-Request-ID", "").strip()
    request_id = supplied_request_id[:128] or uuid.uuid4().hex
    context_token = request_id_context.set(request_id)
    logger.info(
        "request_started",
        extra={
            "event": "http.request.started",
            "http_method": method,
            "http_path": path,
            "client_ip": client_host,
        },
    )
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.exception(
            "request_failed",
            extra={
                "event": "http.request.failed",
                "http_method": method,
                "http_path": path,
                "duration_ms": duration_ms,
            },
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            extra={
                "event": "http.request.completed",
                "http_method": method,
                "http_path": path,
                "http_status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
    finally:
        request_id_context.reset(context_token)


def cors_options(
    production_rules: bool, origins_raw: str | None, origin_regex: str | None
) -> dict[str, Any] | None:
    """CORS middleware settings, or ``None`` for no CORS at all.

    Production rules: only an explicit origin list (wildcards and regexes are refused at
    startup). With no origins there is no CORS middleware: the admin web app is same-origin
    behind nginx and the operator client is native (F-M14). Development keeps the permissive
    defaults, including any localhost port for ``flutter run -d chrome``.
    """
    origins = [o.strip() for o in (origins_raw or "").split(",") if o.strip()]
    if production_rules:
        explicit = [o for o in origins if o != "*"]
        if not explicit:
            return None
        return {
            "allow_origins": explicit,
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }

    if not origins or origins == ["*"]:
        return {
            "allow_origins": ["*"],
            "allow_credentials": False,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    return {
        "allow_origins": origins,
        "allow_origin_regex": origin_regex or r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


_cors = cors_options(
    PRODUCTION_RULES,
    get_config_value("CORS_ORIGINS"),
    get_config_value("CORS_ORIGIN_REGEX"),
)
if _cors is not None:
    app.add_middleware(CORSMiddleware, **_cors)

app.add_exception_handler(DomainException, domain_exception_handler)
app.add_exception_handler(ClientUpgradeRequired, client_upgrade_required_handler)

# Include separated sub-routers
app.include_router(auth.router)
app.include_router(auth.public_router)
app.include_router(admin.router)
app.include_router(outbound.router)
app.include_router(items.router)
app.include_router(stocks.router)
app.include_router(shopee.router)
app.include_router(pick_items.router)
app.include_router(websocket.router)
app.include_router(websocket.v2_router)
app.include_router(client_release.router)
app.include_router(device.router)
app.include_router(meta.router)
app.include_router(order_picks.router)
app.include_router(login_requests.router)
# Contract v2 mirrors the client operations registered above (T6.3).
include_v2(
    app,
    [
        auth.router,
        outbound.router,
        shopee.router,
        items.router,
        stocks.router,
        meta.router,
    ],
)
