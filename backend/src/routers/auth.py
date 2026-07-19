import logging
from datetime import datetime, UTC
import jwt
import jwt.exceptions as jwt_exc
from jwt import PyJWK
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Token, UserAuth, User, RefreshTokenRequest, RefreshToken
from ..dependencies import get_db, get_current_user, ALGORITHM, key_manager
from ..services.manager import conn_mgr, ticket_mgr
from ..services import auth_service

logger = logging.getLogger("backend.routers.auth")

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=Token)
async def register_client(auth: UserAuth, db: Session = Depends(get_db)):
    logger.info(f"Registration attempt for username: {auth.username}")
    user = (
        db.execute(select(User).filter(User.username == auth.username))
        .scalars()
        .first()
    )
    if user:
        logger.warning(f"Registration failed: Username {auth.username} already exists")
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = auth_service.get_password_hash(auth.password)

    new_user = User(
        username=auth.username, password_hash=hashed_password, scope="client"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info(f"User {auth.username} successfully registered")

    from ..models import WSMessageType

    await conn_mgr.broadcast(WSMessageType.USERS, db, scope="admin")
    return auth_service.get_tokens(new_user, db)


@router.post("/auth/login", response_model=Token)
def login_client(auth: UserAuth, db: Session = Depends(get_db)):
    logger.info(f"Login attempt for client: {auth.username}")
    user = (
        db.execute(select(User).filter(User.username == auth.username))
        .scalars()
        .first()
    )
    if not user:
        logger.warning(f"Login failed: User {auth.username} not found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    if not auth_service.verify_password(auth.password, user.password_hash or ""):
        logger.warning(f"Login failed: Incorrect password for user {auth.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    logger.info(f"Client {auth.username} logged in successfully")
    return auth_service.get_tokens(user, db)


@router.post("/auth/logout")
def logout(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    token = body.refresh_token
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        if kid is None:
            raise jwt_exc.InvalidTokenError("Token must include kid")
        jwk = key_manager.get_public_key(kid)
        if jwk is None:
            raise jwt_exc.InvalidTokenError("Key not found")
        payload = jwt.decode(
            token,
            PyJWK.from_dict(jwk).key,
            audience="api.bakingholic:v0.2a",
            issuer="auth.bakingholic:v0.2a",
            options={"require": ["exp", "nbf", "sub", "aud", "iss", "jti", "iat"]},
            algorithms=[ALGORITHM],
            leeway=30.0,
        )
        if payload.get("type") != "refresh":
            raise jwt_exc.InvalidTokenError("Invalid token type")
        jti = payload.get("jti")
        if not jti:
            raise jwt_exc.InvalidTokenError("Token must include jti")
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise HTTPException(status_code=400, detail="Bad Request") from exc

    db_token = (
        db.execute(select(RefreshToken).filter(RefreshToken.jti == jti))
        .scalars()
        .first()
    )
    if db_token:
        logger.info(f"Revoking refresh token for user: {db_token.username}")
        db.delete(db_token)
        db.commit()
    else:
        logger.debug("Logout: Token not found or already revoked")
    return {"message": "Logged out successfully"}


@router.post("/auth/admin", response_model=Token)
def login_admin(auth: UserAuth, db: Session = Depends(get_db)):
    logger.info(f"Admin login attempt for: {auth.username}")
    user = (
        db.execute(select(User).filter(User.username == auth.username))
        .scalars()
        .first()
    )
    if (
        not user
        or user.scope != "admin"
        or not auth_service.verify_password(auth.password, user.password_hash or "")
    ):
        logger.warning(f"Admin login failed for: {auth.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    logger.info(f"Admin {auth.username} logged in successfully")
    return auth_service.get_tokens(user, db)


@router.post("/auth/ws-token")
async def create_ws_token(
    current_user: User = Depends(get_current_user),
):
    ticket = await ticket_mgr.generate_ticket(current_user.username, ttl_seconds=30)
    return {"token": ticket, "expires_in": 30}


@router.get("/.well-known/jwks.json")
def jwks_endpoint():
    """Returns the JSON Web Key Set containing the public key for verifying JWTs."""
    return {"keys": key_manager.get_jwks()}


@router.post("/auth/refresh", response_model=Token)
def refresh(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
    )
    token = body.refresh_token
    logger.info("Token refresh requested")
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        if kid is None:
            raise jwt_exc.InvalidTokenError("Token must include kid")
        jwk = key_manager.get_public_key(kid)
        if jwk is None:
            raise jwt_exc.InvalidTokenError("Key not found")
        payload = jwt.decode(
            token,
            PyJWK.from_dict(jwk).key,
            audience="api.bakingholic:v0.2a",
            issuer="auth.bakingholic:v0.2a",
            options={"require": ["exp", "nbf", "sub", "aud", "iss", "jti", "iat"]},
            algorithms=[ALGORITHM],
            leeway=30.0,
        )
        if payload.get("type") != "refresh":
            raise jwt_exc.InvalidTokenError("Invalid token type")
        jti = payload.get("jti")
        if not jti:
            raise jwt_exc.InvalidTokenError("Token must include jti")
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise credentials_exception from exc

    # Check if token exists in DB
    db_token = (
        db.execute(select(RefreshToken).filter(RefreshToken.jti == jti))
        .scalars()
        .first()
    )
    if not db_token:
        logger.error("Token nonexistent")
        raise credentials_exception

    # Check revoke from DB
    if db_token.revoked_at and db_token.revoked_at.replace(tzinfo=UTC) < datetime.now(
        UTC
    ):
        logger.error("Token revoked")
        db.delete(db_token)
        db.commit()
        raise credentials_exception

    # Check expiry from DB
    if db_token.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        logger.error("Token expired in DB")
        db.delete(db_token)
        db.commit()
        raise credentials_exception

    user = (
        db.execute(select(User).filter(User.username == db_token.username))
        .scalars()
        .first()
    )
    if not user:
        logger.error("User not found")
        raise credentials_exception

    # Rotate refresh token
    logger.info(f"Rotating refresh token for user: {user.username}")
    db.delete(db_token)
    db.commit()

    return auth_service.get_tokens(user, db)
