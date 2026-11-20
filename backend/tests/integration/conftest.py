"""PostgreSQL integration layer (docs/TESTING.md, IMPLEMENTATION_PLAN T0.3).

Runs only when ``TEST_DATABASE_URL`` points at a **disposable** local database whose name ends
in ``_test``. The schema is built from an empty database with ``alembic upgrade head`` (never
``create_all``), so migrations are exercised on every run.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]
APP_SCHEMAS = ("auth", "orders", "shopee", "warehouse")
ALL_SCHEMAS = ("alembic", *APP_SCHEMAS)
SAFE_HOSTS = {"localhost", "127.0.0.1", "postgres", "test-postgres"}


def pytest_collection_modifyitems(items):
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


def _test_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; PostgreSQL integration tests skipped")
    parsed = make_url(url)
    if not (parsed.database or "").endswith("_test") or parsed.host not in SAFE_HOSTS:
        pytest.fail(
            "TEST_DATABASE_URL must be a local disposable database named *_test "
            f"(got host={parsed.host!r}, database={parsed.database!r})"
        )
    return url


def alembic_config(url: str):
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


def reset_schemas(engine) -> None:
    with engine.begin() as conn:
        for schema in ALL_SCHEMAS:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))


@pytest.fixture(scope="session")
def pg_url() -> str:
    return _test_url()


@pytest.fixture(scope="session")
def pg_engine(pg_url):
    from alembic import command

    engine = create_engine(pg_url)
    reset_schemas(engine)
    command.upgrade(alembic_config(pg_url), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine, monkeypatch):
    """Empty tables, and route every ``get_db()`` in the app to the test database."""
    from src.services.queries import engine as engine_module

    with pg_engine.begin() as conn:
        tables = conn.execute(
            text("SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY(:schemas)"),
            {"schemas": list(APP_SCHEMAS)},
        ).all()
        if tables:
            names = ", ".join(f'"{s}"."{t}"' for s, t in tables)
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))

    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "SessionLocal", factory)
    return factory
