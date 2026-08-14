import logging
import secrets
from typing import Optional

from ..redis_service import redis_mgr
from ...config import get_config_int

logger = logging.getLogger("backend.services.managers.ticket_manager")

WS_TICKET_TTL_SECONDS = get_config_int("WS_TICKET_TTL_SECONDS", 30)


class TicketManager:
    def __init__(self, default_ttl: int = WS_TICKET_TTL_SECONDS):
        self.default_ttl = default_ttl

    async def generate_ticket(self, username: str, ttl_seconds: Optional[int] = None) -> str:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        ticket = secrets.token_urlsafe(32)
        key = f"ws_token:{ticket}"
        try:
            await redis_mgr.set(key, username, ex=ttl)

            logger.debug(
                "websocket_ticket_generated",
                extra={"event": "websocket.ticket.generated", "username": username},
            )
        except Exception as e:
            logger.exception(
                "websocket_ticket_store_failed",
                extra={"event": "websocket.ticket.store_failed", "username": username},
            )
            raise RuntimeError("Unable to create WebSocket ticket") from e
        return ticket

    async def consume_ticket(self, ticket: str) -> Optional[str]:
        key = f"ws_token:{ticket}"
        try:
            username = await redis_mgr.get(key)
            if username:
                await redis_mgr.delete(key)
                return username
        except Exception:
            logger.exception(
                "websocket_ticket_consume_failed",
                extra={"event": "websocket.ticket.consume_failed"},
            )
        return None
