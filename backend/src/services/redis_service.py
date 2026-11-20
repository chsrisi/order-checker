import os
import logging
from typing import Optional
import redis.asyncio as redis

from ..config import get_config_value

logger = logging.getLogger("backend.services.redis")


class RedisManager:
    def __init__(self):
        self._client = None

    def initialize(self):
        if self._client is None:
            redis_url = get_config_value("REDIS_URL")
            if redis_url is None:
                redis_url = os.getenv("REDIS_URL")
            if redis_url is None:
                raise ValueError("REDIS_URL configuration is missing!")
            self._client = redis.from_url(redis_url, decode_responses=True)

    async def get(self, key: str):
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None):
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.set(key, value, ex=ex)

    async def delete(self, key: str):
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.delete(key)

    async def getdel(self, key: str):
        """Atomically read and delete a key (Redis >= 6.2)."""
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.getdel(key)

    async def incr_with_ttl(self, key: str, ttl: int) -> int:
        """Increment a counter; the first increment starts its expiry window."""
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        value = await self._client.incr(key)
        if value == 1:
            await self._client.expire(key, ttl)
        return value

    async def expire(self, key: str, ttl: int):
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.expire(key, ttl)

    async def close(self):
        if self._client:
            await self._client.close()
            logger.info("Redis connection pool closed")


redis_mgr = RedisManager()
