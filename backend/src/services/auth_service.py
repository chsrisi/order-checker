import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from passlib.context import CryptContext
import jwt
import jwt.exceptions as jwt_exc
from jwt import PyJWK
from fastapi import Depends, HTTPException, status
from fastapi.security.http import HTTPBearer, HTTPAuthorizationCredentials

from .managers import key_mgr, ACCESS_TTL_SECONDS, conn_mgr
from . import queries
from ..models import User, WSMessageType

logger = logging.getLogger("backend.services.auth")
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
ALGORITHM = "RS256"


def verify_access_token(token: str) -> dict:
    kid = jwt.get_unverified_header(token).get("kid")
    if kid is None:
        raise jwt_exc.InvalidTokenError("Token must include kid")
    jwk = key_mgr.get_public_key(kid)
    if jwk is None:
        raise jwt_exc.InvalidTokenError("Key not found")
    payload = jwt.decode(
        token,
        PyJWK.from_dict(jwk).key,
        audience="api.bakingholic:v0.3a",
        issuer="auth.bakingholic:v0.3a",
        options={"require": ["exp", "nbf", "sub", "aud", "iss", "jti", "iat"]},
        algorithms=[ALGORITHM],
        leeway=30.0,
    )
    if payload.get("type") != "access":
        raise jwt_exc.InvalidTokenError("Invalid token type")
    username: str | None = payload.get("sub")
    if username is None:
        raise jwt_exc.InvalidTokenError("Token must include subject (sub)")
    return payload


def verify_refresh_token(token: str) -> dict:
    kid = jwt.get_unverified_header(token).get("kid")
    if kid is None:
        raise jwt_exc.InvalidTokenError("Token must include kid")
    jwk = key_mgr.get_public_key(kid)
    if jwk is None:
        raise jwt_exc.InvalidTokenError("Key not found")
    payload = jwt.decode(
        token,
        PyJWK.from_dict(jwk).key,
        audience="api.bakingholic:v0.3a",
        issuer="auth.bakingholic:v0.3a",
        options={"require": ["exp", "nbf", "sub", "aud", "iss", "jti", "iat"]},
        algorithms=[ALGORITHM],
        leeway=30.0,
    )
    if payload.get("type") != "refresh":
        raise jwt_exc.InvalidTokenError("Invalid token type")
    jti = payload.get("jti")
    if not jti:
        raise jwt_exc.InvalidTokenError("Token must include jti")
    return payload


async def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = verify_access_token(token.credentials)
        username = payload["sub"]
        user = queries.get_user_data(username)
        if not user:
            raise jwt_exc.InvalidTokenError("User not found in db")
        return user
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise credentials_exception from exc


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(username: str) -> str:
    expire = datetime.now(UTC) + timedelta(seconds=ACCESS_TTL_SECONDS)
    to_encode = {
        "sub": username,
        "exp": expire,
        "type": "access",
        "jti": secrets.token_hex(16),
        "iat": datetime.now(UTC),
        "nbf": datetime.now(UTC),
        "aud": "api.bakingholic:v0.3a",
        "iss": "auth.bakingholic:v0.3a",
    }

    sig = key_mgr.get_active_signer()

    encoded_jwt = jwt.encode(
        to_encode, sig.private_key, algorithm=ALGORITHM, headers={"kid": sig.kid}
    )
    logger.debug(f"Created access token for user: {username} with KID: {sig.kid}")
    return encoded_jwt


def create_refresh_token(username: str):
    expires_delta = timedelta(hours=24)
    expire = datetime.now(UTC) + expires_delta
    to_encode = {
        "sub": username,
        "type": "refresh",
        "jti": secrets.token_hex(16),
        "exp": expire,
        "iat": datetime.now(UTC),
        "nbf": datetime.now(UTC),
        "aud": "api.bakingholic:v0.3a",
        "iss": "auth.bakingholic:v0.3a",
    }

    sig = key_mgr.get_active_signer()

    encoded_jwt = jwt.encode(
        to_encode, sig.private_key, algorithm=ALGORITHM, headers={"kid": sig.kid}
    )
    logger.debug(
        f"Created refresh token for user: {username}, expires at: {expire} with KID: {sig.kid}"
    )
    return encoded_jwt, to_encode["jti"], expire


