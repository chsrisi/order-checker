"""In-memory stand-in for RedisManager. Each command yields once and then runs atomically, as
on the server, so ``asyncio.gather`` really interleaves callers."""

import asyncio
import time


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.expiry: dict[str, float] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.offset = 0.0  # advance() moves the clock
        self.broken = False

    def now(self):
        return time.time() + self.offset

    def advance(self, seconds):
        self.offset += seconds

    async def _step(self):
        await asyncio.sleep(0)
        if self.broken:
            raise ConnectionError("redis down")
        for key in [k for k, at in self.expiry.items() if at <= self.now()]:
            self.values.pop(key, None)
            self.expiry.pop(key)

    def _put(self, key, value, ex):
        self.values[key] = value
        self.expiry.pop(key, None)
        if ex:
            self.expiry[key] = self.now() + ex

    async def get(self, key):
        await self._step()
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        await self._step()
        self._put(key, value, ex)

    async def set_nx(self, key, value, ex):
        await self._step()
        if key in self.values:
            return None
        self._put(key, value, ex)
        return True

    async def getset(self, key, value, ex):
        await self._step()
        old = self.values.get(key)
        self._put(key, value, ex)
        return old

    async def getdel(self, key):
        await self._step()
        return self.values.pop(key, None)

    async def delete(self, key):
        await self._step()
        return int(self.values.pop(key, None) is not None)

    async def expire(self, key, ttl):
        await self._step()
        if key not in self.values:
            return 0
        self.expiry[key] = self.now() + ttl
        return 1

    async def incr_with_ttl(self, key, ttl):
        await self._step()
        value = int(self.values.get(key, 0)) + 1
        if value == 1:
            self._put(key, "1", ttl)
        else:
            self.values[key] = str(value)
        return value

    async def zadd(self, key, member, score):
        await self._step()
        self.zsets.setdefault(key, {})[member] = score

    async def zrem(self, key, member):
        await self._step()
        self.zsets.get(key, {}).pop(member, None)

    async def zcard(self, key):
        await self._step()
        return len(self.zsets.get(key, {}))

    async def zrange(self, key):
        await self._step()
        zset = self.zsets.get(key, {})
        return sorted(zset, key=zset.get)

    async def zremrangebyscore(self, key, low, high):
        await self._step()
        zset = self.zsets.get(key, {})
        for m in [m for m, s in zset.items() if low <= s <= high]:
            zset.pop(m)
