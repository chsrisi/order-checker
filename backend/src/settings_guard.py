"""Startup rules per environment profile (IMPLEMENTATION_PLAN T2.1, delta A-2).

Under production rules (``APP_ENV`` = ``production`` or ``staging``, or unset) the server
refuses to start on a configuration that is only acceptable for local development. Every
violation is reported at once so an operator can fix them in one pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from . import config
from .config import get_config_bool, get_config_value

logger = logging.getLogger("backend.settings_guard")

PLACEHOLDER_ADMIN_PASSWORDS = {"", "admin", "replace-with-a-long-random-password"}


@dataclass(frozen=True)
class GuardInputs:
    app_env: str
    admin_password: Optional[str]
    cors_origins: Optional[str]
    cors_origin_regex: Optional[str]
    mock_order_bypass: bool
    database_url: Optional[str]
    redis_url: Optional[str]
    allow_registration: bool
    retention_days: int
    shopee_url: Optional[str] = None
    allow_live_shopee_in_nonprod: bool = False

    @property
    def production_rules(self) -> bool:
        return self.app_env != "development"


def load_inputs() -> GuardInputs:
    return GuardInputs(
        app_env=config.APP_ENV,
        admin_password=get_config_value("ADMIN_PASSWORD"),
        cors_origins=get_config_value("CORS_ORIGINS"),
        cors_origin_regex=get_config_value("CORS_ORIGIN_REGEX"),
        mock_order_bypass=get_config_bool("MOCK_ORDER_BYPASS", False),
        database_url=get_config_value("DATABASE_URL"),
        redis_url=get_config_value("REDIS_URL"),
        allow_registration=config.ALLOW_REGISTRATION,
        retention_days=config.RECIPIENT_RETENTION_DAYS,
        shopee_url=get_config_value("SHOPEE_URL"),
        allow_live_shopee_in_nonprod=get_config_bool("ALLOW_LIVE_SHOPEE_IN_NONPROD", False),
    )


def _redis_has_credentials(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.password)


def is_live_shopee_host(url: Optional[str]) -> bool:
    """Any Shopee host that is not the sandbox counts as live (A-10: ToS and DPP)."""
    host = (urlparse(url).hostname or "").lower() if url else ""
    return "shopee" in host and "sandbox" not in host and "test-stable" not in host


def collect_violations(cfg: GuardInputs) -> list[str]:
    problems: list[str] = []
    if cfg.retention_days < 1:
        problems.append("RECIPIENT_RETENTION_DAYS must be at least 1")

    if (
        cfg.app_env != "production"
        and is_live_shopee_host(cfg.shopee_url)
        and not cfg.allow_live_shopee_in_nonprod
    ):
        problems.append(
            "SHOPEE_URL points at live Shopee outside production; use the sandbox, or set "
            "ALLOW_LIVE_SHOPEE_IN_NONPROD=1 deliberately"
        )

    if not cfg.production_rules:
        return problems

    if (cfg.admin_password or "").strip() in PLACEHOLDER_ADMIN_PASSWORDS:
        problems.append("ADMIN_PASSWORD is empty or a default/placeholder value")
    origins = [o.strip() for o in (cfg.cors_origins or "").split(",") if o.strip()]
    if "*" in origins:
        problems.append("CORS_ORIGINS='*' is not allowed; leave it empty or list exact origins")
    if cfg.cors_origin_regex:
        problems.append("CORS_ORIGIN_REGEX is not allowed; list exact origins in CORS_ORIGINS")
    if cfg.mock_order_bypass:
        problems.append("MOCK_ORDER_BYPASS must be off")
    if not cfg.database_url or cfg.database_url.startswith("sqlite"):
        problems.append("DATABASE_URL must point at PostgreSQL (no SQLite fallback)")
    if not cfg.redis_url or not _redis_has_credentials(cfg.redis_url):
        problems.append("REDIS_URL must include a password (redis://:<password>@host:6379/0)")
    if cfg.allow_registration:
        problems.append("ALLOW_REGISTRATION must be off; create operators via the admin app")
    if cfg.retention_days > config.RECIPIENT_RETENTION_MAX_DAYS:
        problems.append(
            f"RECIPIENT_RETENTION_DAYS may not exceed {config.RECIPIENT_RETENTION_MAX_DAYS}"
        )
    return problems


class StartupConfigError(RuntimeError):
    pass


def enforce_startup_rules(cfg: Optional[GuardInputs] = None) -> None:
    cfg = cfg or load_inputs()
    problems = collect_violations(cfg)
    if problems:
        message = f"Refusing to start (APP_ENV={cfg.app_env}):\n- " + "\n- ".join(problems)
        logger.critical(message, extra={"event": "startup.config_rejected"})
        raise StartupConfigError(message)
    logger.info(
        "startup_config_accepted",
        extra={"event": "startup.config_accepted", "app_env": cfg.app_env},
    )
