import asyncio
import logging
import logging.handlers
import os
import time
from typing import Any
from contextlib import asynccontextmanager

import aiohttp
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .exceptions import DomainException, domain_exception_handler

from .config import get_config_value
from .services.redis_service import redis_mgr
from .services import auth_service, managers, queries
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
)

load_dotenv(find_dotenv())

# Logger configuration
LOGS_DIR = "temp/logs"
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            os.path.join(LOGS_DIR, "backend.log"),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
        ),
    ],
)
logger = logging.getLogger("backend")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup logic
    logger.info("Application starting up...")

    # Start background rotation and token cleanup tasks
    bg_tasks: list[asyncio.Task[Any]] = []
    bg_tasks.append(asyncio.create_task(managers.key_mgr.rotate_keys_task()))
    bg_tasks.append(asyncio.create_task(auth_service.remove_outdated_refresh_task()))

    # Initialize Persistent aiohttp Session
    session = aiohttp.ClientSession()
    _app.state.aiohttp_session = session
    shopee_client_session.session = session
    logger.info(
        "Persistent aiohttp session initialized in app.state and shopee_service"
    )

    # Seed admin user via queries service
    admin_pass = get_config_value("ADMIN_PASSWORD")
    hashed_pw = auth_service.get_password_hash(str(admin_pass or "admin"))
    queries.seed_admin_user(hashed_pw)

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

app.add_exception_handler(DomainException, domain_exception_handler)

# Include separated sub-routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(outbound.router)
app.include_router(items.router)
app.include_router(stocks.router)
app.include_router(shopee.router)
app.include_router(pick_items.router)
app.include_router(websocket.router)
