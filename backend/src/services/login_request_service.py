"""Ask an admin to approve a login (V2_LOGIN_REQUEST_DELTA, IMPLEMENTATION_PLAN T6.21).

A registered device asks for a worker, an admin approves, and the device that asked (proved by
its key on every call) collects one session. Unknown usernames and admin accounts get a request
that looks the same to the device but that no admin sees, so names stay hidden (F-M17).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from redis.exceptions import RedisError

from ..exceptions import DomainException
from ..models import (
    AdminLoginRequest,
    LoginRequestCreate,
    LoginRequestCreated,
    LoginRequestPoll,
    LoginRequestProof,
    User,
    WSMessageType,
)
from . import auth_service, queries
from .device_service import verify_signature
from .managers import conn_mgr
from .managers import login_request_manager as store
from .managers.login_request_manager import LoginRequest, TooManyRequests, login_request_mgr

logger = logging.getLogger("backend.services.login_request_service")

# A captured create call must not work again later; polls and cancels die with their request.
CREATE_NONCE_SECONDS = 30 * 24 * 3600


@contextmanager
def _redis_required():
    try:
        yield
    except (RedisError, OSError) as exc:
        logger.warning(
            "login_request_store_unavailable",
            extra={"event": "auth.login_request.unavailable"},
        )
        raise DomainException(status_code=503, detail="Login requests are unavailable") from exc


def _log(event: str, request: LoginRequest, **extra: Any) -> None:
    logger.info(
        f"login_request_{event}",
        extra={
            "event": f"auth.login_request.{event}",
            "request_id": request.id,
            "username": request.username,
            "device_id": request.device_id,
            **extra,
        },
    )


def _credential(user: User | None) -> str:
    return hashlib.sha256((user.password_hash or "").encode()).hexdigest() if user else ""


def _message(action: str, subject: str, nonce: str) -> str:
    return f"oc-login-request:{action}:{subject}:{nonce}"


async def _verify(
    public_key: str, action: str, subject: str, proof: LoginRequestProof, ttl: int
) -> None:
    await asyncio.to_thread(
        verify_signature, public_key, proof.signature, _message(action, subject, proof.nonce)
    )
    scope = f"{action}:{hashlib.sha256(public_key.encode()).hexdigest()[:32]}"
    if not await login_request_mgr.claim_nonce(scope, proof.nonce, ttl):
        raise DomainException(status_code=400, detail="Nonce already used")


async def create(body: LoginRequestCreate, ip_address: str | None) -> LoginRequestCreated:
    with _redis_required():
        await _verify(body.public_key, "create", body.username, body, CREATE_NONCE_SECONDS)
        device = await asyncio.to_thread(queries.get_device_by_public_key, body.public_key)
        if device is None:
            raise DomainException(status_code=403, detail="Device not registered")
        if device.status == "revoked":
            raise DomainException(status_code=403, detail="Device revoked")
        user = await asyncio.to_thread(queries.get_user_data, body.username)
        try:
            request = await login_request_mgr.create(
                username=body.username,
                real=user is not None and user.scope == "client",
                credential=_credential(user),
                device_id=device.id,
                device_name=device.label or device.model or device.id[:8],
                public_key=body.public_key,
                ip_address=ip_address,
            )
        except TooManyRequests:
            raise DomainException(status_code=429, detail="Too many login requests. Try later.")
        _log("created", request, visible=request.real)
        await _announce()
    return LoginRequestCreated(
        id=request.id, match_code=request.match_code, expires_in=store.TTL_SECONDS
    )


async def poll(request_id: str, proof: LoginRequestProof) -> LoginRequestPoll:
    with _redis_required():
        request = await login_request_mgr.get(request_id)
        if request is None:
            return LoginRequestPoll(status="expired")
        await _verify(request.public_key, "poll", request_id, proof, store.RATE_WINDOW_SECONDS)
        decision = await login_request_mgr.decision(request_id)
        if decision is None:
            return LoginRequestPoll(status="pending")
        if decision == "denied":
            await login_request_mgr.drop(request_id)
            return LoginRequestPoll(status="denied")
        user = await asyncio.to_thread(queries.get_user_data, request.username)
        if user is None or user.scope != "client" or _credential(user) != request.credential:
            await login_request_mgr.drop(request_id)
            return LoginRequestPoll(status="expired")
        if not await login_request_mgr.collect(request_id):
            return LoginRequestPoll(status="expired")
    tokens = await asyncio.to_thread(_start_session, user, request)
    if tokens is None:
        return LoginRequestPoll(status="denied")
    _log("collected", request)
    return LoginRequestPoll(status="approved", tokens=tokens)


def _start_session(user: User, request: LoginRequest) -> dict | None:
    sid = auth_service.new_session_id()
    tokens = auth_service.get_tokens(
        user, ip_address=request.ip_address, agent="login-request", new_sid=sid
    )
    if queries.bind_session_to_device(sid, request.device_id, user.username or ""):
        return tokens
    queries.revoke_session(sid)  # the device was revoked while the request was open
    return None


async def cancel(request_id: str, proof: LoginRequestProof) -> None:
    with _redis_required():
        request = await login_request_mgr.get(request_id)
        if request is None:
            return
        await _verify(request.public_key, "cancel", request_id, proof, store.RATE_WINDOW_SECONDS)
        await login_request_mgr.drop(request_id)
        _log("cancelled", request)
        await _announce()


async def pending() -> list[AdminLoginRequest]:
    with _redis_required():
        return [_for_admin(r) for r in await login_request_mgr.pending()]


async def decide(request_id: str, decision: str, admin: str) -> None:
    with _redis_required():
        request = await login_request_mgr.get(request_id)
        if request is None or not request.real:
            raise DomainException(status_code=404, detail="Login request not found")
        try:
            won = await login_request_mgr.decide(request_id, decision, admin)
        except LookupError:
            raise DomainException(status_code=404, detail="Login request not found")
        if not won:
            raise DomainException(status_code=409, detail="Login request already decided")
        _log(decision, request, admin=admin)
        await _announce()


def _for_admin(r: LoginRequest) -> AdminLoginRequest:
    return AdminLoginRequest(
        id=r.id,
        username=r.username,
        match_code=r.match_code,
        device_id=r.device_id,
        device_name=r.device_name,
        ip_address=r.ip_address,
        created_at=datetime.fromtimestamp(r.created_at, UTC),
        expires_at=datetime.fromtimestamp(r.expires_at, UTC),
    )


async def _announce() -> None:
    data = [jsonable_encoder(_for_admin(r)) for r in await login_request_mgr.pending()]
    await conn_mgr.broadcast(WSMessageType.LOGIN_REQUESTS, scope="admin", data=data)
