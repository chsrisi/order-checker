import asyncio
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from passlib.context import CryptContext
import jwt
import jwt.exceptions as jwt_exc
from jwt import PyJWK
from fastapi import Depends, HTTPException, Request, status
from fastapi.security.http import HTTPBearer, HTTPAuthorizationCredentials

from .managers import key_mgr, ACCESS_TTL_SECONDS, conn_mgr
from .managers.login_throttle import login_throttle
from sqlalchemy.exc import IntegrityError

from . import queries
from .. import config
from ..exceptions import DomainException
from ..models import User, WSMessageType
from ..timezone import as_utc
from ..config import (
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_ISSUER,
    JWT_LEEWAY_SECONDS,
    REFRESH_TTL_SECONDS,
    REFRESH_CLEANUP_INTERVAL_SECONDS,
)

logger = logging.getLogger("backend.services.auth")
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
ALGORITHM = JWT_ALGORITHM
# ``sid`` (session id) is required since v0.6.0 (T6.2, V2_DELTA Q24): a token without one
# predates sessions and is rejected, so every user logs in once after the upgrade.
REQUIRED_CLAIMS = ["exp", "nbf", "sub", "aud", "iss", "jti", "iat", "sid"]


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
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
        options={"require": REQUIRED_CLAIMS},
        algorithms=[ALGORITHM],
        leeway=JWT_LEEWAY_SECONDS,
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
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
        options={"require": REQUIRED_CLAIMS},
        algorithms=[ALGORITHM],
        leeway=JWT_LEEWAY_SECONDS,
    )
    if payload.get("type") != "refresh":
        raise jwt_exc.InvalidTokenError("Invalid token type")
    jti = payload.get("jti")
    if not jti:
        raise jwt_exc.InvalidTokenError("Token must include jti")
    return payload


@dataclass(frozen=True)
class Principal:
    """The authenticated caller: the user row and the session (``sid``) of its token."""

    user: User
    sid: str


def get_current_principal(
    token: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    request: Request = None,  # type: ignore[assignment]  # injected by FastAPI
) -> Principal:
    # Plain def: FastAPI runs it in the threadpool, so the DB lookup and RSA verification
    # never block the event loop (F-H1).
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = verify_access_token(token.credentials)
        # One query: the user *and* a live session. A revoked or deleted session answers
        # 401 on the very next request (instant revocation, T6.2).
        # A gated /v2 request carries the app's versionCode (set by the gate, which runs
        # first); it updates the session's device (T6.6).
        client_version = getattr(request.state, "client_version", None) if request else None
        user = queries.get_user_for_session(payload["sub"], payload["sid"], client_version)
        if not user:
            raise jwt_exc.InvalidTokenError("User or session not found")
        return Principal(user=user, sid=payload["sid"])
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise credentials_exception from exc


def get_current_user(principal: Principal = Depends(get_current_principal)) -> User:
    return principal.user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    return current_user


def require_operator(current_user: User = Depends(get_current_user)) -> User:
    """Contract v2: admins administer, they do not work on orders (V2_PICKING_DELTA Q69, Q75)."""
    if current_user.scope == "admin":
        raise HTTPException(status_code=403, detail="Admin accounts cannot work on orders")
    return current_user


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def new_session_id() -> str:
    return secrets.token_hex(16)


def create_access_token(username: str, sid: str) -> str:
    expire = datetime.now(UTC) + timedelta(seconds=ACCESS_TTL_SECONDS)
    to_encode = {
        "sub": username,
        "sid": sid,
        "exp": expire,
        "type": "access",
        "jti": secrets.token_hex(16),
        "iat": datetime.now(UTC),
        "nbf": datetime.now(UTC),
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
    }

    sig = key_mgr.get_active_signer()

    encoded_jwt = jwt.encode(
        to_encode, sig.private_key, algorithm=ALGORITHM, headers={"kid": sig.kid}
    )
    logger.debug(f"Created access token for user: {username} with KID: {sig.kid}")
    return encoded_jwt


