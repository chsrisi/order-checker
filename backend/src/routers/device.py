"""v2 device registration (IMPLEMENTATION_PLAN T6.6). Not gated by ``X-Client-Version``: the
body reports the app version, and an outdated app must still be identifiable."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..models import DeviceRegisterRequest, DeviceResponse, DeviceStateRequest, DeviceStateResponse
from ..services import device_assignment_service, device_service
from ..services.auth_service import Principal, get_current_principal
from .v2 import GATE_RESPONSES, require_client_version

router = APIRouter(prefix="/v2/device", tags=["v2 · device"])


@router.post(
    "/register",
    response_model=DeviceResponse,
    summary="Register this device",
    description=(
        "Operator access token required. Registers the device by its Keystore public key "
        "(new devices are `pending`) and binds the caller's session to it. Idempotent: call "
        "it after every login. `signature` signs the token's `sid` claim."
    ),
    responses={
        400: {"description": "Invalid public key or signature"},
        401: {"description": "Invalid bearer token"},
        403: {"description": "Device revoked (the calling session is revoked too)"},
    },
)
async def register_device(
    body: DeviceRegisterRequest,
    principal: Principal = Depends(get_current_principal),
):
    return await device_service.register(body, principal.user.username or "", principal.sid)


@router.post(
    "/state",
    response_model=DeviceStateResponse,
    summary="Poll this device's state",
    description=(
        "No user token: signed with the registered device key (T8.4a). The login screen calls "
        "it every 5 s while in the foreground, at most once per 2 s. Returns a worker switch by "
        "the admin once (`direct`: with the new session's tokens, bound to this device), and "
        "why the device was last logged out by the admin, once."
    ),
    dependencies=[Depends(require_client_version)],
    responses={
        **GATE_RESPONSES,
        400: {
            "description": (
                "X-Client-Version missing, bad signature, nonce reused or more than 5 minutes "
                "off the server's time"
            )
        },
        403: {"description": "Device not registered, or revoked"},
        429: {"description": "Polling faster than once per 2 s"},
        503: {"description": "Redis unavailable"},
    },
)
async def device_state(body: DeviceStateRequest, request: Request):
    return await device_assignment_service.state(
        body, request.client.host if request.client else None
    )
