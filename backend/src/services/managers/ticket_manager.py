import logging
import secrets
from typing import Optional

from ..redis_service import redis_mgr

logger = logging.getLogger("backend.services.managers.ticket_manager")

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
