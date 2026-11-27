"""Per-device logout and worker switch (V2_WORKER_SWITCH_SPEC §4.1–4.3, IMPLEMENTATION_PLAN T8.4a).

An admin logs one device out, or switches its worker: the device's sessions end at once, and an
assignment waits in Redis for the device. The device's login screen polls
``POST /v2/device/state``, signed with its registered key, and collects the assignment once: in
``direct`` mode with a session for the worker bound to the device, in ``preselect`` mode as the
worker to select. Each step is logged with the admin, the device, and the old and new worker
(no audit table, R1.2).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from redis.exceptions import RedisError

from ..exceptions import DomainException
from ..models import (
    AdminDeviceAssign,
    AdminDeviceAssignment,
    AdminDeviceLastAssignment,
    AdminDeviceResponse,
    AdminDeviceUpdate,
    Device,
    DeviceLogoutReason,
    DeviceStateAssignment,
    DeviceStateRequest,
    DeviceStateResponse,
    WSMessageType,
)
from . import queries
from .device_service import start_bound_session, verify_signature
from .login_request_service import credential
from .managers import conn_mgr
from .managers import device_assignment_manager as store
from .managers.device_assignment_manager import Assignment, device_assignment_mgr as mgr

logger = logging.getLogger("backend.services.device_assignment_service")

REDIS_ERRORS = (RedisError, OSError, RuntimeError)
LAST_SEEN_INTERVAL = timedelta(seconds=60)  # P-27, as P-16
SWEEP_INTERVAL_SECONDS = 5


@contextmanager
def _redis_required():
    try:
        yield
    except REDIS_ERRORS as exc:
        logger.warning(
            "device_assignment_store_unavailable",
            extra={"event": "device.assignment.unavailable"},
        )
        raise DomainException(status_code=503, detail="Device assignments are unavailable") from exc


def _log(event: str, device_id: str, **extra: Any) -> None:
    logger.info(
        f"device_{event.replace('.', '_')}",
        extra={"event": f"device.{event}", "device_id": device_id, **extra},
    )


def _log_assignment(event: str, a: Assignment, **extra: Any) -> None:
    _log(
        f"assignment.{event}",
        a.device_id,
        admin=a.admin,
        new_worker=a.username,
        mode=a.mode,
        assignment_id=a.id,
        **extra,
    )


# --- admin view ------------------------------------------------------------------------------


async def _view(device: Device, online: set[str]) -> AdminDeviceResponse:
    extra: dict[str, Any] = {"online": device.id in online}
    try:
        assignment = await mgr.get(device.id)
        last = await mgr.get_last(device.id)
        extra["reachable"] = await mgr.seen(device.id)
    except REDIS_ERRORS:  # the listing works without Redis, just without these fields
        return AdminDeviceResponse.model_validate(device).model_copy(update=extra)
    if assignment is not None:
        extra["assignment"] = AdminDeviceAssignment(
            username=assignment.username,
            mode=assignment.mode,  # type: ignore[arg-type]
            admin=assignment.admin,
            created_at=datetime.fromtimestamp(assignment.created_at, UTC),
            expires_at=datetime.fromtimestamp(assignment.expires_at, UTC),
        )
    if last is not None:
        extra["last_assignment"] = AdminDeviceLastAssignment(
            **{**last, "at": datetime.fromtimestamp(last["at"], UTC)}
        )
    return AdminDeviceResponse.model_validate(device).model_copy(update=extra)


async def _online() -> set[str]:
    return await asyncio.to_thread(queries.device_ids_for_sessions, conn_mgr.live_session_ids())


async def admin_devices() -> list[AdminDeviceResponse]:
    devices = await asyncio.to_thread(queries.list_devices)
    online = await _online()
    return [await _view(d, online) for d in devices]


async def admin_device(device_id: str) -> AdminDeviceResponse:
    return await _view(await _device(device_id), await _online())


async def announce() -> None:
    """``devices_update`` to admins: the whole device list, as ``GET /admin/devices``."""
    try:
        data = jsonable_encoder(await admin_devices())
        await conn_mgr.broadcast(WSMessageType.DEVICES, scope="admin", data=data)
    except Exception:  # never fail the action that changed the device
        logger.exception("devices_update_failed")


# --- admin actions ---------------------------------------------------------------------------


async def _device(device_id: str) -> Device:
    device = await asyncio.to_thread(queries.get_device, device_id)
    if device is None:
        raise DomainException(status_code=404, detail="Device not found")
    return device


async def _end_sessions(device_id: str) -> list[str]:
    sids = await asyncio.to_thread(queries.revoke_device_sessions, device_id)
    for sid in sids:
        await conn_mgr.disconnect_session(sid)
    return sids


async def rename(device_id: str, body: AdminDeviceUpdate, admin: str) -> AdminDeviceResponse:
    """Set the device's console name (T8.6, V2_UX §2.8 open point 2)."""
    device = await asyncio.to_thread(queries.set_device_label, device_id, body.label)
    if device is None:
        raise DomainException(status_code=404, detail="Device not found")
    _log("renamed", device_id, admin=admin, label=body.label)
    await announce()
    return await admin_device(device_id)


