"""Per-username login throttling (F-M17, IMPLEMENTATION_PLAN P-4).

After ``LOGIN_MAX_FAILURES`` failed logins within ``LOGIN_LOCKOUT_SECONDS``, further
attempts for that username get HTTP 429 until the window expires. The counter is per
username (not per IP): the warehouse shares one network, so an IP rule could lock every
operator out at once. If Redis is unavailable, logins are allowed (fail open) and a warning
is logged, so a cache outage never locks everyone out.
"""

import logging

from ...config import get_config_int
from ..redis_service import redis_mgr

logger = logging.getLogger("backend.services.managers.login_throttle")

LOGIN_MAX_FAILURES = get_config_int("LOGIN_MAX_FAILURES", 10)
LOGIN_LOCKOUT_SECONDS = get_config_int("LOGIN_LOCKOUT_SECONDS", 900)


class LoginThrottle:
    def __init__(self, max_failures: int = LOGIN_MAX_FAILURES, window: int = LOGIN_LOCKOUT_SECONDS):
        self.max_failures = max_failures
        self.window = window

    @staticmethod
    def _key(username: str) -> str:
        return f"login_fail:{username.strip().lower()}"

    async def is_locked(self, username: str) -> bool:
        try:
            value = await redis_mgr.get(self._key(username))
        except Exception:
            logger.warning(
                "login_throttle_unavailable", extra={"event": "auth.throttle.unavailable"}
            )
            return False
        return value is not None and int(value) >= self.max_failures

    async def record_failure(self, username: str) -> None:
        try:
            count = await redis_mgr.incr_with_ttl(self._key(username), self.window)
            if count == self.max_failures:
                # Lock for a full window from the failure that triggered it.
                await redis_mgr.expire(self._key(username), self.window)
                logger.warning(
                    "login_locked",
                    extra={"event": "auth.login.locked", "username": username},
                )
        except Exception:
            logger.warning(
                "login_throttle_unavailable", extra={"event": "auth.throttle.unavailable"}
            )

    async def reset(self, username: str) -> None:
        try:
            await redis_mgr.delete(self._key(username))
        except Exception:
            logger.warning(
                "login_throttle_unavailable", extra={"event": "auth.throttle.unavailable"}
            )


login_throttle = LoginThrottle()
