"""Application logging configuration and request-scoped context.

Logs are JSON by default so container runtimes can index individual fields. Set
``LOG_FORMAT=text`` for readable local output and ``LOG_LEVEL`` to control
verbosity. Authentication tokens and passwords must never be passed as fields.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestContextFilter(logging.Filter):
    """Attach the current request ID to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


class JsonFormatter(logging.Formatter):
    """Serialize standard log attributes and safe structured extras as JSON."""

    _reserved = set(logging.makeLogRecord({}).__dict__) | {
        "message",
        "asctime",
        "request_id",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in self._reserved and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging() -> None:
    """Configure console output and an optional rotating file exactly once."""

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = os.getenv("LOG_FORMAT", "json").lower()
    formatter: logging.Formatter
    if log_format == "text":
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"
        )
    else:
        formatter = JsonFormatter()

    context_filter = RequestContextFilter()
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    log_dir = os.getenv("LOG_DIR", "temp/logs")
    if os.getenv("LOG_TO_FILE", "true").lower() in {"1", "true", "yes"}:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                Path(log_dir) / "backend.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
            )
        )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    for handler in handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        root.addHandler(handler)
