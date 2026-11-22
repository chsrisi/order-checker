import json
import logging
import secrets
from typing import NamedTuple, Optional

from ..redis_service import redis_mgr
from ...config import get_config_int

logger = logging.getLogger("backend.services.managers.ticket_manager")

WS_TICKET_TTL_SECONDS = get_config_int("WS_TICKET_TTL_SECONDS", 30)


class TicketClaims(NamedTuple):
    username: str
    sid: Optional[str]


class TicketManager:
    def __init__(self, default_ttl: int = WS_TICKET_TTL_SECONDS):
        self.default_ttl = default_ttl

    async def generate_ticket(
        self, username: str, ttl_seconds: Optional[int] = None, sid: Optional[str] = None
    ) -> str:
        """Store a one-use ticket. The value carries the session id, so the socket can be
        tied to (and closed with) that session (T6.2)."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        ticket = secrets.token_urlsafe(32)
        key = f"ws_token:{ticket}"
        try:
            await redis_mgr.set(key, json.dumps({"username": username, "sid": sid}), ex=ttl)

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

    async def consume_ticket(self, ticket: str) -> Optional[TicketClaims]:
        key = f"ws_token:{ticket}"
        try:
            # GETDEL: read and delete in one step so a ticket can open one socket only (F-M11).
            raw = await redis_mgr.getdel(key)
            if raw:
                value = json.loads(raw)
                if isinstance(value, dict) and value.get("username"):
                    return TicketClaims(value["username"], value.get("sid"))
        except Exception:
            logger.exception(
                "websocket_ticket_consume_failed",
                extra={"event": "websocket.ticket.consume_failed"},
            )
        return None
