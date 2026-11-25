"""v2 device registration (IMPLEMENTATION_PLAN T6.6, V2_SPEC §4A)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Iterable, List, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ...models import AuthSession, Device
from .engine import get_db

logger = logging.getLogger("backend.services.queries.devices")


class DeviceRevoked(Exception):
    """The public key belongs to a revoked device; it must not register again."""


def register_device(
    *,
    public_key: str,
    model: str,
    android_version: str,
    app_version_code: int,
    username: str,
    sid: str,
) -> Device:
    """Upsert the device by ``public_key`` and bind session ``sid`` to it. A new device is
    ``pending``; a known one keeps its status (``revoked`` raises ``DeviceRevoked``).
    Idempotent: registering again only refreshes the reported fields."""
    for attempt in (1, 2):
        with get_db() as db:
            now = datetime.now(UTC)
            device = (
                db.execute(select(Device).where(Device.public_key == public_key).with_for_update())
                .scalars()
                .first()
            )
            if device is not None and device.status == "revoked":
                raise DeviceRevoked()
            if device is None:
                device = Device(
                    id=uuid.uuid4().hex,
                    public_key=public_key,
                    status="pending",
                    enrolled_at=now,
                )
                db.add(device)
            device.model = model
            device.android_version = android_version
            device.app_version_code = app_version_code
            device.current_username = username
            device.last_seen_at = now
            try:
                db.flush()
            except IntegrityError:
                # Two first registrations of one key raced; the second one updates.
                db.rollback()
                if attempt == 2:
                    raise
                continue
            db.execute(
                update(AuthSession)
                .where(AuthSession.id == sid, AuthSession.revoked_at.is_(None))
                .values(device_id=device.id)
            )
            db.commit()
            db.refresh(device)
            db.expunge(device)
            return device
    raise RuntimeError("unreachable")


def list_devices() -> List[Device]:
    with get_db() as db:
        devices = (
            db.execute(select(Device).order_by(Device.last_seen_at.desc().nulls_last()))
            .scalars()
            .all()
        )
        for device in devices:
            db.expunge(device)
        return list(devices)


def device_ids_for_sessions(sids: Iterable[str]) -> set[str]:
    """Devices bound to any of these live (not revoked) sessions."""
    sids = list(sids)
    if not sids:
        return set()
    with get_db() as db:
        rows = db.execute(
            select(AuthSession.device_id).where(
                AuthSession.id.in_(sids),
                AuthSession.revoked_at.is_(None),
                AuthSession.device_id.is_not(None),
            )
        )
        return {row[0] for row in rows}


def get_device(device_id: str) -> Optional[Device]:
    with get_db() as db:
        device = db.get(Device, device_id)
        if device is not None:
            db.expunge(device)
        return device


def get_device_by_public_key(public_key: str) -> Optional[Device]:
    with get_db() as db:
        device = (
            db.execute(select(Device).where(Device.public_key == public_key)).scalars().first()
        )
        if device is not None:
            db.expunge(device)
        return device


def bind_session_to_device(sid: str, device_id: str, username: str) -> bool:
    """Bind a fresh session to its device. False when the device was revoked meanwhile."""
    with get_db() as db:
        device = (
            db.execute(select(Device).where(Device.id == device_id).with_for_update())
            .scalars()
            .first()
        )
        if device is None or device.status == "revoked":
            return False
        device.current_username = username
        device.last_seen_at = datetime.now(UTC)
        db.execute(
            update(AuthSession).where(AuthSession.id == sid).values(device_id=device_id)
        )
        db.commit()
        return True
