import logging
from typing import List
from datetime import datetime, UTC, timedelta
from sqlalchemy import select, delete, or_, update

from ...models import (
    AuthSession,
    Device,
    User,
    RefreshToken,
    OutboundItem,
    PickItemEntry,
    ShopeeOrder,
    Task,
)
from ...timezone import as_utc
from .engine import get_db
from .stocks import restore_for_pick

logger = logging.getLogger("backend.services.queries.users")

# last_seen_at is written at most this often per session (IMPLEMENTATION_PLAN P-16).
LAST_SEEN_INTERVAL = timedelta(seconds=60)


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


def delete_user_by_username(username: str, actor: str = "admin") -> bool:
    """Delete a client account in one transaction. Its pick entries are deleted like
    ``DELETE /pick-items/{id}``: their allocated stock is restored and logged (D1.4.2) with
    ``actor`` (the deleting admin). Outbound scans and refresh tokens are deleted, and
    claimed orders are released.

    Tasks stay (P-32): the worker's tasks lose their assignee (``assigned_name`` keeps the
    name), and their task picks stay with the task, stock untouched, without an owner (T12)."""
    with get_db() as db:
        user = db.execute(select(User).filter(User.username == username)).scalars().first()
        if not user or user.scope == "admin":
            return False

        # Lock order as in queries/pick_items.py: orders, entries, allocations, then stock rows
        # (by sku, so concurrent picks on several SKUs cannot deadlock against this).
        db.execute(
            select(ShopeeOrder.order_sn)
            .where(ShopeeOrder.owner_user == username)
            .order_by(ShopeeOrder.order_sn)
            .with_for_update(key_share=True)
        ).all()
        # Tasks before their entries, as in queries/tasks.py.
        db.execute(
            select(Task.id).where(Task.assigned_to == username).order_by(Task.id).with_for_update()
        ).all()
        entries = (
            db.execute(
                select(PickItemEntry)
                .filter(PickItemEntry.owner_user == username, PickItemEntry.task_line_id.is_(None))
                .order_by(PickItemEntry.sku, PickItemEntry.id)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        for entry in entries:
            restore_for_pick(db, entry, actor=actor)
            db.delete(entry)
        db.execute(
            update(PickItemEntry)
            .where(PickItemEntry.owner_user == username, PickItemEntry.task_line_id.is_not(None))
            .values(owner_user=None)
        )
        # The FK sets NULL too; explicit, so no task depends on the database doing it.
        db.execute(update(Task).where(Task.assigned_to == username).values(assigned_to=None))
        db.execute(delete(OutboundItem).where(OutboundItem.owner_user == username))
        db.execute(delete(RefreshToken).where(RefreshToken.username == username))
        db.execute(delete(AuthSession).where(AuthSession.username == username))
        db.execute(
            update(ShopeeOrder).where(ShopeeOrder.owner_user == username).values(owner_user=None)
        )
        db.delete(user)
        db.commit()
        return True


def _revoke_user_sessions(db, username: str) -> list[str]:
    """Revoke every live session of ``username`` and delete its refresh tokens (no commit)."""
    now = datetime.now(UTC)
    sids = list(
        db.execute(
            update(AuthSession)
            .where(AuthSession.username == username, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(AuthSession.id)
        ).scalars()
    )
    db.execute(delete(RefreshToken).where(RefreshToken.username == username))
    return sids


def set_password_and_revoke_sessions(username: str, password_hash: str) -> bool:
    """Replace a client account's password and revoke all its sessions atomically."""
    with get_db() as db:
        user = db.execute(select(User).filter(User.username == username)).scalars().first()
        if not user or user.scope == "admin":
            return False
        user.password_hash = password_hash
        _revoke_user_sessions(db, username)
        db.commit()
        return True


def revoke_user_sessions(username: str, *, client_only: bool = True) -> list[str] | None:
    """Revoke every session of a user ("log out everywhere"). Returns the revoked session ids,
    or ``None`` when the user is unknown (or an admin while ``client_only``)."""
    with get_db() as db:
        user = db.execute(select(User).filter(User.username == username)).scalars().first()
        if not user or (client_only and user.scope == "admin"):
            return None
        sids = _revoke_user_sessions(db, username)
        db.commit()
        return sids


def create_session(
    username: str,
    jti: str,
    expires_at: datetime,
    sid: str,
    ip_address: str | None = None,
    agent: str | None = None,
) -> AuthSession:
    """Start a session and store its first refresh token, in one transaction."""
    with get_db() as db:
        session = AuthSession(
            id=sid,
            username=username,
            expires_at=expires_at,
            last_seen_at=datetime.now(UTC),
            ip_address=ip_address,
            agent=agent,
        )
        db.add(session)
        db.flush()
        db.add(RefreshToken(jti=jti, username=username, expires_at=expires_at, session_id=sid))
        db.commit()
        return session


def create_refresh_token(jti: str, username: str, expires_at: datetime, session_id: str) -> bool:
    """Store a rotated refresh token for a live session and extend the session's expiry.
    Returns ``False`` when the session is gone or revoked (the rotation must fail)."""
    with get_db() as db:
        extended = db.execute(
            update(AuthSession)
            .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
            .values(expires_at=expires_at)
            .returning(AuthSession.id)
        ).first()
        if extended is None:
            db.rollback()
            return False
        db.add(
            RefreshToken(jti=jti, username=username, expires_at=expires_at, session_id=session_id)
        )
        db.commit()
        return True


def get_user_for_session(username: str, sid: str, client_version: int | None = None) -> User | None:
    """The user, if ``sid`` is one of its live sessions; touches ``last_seen_at`` at most once
    per ``LAST_SEEN_INTERVAL``. This is the per-request check behind instant revocation (T6.2).

    ``client_version`` (the ``X-Client-Version`` of a gated /v2 request) also touches the
    session's device: ``last_seen_at`` on the same throttle, and ``app_version_code`` as soon as
    it changes, which is how an admin sees that an OTA update arrived (T6.6, P-16)."""
    with get_db() as db:
        row = db.execute(
            select(User, AuthSession.last_seen_at, AuthSession.device_id, Device.app_version_code)
            .join(AuthSession, AuthSession.username == User.username)
            .outerjoin(Device, Device.id == AuthSession.device_id)
            .where(
                User.username == username,
                AuthSession.id == sid,
                AuthSession.revoked_at.is_(None),
            )
        ).first()
        if row is None:
            return None
        user, last_seen, device_id, device_version = row
        now = datetime.now(UTC)
        stale = last_seen is None or as_utc(last_seen) < now - LAST_SEEN_INTERVAL
        if stale:
            db.execute(update(AuthSession).where(AuthSession.id == sid).values(last_seen_at=now))
        if device_id is not None and client_version is not None:
            if stale or device_version != client_version:
                db.execute(
                    update(Device)
                    .where(Device.id == device_id)
                    .values(last_seen_at=now, app_version_code=client_version)
                )
                stale = True
        if stale:
            db.commit()
        return user


def revoke_session(sid: str) -> None:
    """End one session (logout): mark it revoked and delete its refresh tokens."""
    with get_db() as db:
        db.execute(
            update(AuthSession)
            .where(AuthSession.id == sid, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        db.execute(delete(RefreshToken).where(RefreshToken.session_id == sid))
        db.commit()


def delete_refresh_token(jti: str) -> None:
    with get_db() as db:
        db_token = (
            db.execute(select(RefreshToken).filter(RefreshToken.jti == jti)).scalars().first()
        )
        if db_token:
            db.delete(db_token)
            db.commit()


def consume_refresh_token(jti: str):
    """Delete the token row and return what it held, in one statement (F-H5).

    This is the single gate of refresh rotation: of two concurrent refreshes with the same
    token, only one gets a row back. Returns ``None`` when the token is unknown or already used.
    """
    with get_db() as db:
        row = db.execute(
            delete(RefreshToken)
            .where(RefreshToken.jti == jti)
            .returning(
                RefreshToken.username,
                RefreshToken.expires_at,
                RefreshToken.revoked_at,
                RefreshToken.session_id,
            )
        ).first()
        db.commit()
        return row


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
        count = len(result.all())
        # Sessions past their last refresh expiry (revoked or not) go too.
        db.execute(delete(AuthSession).where(AuthSession.expires_at < datetime.now(UTC)))
        db.commit()
        return count
