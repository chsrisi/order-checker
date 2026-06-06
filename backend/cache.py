import asyncio
import logging
import time

logger = logging.getLogger("backend.cache")

SHOPEE_CACHE_TTL_SECONDS = 120


class ShopeeOrderCache:
    def __init__(self, cache_ttl: int = SHOPEE_CACHE_TTL_SECONDS):
        self._cache_ttl = cache_ttl
        self._last_sync = 0.0
        self._lock = asyncio.Lock()

    def is_valid(self, force: bool = False) -> bool:
        if force:
            return False
        return (time.time() - self._last_sync) < self._cache_ttl

    def mark_synced(self):
        self._last_sync = time.time()

    def invalidate(self):
        self._last_sync = 0.0

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock
