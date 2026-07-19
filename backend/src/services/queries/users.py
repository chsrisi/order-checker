import logging
from typing import List
from datetime import datetime, UTC
from sqlalchemy import select, delete, or_, update

from ...models import User, RefreshToken, OutboundItem, PickItemEntry, ShopeeOrder
from .engine import get_db

logger = logging.getLogger("backend.services.queries.users")


def get_user_data(username: str) -> User | None:
    with get_db() as db:
        return db.execute(select(User).filter(User.username == username)).scalars().first()


def get_all_user_data() -> List[User]:
    with get_db() as db:
        return list(db.execute(select(User).filter(User.scope == "client")).scalars().all())


def create_user(username: str, password_hash: str, scope: str = "client") -> User:
    with get_db() as db:
        new_user = User(username=username, password_hash=password_hash, scope=scope)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user


def seed_admin_user(username: str, password_hash: str) -> bool:
    """Create the configured administrator if it does not already exist."""
    with get_db() as db:
        admin_user = db.execute(select(User).filter(User.username == username)).scalars().first()
        if not admin_user:
            logger.info("admin_user_seeded", extra={"admin_username": username})
            db_admin = User(username=username, password_hash=password_hash, scope="admin")
            db.add(db_admin)
            db.commit()
            return True
        else:
            logger.debug("admin_user_exists", extra={"admin_username": username})
            return False


def delete_user_by_username(username: str) -> bool:
    with get_db() as db:
        user = db.execute(select(User).filter(User.username == username)).scalars().first()
        if not user or user.scope == "admin":
            return False

        # Delete outbounds, pick items, refresh tokens
        db.execute(delete(OutboundItem).where(OutboundItem.owner_user == username))
        db.execute(delete(PickItemEntry).where(PickItemEntry.owner_user == username))
        db.execute(delete(RefreshToken).where(RefreshToken.username == username))
        db.execute(
            update(ShopeeOrder).where(ShopeeOrder.owner_user == username).values(owner_user=None)
        )
        db.delete(user)
        db.commit()
        return True


def get_refresh_token(jti: str) -> RefreshToken | None:
    with get_db() as db:
        return db.execute(select(RefreshToken).filter(RefreshToken.jti == jti)).scalars().first()


def create_refresh_token(jti: str, username: str, expires_at: datetime) -> RefreshToken:
    with get_db() as db:
        db_refresh_token = RefreshToken(jti=jti, username=username, expires_at=expires_at)
        db.add(db_refresh_token)
        db.commit()
        return db_refresh_token


def delete_refresh_token(jti: str) -> None:
    with get_db() as db:
        db_token = (
            db.execute(select(RefreshToken).filter(RefreshToken.jti == jti)).scalars().first()
        )
        if db_token:
            db.delete(db_token)
            db.commit()


def delete_outdated_refresh_tokens() -> int:
    with get_db() as db:
        result = db.execute(
            delete(RefreshToken)
            .where(
                or_(
                    RefreshToken.expires_at < datetime.now(UTC),
                    RefreshToken.revoked_at.isnot(None),
                )
            )
            .returning(RefreshToken.jti)
        )
        db.commit()
        return len(result.all())
