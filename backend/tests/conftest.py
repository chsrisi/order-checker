"""Shared test configuration.

Unit tests replace persistence and network boundaries with fakes. The production
database schema is PostgreSQL-specific, so full integration tests are a separate
Docker-backed layer described in docs/TESTING.md.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("LOG_TO_FILE", "false")
os.environ.setdefault("LOG_FORMAT", "text")
