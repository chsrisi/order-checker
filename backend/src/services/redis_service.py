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

    async def set_nx(self, key: str, value: str, ex: int):
        """Set only if the key does not exist; truthy when this call set it."""
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.set(key, value, ex=ex, nx=True)

    async def getset(self, key: str, value: str, ex: int):
        """Set and return the previous value, atomically (Redis >= 6.2)."""
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.set(key, value, ex=ex, get=True)

    async def zadd(self, key: str, member: str, score: float):
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.zadd(key, {member: score})

    async def zrem(self, key: str, member: str):
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.zrem(key, member)

    async def zcard(self, key: str) -> int:
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.zcard(key)

    async def zrange(self, key: str) -> list[str]:
        """Every member, lowest score first."""
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.zrange(key, 0, -1)

    async def zrangebyscore(self, key: str, low: float, high: float) -> list[str]:
        """Members with ``low <= score <= high``, lowest score first."""
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.zrangebyscore(key, low, high)

    async def exists(self, key: str) -> bool:
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return bool(await self._client.exists(key))

    async def zremrangebyscore(self, key: str, low: float, high: float):
        self.initialize()
        if self._client is None:
            raise RuntimeError("Redis client is not initialized")
        return await self._client.zremrangebyscore(key, low, high)

    async def close(self):
        if self._client:
            await self._client.close()
            logger.info("Redis connection pool closed")


redis_mgr = RedisManager()
