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
        # Track if the refresh token is fundamentally broken
        self._token_fatal_error = False

    def is_valid(self, force: bool = False) -> bool:
        if force:
            return False
        return (time.time() - self._last_sync) < self._cache_ttl

    def mark_synced(self):
        self._last_sync = time.time()
        # Reset the error if a sync ever miraculously succeeds
        self._token_fatal_error = False

    def invalidate(self):
        self._last_sync = 0.0

    def set_token_fatal(self, value: bool = True):
        self._token_fatal_error = value

    def is_token_fatal(self) -> bool:
        return self._token_fatal_error

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock
