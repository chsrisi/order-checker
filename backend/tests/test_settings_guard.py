"""T2.1: production rules refuse unsafe configuration at startup."""

from dataclasses import replace

import pytest

from src.settings_guard import (
    GuardInputs,
    StartupConfigError,
    collect_violations,
    enforce_startup_rules,
)

SAFE_PROD = GuardInputs(
    app_env="production",
    admin_password="a-long-random-admin-password",
    cors_origins="",
    cors_origin_regex=None,
    mock_order_bypass=False,
    database_url="postgresql+psycopg://bh:pw@db:5432/bakingholic",
    redis_url="redis://:secret@redis:6379/0",
    allow_registration=False,
    retention_days=30,
)


def test_safe_production_config_is_accepted():
    assert collect_violations(SAFE_PROD) == []
    enforce_startup_rules(SAFE_PROD)


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"admin_password": "admin"}, "ADMIN_PASSWORD"),
        ({"admin_password": None}, "ADMIN_PASSWORD"),
        ({"admin_password": "replace-with-a-long-random-password"}, "ADMIN_PASSWORD"),
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://a.example, *"}, "CORS_ORIGINS"),
        ({"cors_origin_regex": ".*"}, "CORS_ORIGIN_REGEX"),
        ({"mock_order_bypass": True}, "MOCK_ORDER_BYPASS"),
        ({"database_url": None}, "DATABASE_URL"),
        ({"database_url": "sqlite:///./local.db"}, "DATABASE_URL"),
        ({"redis_url": "redis://redis:6379/0"}, "REDIS_URL"),
        ({"redis_url": None}, "REDIS_URL"),
        ({"allow_registration": True}, "ALLOW_REGISTRATION"),
        ({"retention_days": 91}, "RECIPIENT_RETENTION_DAYS"),
        ({"retention_days": 0}, "RECIPIENT_RETENTION_DAYS"),
    ],
)
@pytest.mark.parametrize("app_env", ["production", "staging"])
def test_each_rule_refuses_startup(change, fragment, app_env):
    cfg = replace(SAFE_PROD, app_env=app_env, **change)
    with pytest.raises(StartupConfigError, match=fragment):
        enforce_startup_rules(cfg)


def test_explicit_origin_list_is_allowed():
    assert collect_violations(replace(SAFE_PROD, cors_origins="https://admin.example")) == []


def test_all_violations_are_reported_together():
    cfg = replace(SAFE_PROD, admin_password="admin", mock_order_bypass=True)
    assert len(collect_violations(cfg)) == 2


def test_development_allows_local_defaults():
    dev = replace(
        SAFE_PROD,
        app_env="development",
        admin_password="admin",
        cors_origins="*",
        mock_order_bypass=True,
        database_url=None,
        redis_url="redis://localhost:6379/0",
        allow_registration=True,
        retention_days=365,
    )
    assert collect_violations(dev) == []


@pytest.mark.parametrize("raw", [None, "", "  ", "prod", "Live"])
def test_unset_or_unknown_app_env_means_production(raw):
    from src.config import resolve_app_env

    assert resolve_app_env(raw) == "production"


@pytest.mark.parametrize("raw", ["development", " Staging ", "PRODUCTION"])
def test_known_app_env_values_are_normalised(raw):
    from src.config import resolve_app_env

    assert resolve_app_env(raw) == raw.strip().lower()


LIVE = "https://partner.shopeemobile.com"
SANDBOX = "https://openplatform.sandbox.test-stable.shopee.sg"


@pytest.mark.parametrize("app_env", ["development", "staging"])
def test_live_shopee_refused_outside_production(app_env):
    cfg = replace(SAFE_PROD, app_env=app_env, shopee_url=LIVE)
    with pytest.raises(StartupConfigError, match="live Shopee"):
        enforce_startup_rules(cfg)
    enforce_startup_rules(replace(cfg, allow_live_shopee_in_nonprod=True))
    enforce_startup_rules(replace(cfg, shopee_url=SANDBOX))
    enforce_startup_rules(replace(cfg, shopee_url=None))


def test_live_shopee_allowed_in_production():
    enforce_startup_rules(replace(SAFE_PROD, shopee_url=LIVE))
