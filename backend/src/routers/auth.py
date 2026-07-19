import logging

from fastapi import APIRouter, Depends, HTTPException

from ..models import (
    MessageResponse,
    RefreshTokenRequest,
    Token,
    User,
    UserAuth,
    WebSocketTicketResponse,
)
from ..dependencies import get_current_user
from ..services import auth_service
from ..services.managers import ticket_mgr, key_mgr

logger = logging.getLogger("backend.routers.auth")

router = APIRouter(prefix="/auth", tags=["authentication"])
public_router = APIRouter(tags=["authentication"])


@router.post(
    "/register",
    response_model=Token,
    summary="Register an operator account",
    description="Creates a client-scoped account and returns a new access/refresh token pair.",
    responses={400: {"description": "Username already exists"}},
)
async def register_client(auth: UserAuth):
    return await auth_service.register_client(auth.username, auth.password)


@router.post(
    "/login",
    response_model=Token,
    summary="Log in an operator",
    description="Authenticates any existing account for the operator application.",
    responses={401: {"description": "Invalid credentials"}},
)
def login_client(auth: UserAuth):
    return auth_service.login_user(auth.username, auth.password)


@router.post(
    "/admin",
    response_model=Token,
    summary="Log in an administrator",
    description="Authenticates credentials only when the account has the admin scope.",
    responses={401: {"description": "Invalid credentials or non-admin account"}},
)
def login_admin(auth: UserAuth):
    return auth_service.login_user(auth.username, auth.password, required_scope="admin")


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Log out",
    description="Deletes the supplied refresh-token record. The access token expires naturally.",
    responses={400: {"description": "Malformed refresh token"}},
)
def logout(body: RefreshTokenRequest):
    return auth_service.logout_user(body.refresh_token)


@router.post(
    "/ws-token",
    response_model=WebSocketTicketResponse,
    summary="Create a WebSocket ticket",
    description="Returns a one-use ticket that expires after 30 seconds.",
    responses={
        401: {"description": "Invalid bearer token"},
        503: {"description": "Redis unavailable"},
    },
)
async def create_ws_token(
    current_user: User = Depends(get_current_user),
):
    try:
        ticket = await ticket_mgr.generate_ticket(current_user.username, ttl_seconds=30)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="WebSocket ticket service unavailable") from exc
    return {"token": ticket, "expires_in": 30}


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