async def logout(device_id: str, admin: str) -> int:
    """"Log out this device": end its sessions and drop a waiting assignment. Works without
    Redis (the logout reason and the assignment are then left alone)."""
    device = await _device(device_id)
    if device.status == "revoked":
        raise DomainException(status_code=409, detail="Device is revoked")
    sids = await _end_sessions(device_id)
    try:
        dropped = await mgr.take(device_id)
        if dropped is not None:
            await mgr.set_last(dropped, "cancelled")
            _log_assignment("cancelled", dropped, by=admin)
        if sids:
            await mgr.set_logout_reason(device_id, "logout", admin, None)
    except REDIS_ERRORS:
        logger.warning("device_logout_without_redis", extra={"event": "device.logout.no_redis"})
    _log("logout", device_id, admin=admin, old_worker=device.current_username, sessions_revoked=len(sids))
    await announce()
    return len(sids)


async def assign(device_id: str, body: AdminDeviceAssign, admin: str) -> AdminDeviceResponse:
    """Switch the device's worker: store the assignment, then end the device's sessions. A new
    assignment replaces the device's previous one (last admin wins)."""
    device = await _device(device_id)
    if device.status == "revoked":
        raise DomainException(status_code=409, detail="Device is revoked")
    if body.mode == "direct" and device.status != "active":
        # W2: whoever holds the scanner acts as that worker, so only an approved scanner.
        raise DomainException(status_code=409, detail="Device is not approved")
    user = await asyncio.to_thread(queries.get_user_data, body.username)
    if user is None or user.scope != "client":
        raise DomainException(status_code=404, detail="Client account not found")
    with _redis_required():  # before ending sessions: no logout without the assignment
        assignment, old = await mgr.put(
            device_id=device_id,
            username=body.username,
            mode=body.mode,
            admin=admin,
            credential=credential(user),
        )
        if old is not None:
            await mgr.set_last(old, "replaced")
            _log_assignment("replaced", old, by=admin)
    sids = await _end_sessions(device_id)
    if sids:
        try:
            await mgr.set_logout_reason(device_id, "switch", admin, body.username)
        except REDIS_ERRORS:
            logger.warning("device_logout_reason_lost", extra={"event": "device.logout.no_redis"})
    _log_assignment(
        "created", assignment, old_worker=device.current_username, sessions_revoked=len(sids)
    )
    await announce()
    return await admin_device(device_id)


async def cancel(device_id: str, admin: str) -> AdminDeviceResponse:
    """Drop a waiting assignment; idempotent. The device stays logged out."""
    await _device(device_id)
    with _redis_required():
        dropped = await mgr.take(device_id)
        if dropped is not None:
            await mgr.set_last(dropped, "cancelled")
    if dropped is not None:
        _log_assignment("cancelled", dropped, by=admin)
        await announce()
    return await admin_device(device_id)


