from .key_manager import KeyManager, ACCESS_TTL_SECONDS
from .ticket_manager import TicketManager
from .connection_manager import ConnectionManager
from .shopee_token_manager import ShopeeTokenManager
from .shopee_cache_manager import ShopeeOrderCacheManager
from ..redis_service import redis_mgr

ticket_mgr = TicketManager()
conn_mgr = ConnectionManager()
token_mgr = ShopeeTokenManager(redis_mgr)
cache_mgr = ShopeeOrderCacheManager()
key_mgr = KeyManager()

__all__ = [
    "ticket_mgr",
    "conn_mgr",
    "token_mgr",
    "cache_mgr",
    "key_mgr",
    "redis_mgr",
    "ACCESS_TTL_SECONDS",
]