def create_refresh_token(username: str, sid: str):
    expires_delta = timedelta(seconds=REFRESH_TTL_SECONDS)
    expire = datetime.now(UTC) + expires_delta
    to_encode = {
        "sub": username,
        "sid": sid,
        "type": "refresh",
        "jti": secrets.token_hex(16),
        "exp": expire,
        "iat": datetime.now(UTC),
        "nbf": datetime.now(UTC),
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
    }

    sig = key_mgr.get_active_signer()

    encoded_jwt = jwt.encode(
        to_encode, sig.private_key, algorithm=ALGORITHM, headers={"kid": sig.kid}
    )
    logger.debug(
        f"Created refresh token for user: {username}, expires at: {expire} with KID: {sig.kid}"
    )
    return encoded_jwt, to_encode["jti"], expire


def get_tokens(
    user: User,
    sid: str | None = None,
    ip_address: str | None = None,
    agent: str | None = None,
    new_sid: str | None = None,
):
    """Issue a token pair. Without ``sid`` a new session starts (login, registration); with
    ``sid`` the pair belongs to that existing, live session (refresh rotation). ``new_sid``
    names the new session when the caller has to know its id."""
    logger.info(f"Generating tokens for user: {user.username} (scope: {user.scope})")
    new_session = sid is None
    session_id = (new_sid or new_session_id()) if new_session else sid
    access_token = create_access_token(user.username, session_id)
    refresh_token, jti, expire = create_refresh_token(user.username, session_id)

    if new_session:
        queries.create_session(
            username=user.username,
            jti=jti,
            expires_at=expire,
            sid=session_id,
            ip_address=ip_address,
            agent=(agent or "")[:256] or None,
        )
    elif not queries.create_refresh_token(
        jti=jti, username=user.username, expires_at=expire, session_id=session_id
    ):
        # The session was revoked between consuming the old token and storing the new one.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    logger.debug(f"Refresh token stored in DB for user {user.username}, expires at {expire}")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


async def delete_user(username: str, actor: str = "admin") -> None:
    success = await asyncio.to_thread(queries.delete_user_by_username, username, actor)
    if not success:
        raise DomainException(status_code=404, detail="User not found")

    await conn_mgr.disconnect_user(username)
    await conn_mgr.broadcast(WSMessageType.USERS, scope="admin")
    # The user's pick entries were deleted with their stock restored, its outbound scans
    # deleted and its claimed orders released.
    await conn_mgr.broadcast(WSMessageType.PICK_ITEM_ENTRIES, scope="admin")
    await conn_mgr.broadcast(WSMessageType.OUTBOUNDS, scope="admin")
    await conn_mgr.broadcast(WSMessageType.SHOPEE_ORDERS, scope="admin")
    await conn_mgr.broadcast(WSMessageType.STOCKS)


async def admin_create_user(username: str, password: str) -> User:
    """Create a client-scope operator account (A-3: accounts are created admin-side)."""
    if await asyncio.to_thread(queries.get_user_data, username):
        raise DomainException(status_code=409, detail="Username already exists")
    password_hash = await asyncio.to_thread(get_password_hash, password)
    try:
        user = await asyncio.to_thread(
            queries.create_user, username=username, password_hash=password_hash, scope="client"
        )
    except IntegrityError as exc:  # lost a race with another create
        raise DomainException(status_code=409, detail="Username already exists") from exc
    logger.info(f"Operator account {username} created by an administrator")
    await conn_mgr.broadcast(WSMessageType.USERS, scope="admin")
    return user


async def admin_logout_user(username: str) -> int:
    """Log a client account out everywhere: revoke all its sessions, close its sockets."""
    sids = await asyncio.to_thread(queries.revoke_user_sessions, username)
    if sids is None:
        raise DomainException(status_code=404, detail="User not found")
    logger.info(f"All sessions of {username} revoked by an administrator ({len(sids)})")
    await conn_mgr.disconnect_user(username)
    return len(sids)


