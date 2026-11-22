"""Device registration proof (IMPLEMENTATION_PLAN T6.6, P-12)."""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from src.exceptions import DomainException
from src.services import device_service


def keypair(curve=None):
    key = ec.generate_private_key(curve or ec.SECP256R1())
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return key, base64.b64encode(spki).decode()


def sign(key, sid: str) -> str:
    return base64.b64encode(key.sign(sid.encode(), ec.ECDSA(hashes.SHA256()))).decode()


def test_valid_signature_over_the_sid_passes():
    key, pub = keypair()
    device_service.verify_registration_proof(pub, sign(key, "sid-1"), "sid-1")


@pytest.mark.parametrize(
    "case",
    ["other_sid", "other_key", "garbage_sig", "not_base64", "bad_key", "p384", "rsa"],
)
def test_invalid_proofs_are_400(case):
    key, pub = keypair()
    sig = sign(key, "sid-1")
    if case == "other_sid":
        sig = sign(key, "sid-2")
    elif case == "other_key":
        sig = sign(keypair()[0], "sid-1")
    elif case == "garbage_sig":
        sig = base64.b64encode(b"\x30\x06\x02\x01\x01\x02\x01\x01").decode()
    elif case == "not_base64":
        sig = "***"
    elif case == "bad_key":
        pub = base64.b64encode(b"not a key").decode()
    elif case == "p384":
        key, pub = keypair(ec.SECP384R1())
        sig = sign(key, "sid-1")
    elif case == "rsa":
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = base64.b64encode(
            rsa_key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        ).decode()
    with pytest.raises(DomainException) as exc:
        device_service.verify_registration_proof(pub, sig, "sid-1")
    assert exc.value.status_code == 400
