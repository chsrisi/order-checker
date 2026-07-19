import logging
from typing import Optional

from ..redis_service import RedisManager
from ...config import get_config_value

logger = logging.getLogger("backend.services.managers.shopee_token_manager")

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