async def drop_for_revoked(device_id: str, admin: str) -> None:
    """After a revoke (T8.1): a waiting assignment can never be collected. Best effort."""
    try:
        dropped = await mgr.take(device_id)
        if dropped is not None:
            await mgr.set_last(dropped, "invalid")
            _log_assignment("invalid", dropped, by=admin, reason="device_revoked")
    except REDIS_ERRORS:
        pass  # it can't be collected anyway: the state poll refuses a revoked device
    await announce()


async def expire_due() -> int:
    """Record and announce assignments that expired without being collected."""
    expired = await mgr.due()
    for a in expired:
        await mgr.set_last(a, "expired")
        _log_assignment("expired", a)
    if expired:
        await announce()
    return len(expired)


async def assignment_expiry_task() -> None:
    try:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            try:
                await expire_due()
            except REDIS_ERRORS:
                logger.debug("device assignment sweep skipped: Redis unavailable")
    except asyncio.CancelledError:
        logger.info("Device assignment expiry task cancelled")
        raise


# --- the device's poll -----------------------------------------------------------------------


def _message(device_id: str, nonce: str) -> str:
    return f"oc-device:state:{device_id}:{nonce}"


async def state(body: DeviceStateRequest, ip_address: str | None) -> DeviceStateResponse:
    with _redis_required():
        device = await asyncio.to_thread(queries.get_device, body.device_id)
        if device is None:
            raise DomainException(status_code=403, detail="Device not registered")
        await asyncio.to_thread(
            verify_signature,
            device.public_key,
            body.signature,
            _message(body.device_id, body.nonce),
        )
        if abs(time.time() - int(body.nonce.split("-", 1)[0])) > store.NONCE_WINDOW_SECONDS:
            raise DomainException(status_code=400, detail="Nonce out of time")
        if not await mgr.claim_nonce(device.id, body.nonce):
            raise DomainException(status_code=400, detail="Nonce already used")
        if device.status == "revoked":
            raise DomainException(status_code=403, detail="Device revoked")
        if not await mgr.claim_poll_slot(device.id):
            raise DomainException(status_code=429, detail="Polling too fast")
        await mgr.mark_seen(device.id)
        await asyncio.to_thread(queries.touch_device, device.id, LAST_SEEN_INTERVAL)
        reason = await mgr.take_logout_reason(device.id)
        assignment = await mgr.take(device.id)
    return DeviceStateResponse(
        assignment=await _hand_over(device, assignment, ip_address) if assignment else None,
        logout_reason=(
            DeviceLogoutReason(kind=reason["kind"], username=reason.get("username"))
            if reason
            else None
        ),
    )


async def _hand_over(
    device: Device, a: Assignment, ip_address: str | None
) -> DeviceStateAssignment | None:
    """The assignment was taken (once); check it still holds, then hand it over."""
    user = await asyncio.to_thread(queries.get_user_data, a.username)
    reason = None
    if user is None or user.scope != "client" or credential(user) != a.credential:
        reason = "worker_changed"  # deleted, password reset, or made an admin meanwhile
    elif a.mode == "direct" and device.status != "active":
        reason = "device_not_approved"
    tokens = None
    if reason is None and a.mode == "direct":
        tokens = await asyncio.to_thread(
            start_bound_session, user, device.id, ip_address, "device-assignment"
        )
        if tokens is None:
            reason = "device_revoked"
    if reason is not None:
        await _record(a, "invalid", reason=reason)
        return None
    await _record(a, "collected", old_worker=device.current_username)
    return DeviceStateAssignment(username=a.username, mode=a.mode, tokens=tokens)  # type: ignore[arg-type]


async def _record(a: Assignment, outcome: str, **extra: Any) -> None:
    try:
        await mgr.set_last(a, outcome)
    except REDIS_ERRORS:
        pass
    _log_assignment(outcome, a, **extra)
    await announce()
