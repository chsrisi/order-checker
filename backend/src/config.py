import os
import re
import logging
import tomllib
from pathlib import Path
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
    First checks for secrets:
      1. Explicit SECRETS_DIR if defined
      2. Docker Secret at /run/secrets/<key_lowercase>
      3. Local secrets in backend/.secrets/<key_lowercase> or ./.secrets/<key_lowercase>
    If not found, falls back to the environment variable or default.
    """
    val = None

    # 1. Try reading from docker secrets or local .secrets files first
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    secret_candidate_paths = [
        f"/run/secrets/{key.lower()}",
        os.path.join(backend_dir, ".secrets", key.lower()),
        os.path.join(os.getcwd(), ".secrets", key.lower()),
    ]
    secrets_dir = os.getenv("SECRETS_DIR")
    if secrets_dir:
        secret_candidate_paths.insert(0, os.path.join(secrets_dir, key.lower()))

    for secret_path in secret_candidate_paths:
        if os.path.isfile(secret_path):
            try:
                with open(secret_path, "r", encoding="utf-8") as f:
                    temp_val = f.read().strip()
                    if temp_val:
                        val = temp_val
                        logger.debug(f"Loaded config '{key}' from secret file at {secret_path}")
                        break
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
            db_host = os.getenv("DB_HOST", "backend-postgres-1")
            val = re.sub(
                r"@(localhost|127\.0\.0\.1|db|postgres-1|postgres_container)(:\d+)?",
                f"@{db_host}\\2",
                val,
            )
            if val != original:
                # Censor password in logs
                censored = re.sub(r":([^:@]+)@", r":****@", val)
                logger.info(
                    f"Resolved database URL host from localhost/127.0.0.1/db/postgres-1/postgres_container to '{db_host}' for Docker: {censored}"
                )

    return val


def get_config_int(key: str, default: int) -> int:
    val = get_config_value(key)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val.strip())
    except ValueError:
        logger.warning(
            f"Invalid integer for config '{key}': '{val}', falling back to default: {default}"
        )
        return default


def get_config_float(key: str, default: float) -> float:
    val = get_config_value(key)
    if val is None or val.strip() == "":
        return default
    try:
        return float(val.strip())
    except ValueError:
        logger.warning(
            f"Invalid float for config '{key}': '{val}', falling back to default: {default}"
        )
        return default


def get_config_bool(key: str, default: bool) -> bool:
    val = get_config_value(key)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


# ------------------------------------------------------------------------------
# Security, JWT & Token Configuration (token identity: see "Versions" below)
# ------------------------------------------------------------------------------
JWT_ALGORITHM: str = get_config_value("JWT_ALGORITHM", "RS256") or "RS256"
JWT_LEEWAY_SECONDS: float = get_config_float("JWT_LEEWAY_SECONDS", 30.0)
REFRESH_TTL_SECONDS: int = get_config_int("REFRESH_TTL_SECONDS", 86400)
REFRESH_CLEANUP_INTERVAL_SECONDS: int = get_config_int("REFRESH_CLEANUP_INTERVAL_SECONDS", 3600)


# ------------------------------------------------------------------------------
# Environment profile (docs/OPERATIONS.md "Environment profiles")
# ------------------------------------------------------------------------------
# Fail closed: an unset or unknown APP_ENV applies production rules. Local setups set
# APP_ENV=development explicitly (.env.example, compose.test.yaml).
APP_ENV_VALUES = ("development", "staging", "production")


def resolve_app_env(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in APP_ENV_VALUES:
        return value
    if value:
        logger.warning(f"Unknown APP_ENV {value!r}; applying production rules")
    return "production"


APP_ENV: str = resolve_app_env(get_config_value("APP_ENV"))
# Staging is production-like: same startup rules, but sandbox Shopee only.
PRODUCTION_RULES: bool = APP_ENV != "development"

ALLOW_REGISTRATION: bool = get_config_bool("ALLOW_REGISTRATION", not PRODUCTION_RULES)
EXPOSE_API_DOCS: bool = get_config_bool("EXPOSE_API_DOCS", not PRODUCTION_RULES)
RECIPIENT_RETENTION_DAYS: int = get_config_int("RECIPIENT_RETENTION_DAYS", 30)
RECIPIENT_RETENTION_MAX_DAYS: int = 90  # Shopee DPP maximum

# ------------------------------------------------------------------------------
# Stock location mode (docs/OPERATIONS.md "Stock Location Mode", delta A-8)
# ------------------------------------------------------------------------------
STOCK_LOCATION_MODES = ("multi", "single")


def strict_stock() -> bool:
    """``STOCK_STRICT``: reject picks larger than the recorded stock instead of logging a
    shortfall (V2_PICKING_DELTA R1.5). Evaluated on every call, off by default."""
    return get_config_bool("STOCK_STRICT", False)


_LEGACY_STOCK_MODE_FLAGS = ("SINGLE_LOCATION_STOCK_BYPASS", "STOCK_SINGLE_LOCATION_BYPASS")
_warned_legacy_stock_flags: set[str] = set()


def stock_location_mode() -> str:
    """``multi`` (default) or ``single``, evaluated on every call.

    ``STOCK_LOCATION_MODE`` wins. The legacy boolean flags are accepted as deprecated aliases
    (a truthy value means ``single``) and log a warning once per process.
    """
    raw = (get_config_value("STOCK_LOCATION_MODE") or "").strip().lower()
    if raw in STOCK_LOCATION_MODES:
        return raw
    if raw:
        logger.warning(f"Unknown STOCK_LOCATION_MODE {raw!r}; using 'multi'")
        return "multi"
    for flag in _LEGACY_STOCK_MODE_FLAGS:
        value = get_config_value(flag)
        if value is None or value.strip() == "":
            continue
        if flag not in _warned_legacy_stock_flags:
            _warned_legacy_stock_flags.add(flag)
            logger.warning(f"{flag} is deprecated; set STOCK_LOCATION_MODE=single|multi instead")
        return "single" if get_config_bool(flag, False) else "multi"
    return "multi"


# ------------------------------------------------------------------------------
# Versions (IMPLEMENTATION_PLAN T3.1, delta A-7)
# ------------------------------------------------------------------------------
# One SemVer for the backend: [project].version in backend/pyproject.toml.
# CLIENT_CONTRACT is the newest operator-client API major the backend serves (KNOWN_LIMITATIONS
# #8); it changes only with a client major and side-by-side routes. Since v0.6.0 the root routes
# are contract v1 (frozen) and /v2 is contract v2 (IMPLEMENTATION_PLAN T6.3).
CLIENT_CONTRACT = 2
CLIENT_CONTRACT_MIN = 1
CLIENT_CONTRACT_MAX = 2

# Directory holding the published operator-client APKs and latest.json (T6.5, V2_DELTA Q5).
CLIENT_RELEASES_DIR = get_config_value("CLIENT_RELEASES_DIR", "data/releases/client")


def read_project_version(pyproject: Path | None = None) -> str:
    path = pyproject or Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        with open(path, "rb") as f:
            return str(tomllib.load(f)["project"]["version"])
    except Exception as e:
        logger.warning(f"Could not read version from {path}: {e}")
        return "0.0.0+unknown"


PROJECT_VERSION: str = read_project_version()
_api_version_override = get_config_value("API_VERSION")
if _api_version_override and APP_ENV != "development":
    logger.warning("API_VERSION is ignored outside development; the version comes from pyproject")
    _api_version_override = None
API_VERSION: str = _api_version_override or PROJECT_VERSION

# Token identity is per environment, not per release: a dev token is never accepted by
# production, and upgrading the backend no longer logs everyone out. Explicit
# JWT_AUDIENCE / JWT_ISSUER still win. JWT_VERSION is deprecated and ignored.
if get_config_value("JWT_VERSION"):
    logger.warning(
        "JWT_VERSION is deprecated and ignored; iss/aud derive from APP_ENV "
        "(set JWT_AUDIENCE/JWT_ISSUER to override)"
    )
DEFAULT_JWT_AUDIENCE: str = f"api.bakingholic:{APP_ENV}"
DEFAULT_JWT_ISSUER: str = f"auth.bakingholic:{APP_ENV}"
JWT_AUDIENCE: str = get_config_value("JWT_AUDIENCE", DEFAULT_JWT_AUDIENCE) or DEFAULT_JWT_AUDIENCE
JWT_ISSUER: str = get_config_value("JWT_ISSUER", DEFAULT_JWT_ISSUER) or DEFAULT_JWT_ISSUER
