"""v2 device registration (IMPLEMENTATION_PLAN T6.6, P-12).

The app creates an EC P-256 key pair in the Android Keystore on first start and registers its
public key at the first login, signing the session id (``sid``) of that login. The signature
proves the caller holds the private key, and binding it to the ``sid`` stops a captured
request from being replayed in another session.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key

from ..exceptions import DomainException
from ..models import Device, DeviceRegisterRequest
from . import queries
from .managers import conn_mgr

logger = logging.getLogger("backend.services.device_service")


def _b64(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except binascii.Error, ValueError:
        raise DomainException(status_code=400, detail="Invalid base64")


def verify_signature(public_key_b64: str, signature_b64: str, message: str) -> None:
    """400 unless ``signature`` is a valid ECDSA/SHA-256 signature over ``message`` by the P-256
    key in ``public_key`` (DER SubjectPublicKeyInfo)."""
    try:
        key = load_der_public_key(_b64(public_key_b64))
    except ValueError, TypeError:
        raise DomainException(status_code=400, detail="Invalid public key")
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise DomainException(status_code=400, detail="Public key must be EC P-256")
    try:
        key.verify(_b64(signature_b64), message.encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise DomainException(status_code=400, detail="Invalid device signature")


def verify_registration_proof(public_key_b64: str, signature_b64: str, sid: str) -> None:
    """The registration signature covers the session id."""
    verify_signature(public_key_b64, signature_b64, sid)


async def register(body: DeviceRegisterRequest, username: str, sid: str) -> Device:
    await asyncio.to_thread(verify_registration_proof, body.public_key, body.signature, sid)
    try:
        device = await asyncio.to_thread(
            queries.register_device,
            public_key=body.public_key,
            model=body.model,
            android_version=body.android_version,
            app_version_code=body.app_version_code,
            username=username,
            sid=sid,
        )
    except queries.DeviceRevoked:
        # W9: a password login on a revoked device must not stay valid. A v2 app always
        # registers after logging in, so its session ends within one request.
        await asyncio.to_thread(queries.revoke_session, sid)
        await conn_mgr.disconnect_session(sid)
        logger.warning(
            "device_register_revoked",
            extra={"event": "device.register.revoked", "username": username},
        )
        raise DomainException(status_code=403, detail="Device revoked")
    logger.info(
        "device_registered",
        extra={
            "event": "device.registered",
            "username": username,
            "device_id": device.id,
            "status": device.status,
        },
    )
    return device


async def set_status(device_id: str, status: str, admin: str) -> Device:
    """Approve or revoke a device for an admin (T8.1). Revoking ends every session bound to
    the device and closes their sockets; the workers' sessions on other devices stay."""
    try:
        device, changed, sids = await asyncio.to_thread(
            queries.set_device_status, device_id, status
        )
    except queries.DeviceNotFound:
        raise DomainException(status_code=404, detail="Device not found")
    except queries.DeviceStatusConflict as exc:
        raise DomainException(status_code=409, detail=f"Device is {exc.status}")
    for sid in sids:
        await conn_mgr.disconnect_session(sid)
    action = "approved" if status == "active" else "revoked"
    logger.info(
        f"device_{action}",
        extra={
            "event": f"device.{action}",
            "admin": admin,
            "device_id": device.id,
            "username": device.current_username,
            "changed": changed,
            "sessions_revoked": len(sids),
        },
    )
    return device
