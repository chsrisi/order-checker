import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from passlib.context import CryptContext
import jwt
from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from ..models import User, RefreshToken
from ..keys import ACCESS_TTL_SECONDS
from ..dependencies import key_manager, ALGORITHM, ctx_get_db

logger = logging.getLogger("backend.services.auth")

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


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
        "aud": "api.bakingholic:v0.2a",
        "iss": "auth.bakingholic:v0.2a",
    }

    sig = key_manager.get_active_signer()

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
        "aud": "api.bakingholic:v0.2a",
        "iss": "auth.bakingholic:v0.2a",
    }

    sig = key_manager.get_active_signer()

    encoded_jwt = jwt.encode(
        to_encode, sig.private_key, algorithm=ALGORITHM, headers={"kid": sig.kid}
    )
    logger.debug(
        f"Created refresh token for user: {username}, expires at: {expire} with KID: {sig.kid}"
    )
    return encoded_jwt, to_encode["jti"], expire


def get_tokens(user: User, db: Session):
    logger.info(f"Generating tokens for user: {user.username} (scope: {user.scope})")
    access_token = create_access_token(user.username)
    refresh_token, jti, expire = create_refresh_token(user.username)

    # Store refresh token in DB
    db_refresh_token = RefreshToken(jti=jti, username=user.username, expires_at=expire)
    db.add(db_refresh_token)
    db.commit()
    logger.debug(
        f"Refresh token stored in DB for user {user.username}, expires at {expire}"
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


def _delete_outdated_refresh_tokens() -> int:
    with ctx_get_db() as db:
        result = db.execute(
            delete(RefreshToken).where(
                or_(
                    RefreshToken.expires_at < datetime.now(UTC),
                    RefreshToken.revoked_at.isnot(None),
                )
            )
        )
        db.commit()
        return len(result.all())


async def remove_outdated_refresh():
    try:
        while True:
            await asyncio.sleep(3600)
            count = await asyncio.to_thread(_delete_outdated_refresh_tokens)
            if count:
                logger.info(f"Deleted {count} outdated refresh tokens")
    except asyncio.CancelledError:
        logger.info("Remove outdated refresh task cancelled")
        raise
