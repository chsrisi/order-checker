import logging
from typing import Generator, Optional

import jwt
import jwt.exceptions as jwt_exc
from jwt import PyJWK
from fastapi import Depends, HTTPException, status
from fastapi.security.http import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from contextlib import contextmanager

from .models import User
from .keys import KeyManager
from .config import get_config_value

logger = logging.getLogger("backend.dependencies")

# Database setup
# TODO: raise if no postgres db url, remove sqlite fallback
SQLALCHEMY_DATABASE_URL: Optional[str] = get_config_value("DATABASE_URL")
if not SQLALCHEMY_DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./local.db"
    logger.warning(
        "DATABASE_URL not found in env/secrets, defaulting to: %s",
        SQLALCHEMY_DATABASE_URL,
    )

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Security and Key Manager setup
ALGORITHM = "RS256"
key_manager = KeyManager()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    logger.debug("Database session opened")
    try:
        yield db
    finally:
        db.close()
        logger.debug("Database session closed")


@contextmanager
def ctx_get_db():
    db = SessionLocal()
    logger.debug("Database session opened (context)")
    try:
        yield db
    finally:
        db.close()
        logger.debug("Database session closed (context)")


def get_user(token: str, db: Session) -> User:
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
    if payload.get("type") != "access":
        raise jwt_exc.InvalidTokenError("Invalid token type")
    username: str | None = payload.get("sub")
    if username is None:
        raise jwt_exc.InvalidTokenError("Token must include subject (sub)")

    user = db.execute(select(User).filter(User.username == username)).scalars().first()
    if not user:
        raise jwt_exc.InvalidTokenError("User not found in db")

    return user


async def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: Session = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user = get_user(token.credentials, db)
    except jwt_exc.InvalidTokenError as exc:
        logger.error(str(exc))
        raise credentials_exception from exc

    logger.debug(f"User authenticated: {user.username}")
    return user
