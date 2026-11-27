"""Device assignments and device state in Redis (V2_WORKER_SWITCH_DELTA W4, W8; IMPLEMENTATION_PLAN
T8.4a, P-23, P-25, P-27).

Keys (all expire by themselves):

* ``device_assign:<dev>``          the device's assignment (JSON), one per device. It existing
                                   means "not collected, cancelled, replaced or expired".
* ``device_assign_index``          sorted set of the assignments' JSON by expiry, so the sweeper
                                   still knows an assignment whose key has expired.
* ``device_assign_last:<dev>``     what happened to the last assignment (JSON, for the console).
* ``device_logout_reason:<dev>``   why the device was last logged out (JSON), read once.
* ``device_state_rate:<dev>``      set for ``POLL_MIN_INTERVAL_SECONDS`` by a poll.
* ``device_state_nonce:<dev>:<nonce>``  nonces seen.
* ``device_seen:<dev>``            set for ``REACHABLE_SECONDS`` by a poll (P-27).

Collecting is one GETDEL, so two polls racing produce at most one session. Replacing is one SET
with GET. Redis errors propagate; the service answers 503 (fail closed).
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Optional

from ...config import get_config_int
from ..redis_service import redis_mgr

TTL_SECONDS = get_config_int("DEVICE_ASSIGNMENT_TTL_SECONDS", 600)
POLL_MIN_INTERVAL_SECONDS = 2
REACHABLE_SECONDS = 30
LOGOUT_REASON_SECONDS = 24 * 3600
LAST_OUTCOME_SECONDS = 3600
# The poll nonce starts with the device's Unix time; older or newer polls are refused, so a
# captured poll can't be replayed once its nonce has been forgotten.
NONCE_WINDOW_SECONDS = 300

INDEX = "device_assign_index"


@dataclass(frozen=True)
class Assignment:
    id: str
    device_id: str
    username: str
    mode: str  # "direct" | "preselect"
    admin: str
    # Changes with the password (and when the account is recreated); see login requests.
    credential: str
    created_at: float
    expires_at: float


class DeviceAssignmentManager:
    async def put(
        self, *, device_id: str, username: str, mode: str, admin: str, credential: str
    ) -> tuple[Assignment, Optional[Assignment]]:
        """Store a new assignment; returns it and the one it replaced, if any."""
        now = time.time()
        assignment = Assignment(
            id=secrets.token_hex(16),
            device_id=device_id,
            username=username,
            mode=mode,
            admin=admin,
            credential=credential,
            created_at=now,
            expires_at=now + TTL_SECONDS,
        )
        value = json.dumps(asdict(assignment))
        await redis_mgr.zadd(INDEX, value, assignment.expires_at)
        raw = await redis_mgr.getset(f"device_assign:{device_id}", value, ex=TTL_SECONDS)
        if not raw:
            return assignment, None
        await redis_mgr.zrem(INDEX, raw)
        return assignment, Assignment(**json.loads(raw))

    async def get(self, device_id: str) -> Optional[Assignment]:
        raw = await redis_mgr.get(f"device_assign:{device_id}")
        return Assignment(**json.loads(raw)) if raw else None

    async def take(self, device_id: str) -> Optional[Assignment]:
        """The assignment, for exactly one caller (collect, cancel)."""
        raw = await redis_mgr.getdel(f"device_assign:{device_id}")
        if not raw:
            return None
        await redis_mgr.zrem(INDEX, raw)
        return Assignment(**json.loads(raw))

    async def due(self) -> list[Assignment]:
        """Assignments past their expiry and not collected, cancelled or replaced, each
        returned to one caller only (ZREM decides)."""
        result = []
        for member in await redis_mgr.zrangebyscore(INDEX, 0, time.time()):
            if await redis_mgr.zrem(INDEX, member):
                result.append(Assignment(**json.loads(member)))
        return result

    async def set_last(self, assignment: Assignment, outcome: str) -> None:
        value = {
            "username": assignment.username,
            "mode": assignment.mode,
            "admin": assignment.admin,
            "outcome": outcome,
            "at": time.time(),
        }
        await redis_mgr.set(
            f"device_assign_last:{assignment.device_id}", json.dumps(value), ex=LAST_OUTCOME_SECONDS
        )

    async def get_last(self, device_id: str) -> Optional[dict]:
        raw = await redis_mgr.get(f"device_assign_last:{device_id}")
        return json.loads(raw) if raw else None

    async def set_logout_reason(self, device_id: str, kind: str, admin: str, username: str | None):
        value = {"kind": kind, "admin": admin, "username": username}
        await redis_mgr.set(
            f"device_logout_reason:{device_id}", json.dumps(value), ex=LOGOUT_REASON_SECONDS
        )

    async def take_logout_reason(self, device_id: str) -> Optional[dict]:
        raw = await redis_mgr.getdel(f"device_logout_reason:{device_id}")
        return json.loads(raw) if raw else None

    async def claim_nonce(self, device_id: str, nonce: str) -> bool:
        """False when this nonce was used before."""
        return bool(
            await redis_mgr.set_nx(
                f"device_state_nonce:{device_id}:{nonce}", "1", ex=2 * NONCE_WINDOW_SECONDS
            )
        )

    async def claim_poll_slot(self, device_id: str) -> bool:
        """False when the device polled less than ``POLL_MIN_INTERVAL_SECONDS`` ago (P-25)."""
        return bool(
            await redis_mgr.set_nx(
                f"device_state_rate:{device_id}", "1", ex=POLL_MIN_INTERVAL_SECONDS
            )
        )

    async def mark_seen(self, device_id: str) -> None:
        await redis_mgr.set(f"device_seen:{device_id}", "1", ex=REACHABLE_SECONDS)

    async def seen(self, device_id: str) -> bool:
        return await redis_mgr.exists(f"device_seen:{device_id}")


device_assignment_mgr = DeviceAssignmentManager()
