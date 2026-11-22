import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..models import (
    MessageResponse,
    RefreshTokenRequest,
    Token,
    UserAuth,
    WebSocketTicketResponse,
)
from ..services import auth_service
from ..services.auth_service import Principal, get_current_principal
from ..services.managers import ticket_mgr, key_mgr

logger = logging.getLogger("backend.routers.auth")

router = APIRouter(prefix="/auth", tags=["authentication"])
public_router = APIRouter(tags=["authentication"])


def _client_info(request: Request) -> dict:
    """Recorded on the session at login (``auth.sessions.ip_address/agent``)."""
    return {
        "ip_address": request.client.host if request.client else None,
        "agent": request.headers.get("user-agent"),
    }


@router.post(
    "/register",
    response_model=Token,
    summary="Register an operator account",
    description=(
        "Creates a client-scoped account and returns a new access/refresh token pair. "
        "Disabled (403) unless ALLOW_REGISTRATION is on; production creates operator "
        "accounts through POST /admin/users."
    ),
    responses={
        400: {"description": "Username already exists"},
        403: {"description": "Registration is disabled"},
    },
)
async def register_client(auth: UserAuth):
    return await auth_service.register_client(auth.username, auth.password)


@router.post(
    "/login",
    response_model=Token,
    summary="Log in an operator",
    description="Authenticates any existing account for the operator application.",
    responses={
        401: {"description": "Invalid credentials"},
        429: {"description": "Too many failed attempts for this username; retry later"},
    },
)
async def login_client(auth: UserAuth, request: Request):
    return await auth_service.login_throttled(
        auth.username, auth.password, **_client_info(request)
    )


@router.post(
    "/admin",
    response_model=Token,
    summary="Log in an administrator",
    description="Authenticates credentials only when the account has the admin scope.",
    responses={
        401: {"description": "Invalid credentials or non-admin account"},
        429: {"description": "Too many failed attempts for this username; retry later"},
    },
)
async def login_admin(auth: UserAuth, request: Request):
    return await auth_service.login_throttled(
        auth.username, auth.password, required_scope="admin", **_client_info(request)
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Log out",
    description=(
        "Ends the refresh token's session: its access and refresh tokens stop working at once "
        "and its WebSocket connections are closed."
    ),
    responses={400: {"description": "Malformed refresh token"}},
)
async def logout(body: RefreshTokenRequest):
    return await auth_service.logout_user(body.refresh_token)


@router.post(
    "/ws-token",
    response_model=WebSocketTicketResponse,
    summary="Create a WebSocket ticket",
    description="Returns a one-use ticket that expires after configured TTL.",
    responses={
        401: {"description": "Invalid bearer token"},
        503: {"description": "Redis unavailable"},
    },
)
async def create_ws_token(
    principal: Principal = Depends(get_current_principal),
):
    ttl = ticket_mgr.default_ttl
    try:
        ticket = await ticket_mgr.generate_ticket(
            principal.user.username, ttl_seconds=ttl, sid=principal.sid
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="WebSocket ticket service unavailable") from exc
    return {"token": ticket, "expires_in": ttl}



@public_router.get(
    "/.well-known/jwks.json",
    summary="Get JSON Web Key Set",
    description="Returns public RSA keys used to verify Order Checker access tokens.",
)
def jwks_endpoint():
    """Returns the JSON Web Key Set containing the public key for verifying JWTs."""
    return {"keys": key_mgr.get_jwks()}


@router.post(
    "/refresh",
    response_model=Token,
    summary="Rotate a refresh token",
    description="Consumes a stored refresh token and returns a replacement token pair.",
    responses={401: {"description": "Invalid, expired, revoked, or already consumed token"}},
)
def refresh(body: RefreshTokenRequest):
    return auth_service.refresh_tokens(body.refresh_token)
