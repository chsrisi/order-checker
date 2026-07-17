import os
import logging
from typing import Optional
import redis.asyncio as redis

from .config import get_config_value

logger = logging.getLogger("backend.redis")

# Initialize the async Redis client
REDIS_URL = get_config_value("REDIS_URL", os.getenv("REDIS_URL"))
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


async def get_shopee_token(key: str) -> Optional[str]:
    """
    Retrieves the Shopee token (ACCESS_TOKEN or REFRESH_TOKEN) from Redis.
    If not found in Redis, loads the initial value from configuration,
    seeds it into Redis, and returns it.
    """
    redis_key = f"shopee:{key.lower()}"
    try:
        val = await redis_client.get(redis_key)
        if val:
            logger.debug(f"Retrieved {redis_key} from Redis")
            return val
    except Exception as e:
        logger.error(f"Redis error getting {redis_key}: {e}")

    # Fallback to loading the initial/configured value (env or secret)
    fallback = get_config_value(key.upper())
    if fallback:
        logger.info(f"Seeding {redis_key} to Redis from initial configuration fallback")
        await set_shopee_token(key, fallback)
        return fallback

    return None


async def set_shopee_token(key: str, value: str):
    """
    Saves the Shopee token (ACCESS_TOKEN or REFRESH_TOKEN) to Redis.
    """
    redis_key = f"shopee:{key.lower()}"
    try:
        await redis_client.set(redis_key, value)
        logger.info(f"Saved {redis_key} to Redis successfully")
    except Exception as e:
        logger.error(f"Redis error setting {redis_key}: {e}")
