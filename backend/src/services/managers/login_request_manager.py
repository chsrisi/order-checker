"""Pending login requests in Redis (V2_LOGIN_REQUEST_DELTA L2, IMPLEMENTATION_PLAN T6.21).

Keys (all expire by themselves):

* ``login_req:<id>``           the request (JSON). It existing means "not collected, cancelled,
                               replaced or expired".
* ``login_req_decision:<id>``  ``approved:<admin>`` or ``denied:<admin>``, set with NX.
* ``login_req_device:<dev>``   the device's current request id.
* ``login_req_rate:<dev>``     requests made in the rate window.
* ``login_req_nonce:<scope>:<nonce>``  nonces seen.
* ``login_req_index``          sorted set of open request ids by expiry.

Each transition is one atomic command: NX decides, GETDEL collects, DEL cancels. So two admins,
two polls, or a cancel racing an approval can produce at most one session.
Redis errors propagate; the service answers 503 (L8, fail closed).
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Optional

from ...config import get_config_int
from ..redis_service import redis_mgr

TTL_SECONDS = get_config_int("LOGIN_REQUEST_TTL_SECONDS", 120)
COLLECT_SECONDS = get_config_int("LOGIN_REQUEST_COLLECT_SECONDS", 30)
MAX_PER_DEVICE = get_config_int("LOGIN_REQUEST_MAX_PER_DEVICE", 5)
RATE_WINDOW_SECONDS = get_config_int("LOGIN_REQUEST_RATE_WINDOW_SECONDS", 600)
MAX_PENDING = get_config_int("LOGIN_REQUEST_MAX_PENDING", 20)

INDEX = "login_req_index"


class TooManyRequests(Exception):
    pass


@dataclass(frozen=True)
class LoginRequest:
    id: str
    username: str
    # False for unknown and admin accounts: looks alike to the device, invisible to admins.
    real: bool
    # Changes with the password (and when the account is recreated).
    credential: str
    device_id: str
    device_name: str
    public_key: str
    match_code: str
    ip_address: Optional[str]
    created_at: float
    expires_at: float


class LoginRequestManager:
    async def claim_nonce(self, scope: str, nonce: str, ttl: int) -> bool:
        """False when this nonce was used before."""
        return bool(await redis_mgr.set_nx(f"login_req_nonce:{scope}:{nonce}", "1", ex=ttl))

    async def create(
        self,
        *,
        username: str,
        real: bool,
        credential: str,
        device_id: str,
        device_name: str,
        public_key: str,
        ip_address: Optional[str],
    ) -> LoginRequest:
        rate = await redis_mgr.incr_with_ttl(f"login_req_rate:{device_id}", RATE_WINDOW_SECONDS)
        if rate > MAX_PER_DEVICE:
            raise TooManyRequests()
        now = time.time()
        request = LoginRequest(
            id=secrets.token_hex(16),
            username=username,
            real=real,
            credential=credential,
            device_id=device_id,
            device_name=device_name,
            public_key=public_key,
            match_code=f"{secrets.randbelow(100):02d}",
            ip_address=ip_address,
            created_at=now,
            expires_at=now + TTL_SECONDS,
        )
        old = await redis_mgr.getset(f"login_req_device:{device_id}", request.id, ex=TTL_SECONDS)
        if old:
            await self.drop(old)
        await redis_mgr.zadd(INDEX, request.id, request.expires_at)
        await redis_mgr.zremrangebyscore(INDEX, 0, now)
        if await redis_mgr.zcard(INDEX) > MAX_PENDING:
            await redis_mgr.zrem(INDEX, request.id)
            raise TooManyRequests()
        await redis_mgr.set(f"login_req:{request.id}", json.dumps(asdict(request)), ex=TTL_SECONDS)
        return request

    async def get(self, request_id: str) -> Optional[LoginRequest]:
        raw = await redis_mgr.get(f"login_req:{request_id}")
        return LoginRequest(**json.loads(raw)) if raw else None

    async def decision(self, request_id: str) -> Optional[str]:
        """``approved``, ``denied`` or None."""
        value = await redis_mgr.get(f"login_req_decision:{request_id}")
        return value.split(":", 1)[0] if value else None

    async def decide(self, request_id: str, decision: str, admin: str) -> bool:
        """False when someone else decided first. Raises LookupError when the request ended
        meanwhile. An approved request stays collectable for COLLECT_SECONDS."""
        won = await redis_mgr.set_nx(
            f"login_req_decision:{request_id}",
            f"{decision}:{admin}",
            ex=TTL_SECONDS + COLLECT_SECONDS,
        )
        if not won:
            return False
        await redis_mgr.zrem(INDEX, request_id)
        if not await redis_mgr.expire(f"login_req:{request_id}", COLLECT_SECONDS):
            raise LookupError(request_id)
        return True

    async def collect(self, request_id: str) -> bool:
        """True for exactly one caller."""
        return await redis_mgr.getdel(f"login_req:{request_id}") is not None

    async def drop(self, request_id: str) -> None:
        await redis_mgr.delete(f"login_req:{request_id}")
        await redis_mgr.zrem(INDEX, request_id)

    async def pending(self) -> list[LoginRequest]:
        """Undecided requests for real accounts, oldest first."""
        await redis_mgr.zremrangebyscore(INDEX, 0, time.time())
        requests = [await self.get(i) for i in await redis_mgr.zrange(INDEX)]
        return [r for r in requests if r is not None and r.real]


login_request_mgr = LoginRequestManager()