def get_tokens(user: User):
    logger.info(f"Generating tokens for user: {user.username} (scope: {user.scope})")
    access_token = create_access_token(user.username)
    refresh_token, jti, expire = create_refresh_token(user.username)

    queries.create_refresh_token(jti=jti, username=user.username, expires_at=expire)
    logger.debug(f"Refresh token stored in DB for user {user.username}, expires at {expire}")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


async def delete_user(username: str) -> None:
    from . import queries

    success = queries.delete_user_by_username(username)
    if not success:
        from ..exceptions import DomainException

        raise DomainException(status_code=404, detail="User not found")

    from .managers import conn_mgr
    from ..models import WSMessageType

    await conn_mgr.broadcast(WSMessageType.USERS, scope="admin")


async def register_client(username: str, password: str) -> dict:
    logger.info(f"Registration attempt for username: {username}")
    user = queries.get_user_data(username)
    if user:
        logger.warning(f"Registration failed: Username {username} already exists")
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = get_password_hash(password)
    new_user = queries.create_user(username=username, password_hash=hashed_password, scope="client")
    logger.info(f"User {username} successfully registered")

    await conn_mgr.broadcast(WSMessageType.USERS, scope="admin")
    return get_tokens(new_user)


def login_user(
    username: str,
    password: str,
    required_scope: str | None = None,
) -> dict:
    logger.info(f"Login attempt for user: {username} (required scope: {required_scope})")
    user = queries.get_user_data(username)
    if not user:
        logger.warning(f"Login failed: User {username} not found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"} if required_scope else None,
        )

    if required_scope and user.scope != required_scope:
        logger.warning(
            f"Login failed: User {username} scope '{user.scope}' does not match required '{required_scope}'"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(password, user.password_hash or ""):
        logger.warning(f"Login failed: Incorrect password for user {username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"} if required_scope else None,
        )

    logger.info(f"User {username} logged in successfully")
    return get_tokens(user)


def logout_user(refresh_token: str) -> dict:
    try:
        payload = verify_refresh_token(refresh_token)
        jti = payload["jti"]
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise HTTPException(status_code=400, detail="Bad Request") from exc

    queries.delete_refresh_token(jti)
    return {"message": "Logged out successfully"}


def refresh_tokens(refresh_token: str) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
    )
    logger.info("Token refresh requested")
    try:
        payload = verify_refresh_token(refresh_token)
        jti = payload["jti"]
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise credentials_exception from exc

    db_token = queries.get_refresh_token(jti)
    if not db_token:
        logger.error("Token nonexistent")
        raise credentials_exception

    if db_token.revoked_at is not None:
        logger.error("Token revoked")
        queries.delete_refresh_token(jti)
        raise credentials_exception

    if db_token.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        logger.error("Token expired in DB")
        queries.delete_refresh_token(jti)
        raise credentials_exception

    user = queries.get_user_data(db_token.username)
    if not user:
        logger.error("User not found")
        raise credentials_exception

    logger.info(f"Rotating refresh token for user: {user.username}")
    queries.delete_refresh_token(jti)

    return get_tokens(user)


def _delete_outdated_refresh_tokens() -> int:
    return queries.delete_outdated_refresh_tokens()


async def remove_outdated_refresh_task():
    try:
        while True:
            await asyncio.sleep(3600)
            count = await asyncio.to_thread(_delete_outdated_refresh_tokens)
            if count:
                logger.info(f"Deleted {count} outdated refresh tokens")
    except asyncio.CancelledError:
        logger.info("Remove outdated refresh task cancelled")
        raise
