"""Login requests of the v2 app (V2_LOGIN_REQUEST_DELTA, IMPLEMENTATION_PLAN T6.22). No user
token: the device proves itself with its registered key on every call."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from ...models import (
    LoginRequestCreate,
    LoginRequestCreated,
    LoginRequestPoll,
    LoginRequestProof,
    MessageResponse,
)
from ...services import login_request_service
from . import GATE_RESPONSES, require_client_version

router = APIRouter(
    prefix="/v2/auth/login-requests",
    tags=["v2 · authentication"],
    dependencies=[Depends(require_client_version)],
)

RequestId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
RESPONSES = {
    **GATE_RESPONSES,
    400: {"description": "X-Client-Version missing, bad signature or key, or nonce reused"},
    503: {"description": "Redis unavailable"},
}


@router.post(
    "",
    response_model=LoginRequestCreated,
    summary="Ask an admin to approve a login",
    description=(
        "From a registered, not revoked device. Replaces the device's previous request. The "
        "answer does not tell whether the account exists."
    ),
    responses={
        **RESPONSES,
        403: {"description": "Device not registered, or revoked"},
        429: {"description": "Too many requests from this device, or too many pending"},
    },
)
async def create_login_request(body: LoginRequestCreate, request: Request):
    return await login_request_service.create(body, request.client.host if request.client else None)


@router.post(
    "/{request_id}/poll",
    response_model=LoginRequestPoll,
    summary="Check a login request",
    description="Returns the tokens once when approved. Poll every 2 s.",
    responses=RESPONSES,
)
async def poll_login_request(request_id: RequestId, body: LoginRequestProof):
    return await login_request_service.poll(request_id, body)


@router.post(
    "/{request_id}/cancel",
    response_model=MessageResponse,
    summary="Cancel a login request",
    description="Idempotent: an ended request answers the same.",
    responses=RESPONSES,
)
async def cancel_login_request(request_id: RequestId, body: LoginRequestProof):
    await login_request_service.cancel(request_id, body)
    return {"message": "Login request cancelled"}
