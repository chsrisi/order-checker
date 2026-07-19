import asyncio
import logging
import secrets
from typing import Any, Dict, List, Optional
from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from . import queries
from .redis_service import redis_mgr, RedisManager
from .bom_service import build_shopee_order_response
from ..config import get_config_value
from ..models import WSMessageType, OutboundResponse, StockResponse

logger = logging.getLogger("backend.services.manager")


class TicketManager:
    async def generate_ticket(self, username: str, ttl_seconds: int = 30) -> str:
        ticket = secrets.token_urlsafe(32)
        key = f"ws_token:{ticket}"
        try:
            await redis_mgr.set(key, username, ex=ttl_seconds)
            logger.debug(f"Generated WS ticket in Redis for user {username}: {ticket}")
        except Exception as e:
            logger.error(f"Failed to save WS ticket in Redis: {e}")
        return ticket

    async def consume_ticket(self, ticket: str) -> Optional[str]:
        key = f"ws_token:{ticket}"
        try:
            username = await redis_mgr.get(key)
            if username:
                await redis_mgr.delete(key)
                return username
        except Exception as e:
            logger.error(f"Failed to consume WS ticket from Redis: {e}")
        return None


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
        user = queries.get_user_data(db, username)
        if user:
            is_admin = user.scope == "admin"
        else:
            raise ValueError(f"User {username} not found")

        data = None

        if message_type == WSMessageType.USERS:
            data = queries.get_all_user_data(db)
        elif message_type == WSMessageType.OUTBOUNDS:
            outbounds = (
                queries.get_all_outbound_data(db)
                if is_admin
                else queries.get_outbounds_data(db, username)
            )
            data = [OutboundResponse.model_validate(o) for o in outbounds]
        elif message_type == WSMessageType.SHOPEE_ORDERS:
            orders = (
                queries.get_all_shopee_order_data(db)
                if is_admin
                else queries.get_shopee_order_data(db, username)
            )
            data = [build_shopee_order_response(o, db) for o in orders]
        elif message_type == WSMessageType.PICK_ITEM_ENTRIES:
            data = (
                queries.get_all_pie_data(db)
                if is_admin
                else queries.get_pie_data(db, username)
            )
        elif message_type == WSMessageType.STOCKS:
            stocks = queries.get_all_stocks_data(db, join_warehouse=True)
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


class ShopeeTokenManager:
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager

    async def get_token(self, key: str) -> Optional[str]:
        redis_key = f"shopee:{key.lower()}"
        val = await self.redis.get(redis_key)
        if val:
            logger.debug(f"Retrieved {redis_key} from Redis")
            return val

        # Fallback to loading the initial/configured value (env or secret)
        fallback = get_config_value(key.upper())
        if fallback:
            logger.info(
                f"Seeding {redis_key} to Redis from initial configuration fallback"
            )
            await self.set_token(key, fallback)
            return fallback

        return None

    async def set_token(self, key: str, value: str):
        redis_key = f"shopee:{key.lower()}"
        await self.redis.set(redis_key, value)


ticket_mgr = TicketManager()
conn_mgr = ConnectionManager()
token_mgr = ShopeeTokenManager(redis_mgr)
