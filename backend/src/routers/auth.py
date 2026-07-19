import logging

from fastapi import APIRouter, Depends

from ..models import Token, UserAuth, User, RefreshTokenRequest
from ..dependencies import get_current_user
from ..services import auth_service
from ..services.managers import ticket_mgr, key_mgr

logger = logging.getLogger("backend.routers.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token)
async def register_client(auth: UserAuth):
    return await auth_service.register_client(auth.username, auth.password)


@router.post("/login", response_model=Token)
def login_client(auth: UserAuth):
    return auth_service.login_user(auth.username, auth.password)


@router.post("/logout")
def logout(body: RefreshTokenRequest):
    return auth_service.logout_user(body.refresh_token)


@router.post("/ws-token")
async def create_ws_token(
    current_user: User = Depends(get_current_user),
):
    ticket = await ticket_mgr.generate_ticket(current_user.username, ttl_seconds=30)
    return {"token": ticket, "expires_in": 30}


@router.get("/.well-known/jwks.json")
def jwks_endpoint():
    """Returns the JSON Web Key Set containing the public key for verifying JWTs."""
    return {"keys": key_mgr.get_jwks()}


@router.post("/refresh", response_model=Token)
def refresh(body: RefreshTokenRequest):
    return auth_service.refresh_tokens(body.refresh_token)