async def admin_reset_password(username: str, password: str) -> None:
    """Set a new password, revoke every refresh token and close the user's sockets."""
    password_hash = await asyncio.to_thread(get_password_hash, password)
    if not await asyncio.to_thread(queries.set_password_and_revoke_sessions, username, password_hash):
        raise DomainException(status_code=404, detail="User not found")
    logger.info(f"Password reset for {username}; sessions revoked")
    await conn_mgr.disconnect_user(username)
    await conn_mgr.broadcast(WSMessageType.USERS, scope="admin")


async def register_client(username: str, password: str) -> dict:
    logger.info(f"Registration attempt for username: {username}")
    if not config.ALLOW_REGISTRATION:
        # Path and schema stay (client contract v1); production creates accounts admin-side.
        raise DomainException(status_code=403, detail="Registration is disabled")
    user = await asyncio.to_thread(queries.get_user_data, username)
    if user:
        logger.warning(f"Registration failed: Username {username} already exists")
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = await asyncio.to_thread(get_password_hash, password)
    new_user = await asyncio.to_thread(
        queries.create_user, username=username, password_hash=hashed_password, scope="client"
    )
    logger.info(f"User {username} successfully registered")

    await conn_mgr.broadcast(WSMessageType.USERS, scope="admin")
    return get_tokens(new_user)


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = get_password_hash(secrets.token_urlsafe(16))
    return _DUMMY_HASH


async def login_throttled(
    username: str,
    password: str,
    required_scope: str | None = None,
    ip_address: str | None = None,
    agent: str | None = None,
) -> dict:
    """Login with per-username failure throttling; Argon2 runs off the event loop."""
    if await login_throttle.is_locked(username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(login_throttle.window)},
        )
    try:
        tokens = await asyncio.to_thread(
            login_user, username, password, required_scope, ip_address, agent
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            await login_throttle.record_failure(username)
        raise
    await login_throttle.reset(username)
    return tokens


def login_user(
    username: str,
    password: str,
    required_scope: str | None = None,
    ip_address: str | None = None,
    agent: str | None = None,
) -> dict:
    logger.info(f"Login attempt for user: {username} (required scope: {required_scope})")
    user = queries.get_user_data(username)
    if not user:
        logger.warning(f"Login failed: User {username} not found")
        # Same Argon2 cost as a real check, so response time does not reveal which
        # usernames exist (F-M17).
        verify_password(password, _dummy_hash())
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
    return get_tokens(user, ip_address=ip_address, agent=agent)


async def logout_user(refresh_token: str) -> dict:
    """End the token's session: revoke it, delete its refresh tokens, close its sockets."""
    try:
        payload = verify_refresh_token(refresh_token)
        sid = payload["sid"]
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise HTTPException(status_code=400, detail="Bad Request") from exc

    await asyncio.to_thread(queries.revoke_session, sid)
    await conn_mgr.disconnect_session(sid)
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

    # Single gate: the row is deleted and read in one statement, so a token can be
    # used at most once even under concurrent refreshes (F-H5).
    db_token = queries.consume_refresh_token(jti)
    if not db_token:
        logger.error("Token nonexistent or already used")
        raise credentials_exception

    if db_token.revoked_at is not None:
        logger.error("Token revoked")
        raise credentials_exception

    if as_utc(db_token.expires_at) < datetime.now(UTC):
        logger.error("Token expired in DB")
        raise credentials_exception

    if db_token.session_id != payload.get("sid"):
        logger.error("Token session mismatch")
        raise credentials_exception

    user = queries.get_user_data(db_token.username)
    if not user:
        logger.error("User not found")
        raise credentials_exception

    logger.info(f"Rotating refresh token for user: {user.username}")
    return get_tokens(user, sid=db_token.session_id)


def _delete_outdated_refresh_tokens() -> int:
    return queries.delete_outdated_refresh_tokens()


async def remove_outdated_refresh_task():
    try:
        while True:
            await asyncio.sleep(REFRESH_CLEANUP_INTERVAL_SECONDS)
            count = await asyncio.to_thread(_delete_outdated_refresh_tokens)
            if count:
                logger.info(f"Deleted {count} outdated refresh tokens")
    except asyncio.CancelledError:
        logger.info("Remove outdated refresh task cancelled")
        raise
