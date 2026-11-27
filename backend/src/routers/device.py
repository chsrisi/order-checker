"""v2 device registration (IMPLEMENTATION_PLAN T6.6). Not gated by ``X-Client-Version``: the
body reports the app version, and an outdated app must still be identifiable."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..models import DeviceRegisterRequest, DeviceResponse
from ..services import device_service
from ..services.auth_service import Principal, get_current_principal

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
