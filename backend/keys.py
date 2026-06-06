import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from Crypto.PublicKey import RSA

logger = logging.getLogger("backend.keys")

KEYS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "keys")
CACHE_TTL_SECONDS = 300  # 5 minutes
ACCESS_TTL_SECONDS = 900


def ensure_keys_exist(keys_dir: str) -> bool:
    """Ensures at least one complete RSA key pair exists in the keys directory."""
    if not os.path.exists(keys_dir):
        os.makedirs(keys_dir)
        logger.info("Keys dir not found, creating one")
        return False

    files = os.listdir(keys_dir)
    pub_files = {f[:-4] for f in files if f.endswith(".pub")}
    key_files = {f[:-4] for f in files if f.endswith(".key")}

    # Match pairs
    if pub_files.intersection(key_files):
        logger.debug("Valid key pair already exists")
        return True

    logger.warning("No complete key pairs found")
    return False


@dataclass
class Signer:
    kid: str
    private_key: str


class KeyManager:
    def __init__(
        self,
        keys_dir: str = KEYS_DIR,
        cache_ttl: int = CACHE_TTL_SECONDS,
        access_ttl: int = ACCESS_TTL_SECONDS,
    ):
        self.keys_dir = keys_dir
        self._jwks_cache: list[dict[str, Any]] = []
        self._active_signer: dict[str, str] = {}
        self._last_refresh = 0.0
        self.cache_ttl = cache_ttl
        self.access_ttl = access_ttl

        self._rotating: bool = False
        self._rkey: Optional[RSA.RsaKey] = None
        self._new_kid: Optional[str] = None

        if not ensure_keys_exist(self.keys_dir):
            self._create_new_pub()
            self._create_new_signer()

        # Populate in-memory state immediately on startup
        self._refresh_keys_from_disk(force=True)

    def _refresh_keys_from_disk(self, force: bool = False):
        """Scans the directory, builds the JWKS, and identifies the newest key pair."""
        now = time.time()
        if not force and now - self._last_refresh < self.cache_ttl and self._jwks_cache:
            return

        try:
            files = os.listdir(self.keys_dir)
        except OSError as e:
            logger.error(f"Failed to read keys directory: {e}")
            return

        pub_kids = {f[:-4] for f in files if f.endswith(".pub")}
        priv_kids = {f[:-4] for f in files if f.endswith(".key")}

        # Complete key pairs sorted chronologically (newest first)
        valid_pairs = sorted(list(pub_kids.intersection(priv_kids)), reverse=True)

        if not valid_pairs:
            raise RuntimeError(
                f"No valid key pairs found in directory: {self.keys_dir}"
            )

        public_keys: list[dict[str, Any]] = []
        # Display all available public keys to the JWKS endpoint
        for kid in sorted(list(pub_kids), reverse=True):
            pub_path = os.path.join(self.keys_dir, f"{kid}.pub")
            try:
                with open(pub_path, "r") as f:
                    pub_pem = f.read()
                key = RSA.import_key(pub_pem)
                jwk_dict = {
                    "kty": "RSA",
                    "use": "sig",
                    "kid": kid,
                    "alg": "RS256",
                    "n": self.to_base64url_uint(key.n),
                    "e": self.to_base64url_uint(key.e),
                }
                public_keys.append(jwk_dict)
            except Exception as e:
                logger.error(f"Skipping broken public key {kid}: {e}")
                continue

        # Active signer becomes the newest complete pair
        active_kid = valid_pairs[0]
        priv_path = os.path.join(self.keys_dir, f"{active_kid}.key")

        with open(priv_path, "r") as f:
            active_priv_pem = f.read()

        self._jwks_cache = public_keys
        self._active_signer = {"kid": active_kid, "private_key": active_priv_pem}
        self._last_refresh = now

    def _create_new_pub(self):
        logger.info("Generating new RSA key pair components...")
        self._rotating = True
        # YYYYMMDD_HHMMSS ensures collision resistance and perfect alphabetical sorting
        self._new_kid = datetime.now().strftime("key_%Y%m%d_%H%M%S")
        self._rkey = RSA.generate(2048)

        pub_path = os.path.join(self.keys_dir, f"{self._new_kid}.pub")
        with open(pub_path, "wb") as f:
            f.write(self._rkey.publickey().export_key("PEM"))
        logger.info(f"Added new .pub file with KID: {self._new_kid}")

    def _create_new_signer(self):
        if not self._rkey or not self._new_kid:
            raise RuntimeError("No active rotation context found")
        priv_path = os.path.join(self.keys_dir, f"{self._new_kid}.key")
        with open(priv_path, "wb") as f:
            f.write(self._rkey.export_key("PEM"))
        logger.info(f"Added new .key file with KID: {self._new_kid}")

    def _remove_old_keys(self):
        if not self._new_kid:
            raise RuntimeError("No active rotation context found")

        for f in os.listdir(self.keys_dir):
            # Fixed operator precedence flaw via explicit parentheses
            if (
                (f.endswith(".key") or f.endswith(".pub"))
                and f != f"{self._new_kid}.key"
                and f != f"{self._new_kid}.pub"
            ):
                try:
                    os.remove(os.path.join(self.keys_dir, f))
                except OSError as e:
                    logger.error(f"Failed to delete old key file {f}: {e}")

        logger.info("Removed old historical .pub and .key pairs")
        self._refresh_keys_from_disk(force=True)
        self._rkey = None
        self._new_kid = None
        self._rotating = False

    def rotate_keys_force(self):
        self._create_new_pub()
        self._create_new_signer()
        self._remove_old_keys()

    async def rotate_keys_task(self):
        """Background task to gracefully rotate RSA keys every 24 hours without blocking the event loop."""
        try:
            while True:
                current_kid = self._active_signer.get("kid")
                if current_kid is None:
                    # Fallback verification if state isn't initialized
                    await asyncio.to_thread(self._refresh_keys_from_disk, force=True)
                    current_kid = self._active_signer.get("kid")
                if not current_kid:
                    # this case should never happen
                    raise RuntimeError("Current kid is none")

                dt = datetime.strptime(current_kid, "key_%Y%m%d_%H%M%S")
                if not dt < datetime.now() - timedelta(days=1):
                    await asyncio.sleep(3600)
                    continue

                # Step 1: Add new public key to disk, allowing clients to cache it via JWKS
                await asyncio.to_thread(self._create_new_pub)
                await asyncio.to_thread(self._refresh_keys_from_disk, force=True)
                await asyncio.sleep(self.cache_ttl + 30)

                # Step 2: Write private key and switch signing immediately
                await asyncio.to_thread(self._create_new_signer)
                await asyncio.to_thread(self._refresh_keys_from_disk, force=True)
                await asyncio.sleep(self.access_ttl + 30)

                # Step 3: Remove old pairs safely
                await asyncio.to_thread(self._remove_old_keys)
                logger.info("Keys rotation lifecycle completed successfully")
        except asyncio.CancelledError:
            logger.info("Key rotation background task cancelled.")
            if self._rkey is not None and self._new_kid is not None:
                logger.info("Committing partial key rotation before cancel...")
                priv_path = os.path.join(self.keys_dir, f"{self._new_kid}.key")
                if not os.path.exists(priv_path):
                    self._create_new_signer()
                self._remove_old_keys()
                logger.info("Partial key rotation committed successfully.")
            raise

    def get_jwks(self, *, force: bool = False) -> list[dict[str, Any]]:
        self._refresh_keys_from_disk(force)
        return self._jwks_cache

    def get_public_key(self, kid: str) -> Optional[dict[str, Any]]:
        jwks = self.get_jwks()
        for key in jwks:
            if key.get("kid") == kid:
                return key
        jwks = self.get_jwks(force=True)
        for key in jwks:
            if key.get("kid") == kid:
                return key
        return None

    def get_active_signer(self) -> Signer:
        self._refresh_keys_from_disk()
        return Signer(
            kid=self._active_signer["kid"],
            private_key=self._active_signer["private_key"],
        )

    @staticmethod
    def to_base64url_uint(val: int) -> str:
        bytes_val = val.to_bytes((val.bit_length() + 7) // 8, byteorder="big")
        return base64.urlsafe_b64encode(bytes_val).rstrip(b"=").decode("utf-8")
