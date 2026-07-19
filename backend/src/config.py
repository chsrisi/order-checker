import os
import re
import logging
from typing import overload
from dotenv import load_dotenv, find_dotenv

# Automatically load environment variables from the nearest .env file
load_dotenv(find_dotenv())

logger = logging.getLogger("backend.config")


@overload
def get_config_value(key: str) -> str | None: ...
@overload
def get_config_value(key: str, default: str) -> str: ...


def get_config_value(key: str, default: str | None = None) -> str | None:
    """
    Retrieves a configuration value.
    First checks for a Docker Secret at /run/secrets/<key_lowercase>.
    If not found, falls back to the environment variable.
    """
    val = None

    # 1. Try reading from docker secrets first
    secret_path = f"/run/secrets/{key.lower()}"
    if os.path.exists(secret_path):
        try:
            with open(secret_path, "r") as f:
                temp_val = f.read().strip()
                if temp_val:
                    val = temp_val
                    logger.debug(f"Loaded config '{key}' from docker secret")
        except Exception as e:
            logger.warning(f"Failed to read secret {key} from {secret_path}: {e}")

    # 2. Fallback to environment variables or default
    if val is None:
        val = os.getenv(key)

    if val is None:
        val = default

    # 3. Dynamic adjustment for database URL inside Docker
    if val and key.upper() == "DATABASE_URL":
        if os.path.exists("/.dockerenv") or os.path.exists("/run/secrets"):
            original = val
            val = re.sub(r"@(localhost|127\.0\.0\.1)(:\d+)?", r"@db\2", val)
            if val != original:
                # Censor password in logs
                censored = re.sub(r":([^:@]+)@", r":****@", val)
                logger.info(
                    f"Resolved database URL host from localhost/127.0.0.1 to 'db' for Docker: {censored}"
                )

    return val
