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

from .config import get_config_value, get_config_bool, get_config_int


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
    """Configure console output (default WARNING) and an optional rotating file (default DEBUG)."""

    console_level_name = (
        get_config_value("LOG_LEVEL_CONSOLE")
        or get_config_value("LOG_LEVEL", "WARNING")
        or "WARNING"
    ).upper()
    console_level = getattr(logging, console_level_name, logging.WARNING)

    file_level_name = (get_config_value("LOG_LEVEL_FILE", "DEBUG") or "DEBUG").upper()
    file_level = getattr(logging, file_level_name, logging.DEBUG)

    log_format = (get_config_value("LOG_FORMAT", "json") or "json").lower()
    formatter: logging.Formatter
    if log_format == "text":
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"
        )
    else:
        formatter = JsonFormatter()

    context_filter = RequestContextFilter()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(context_filter)
    handlers: list[logging.Handler] = [console_handler]

    active_levels = [console_level]

    log_dir = get_config_value("LOG_DIR", "temp/logs") or "temp/logs"
    if get_config_bool("LOG_TO_FILE", True):
        max_bytes = get_config_int("LOG_MAX_BYTES", 10 * 1024 * 1024)
        backup_count = get_config_int("LOG_BACKUP_COUNT", 5)
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            Path(log_dir) / "backend.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        handlers.append(file_handler)
        active_levels.append(file_level)

    root = logging.getLogger()
    root.setLevel(min(active_levels))
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)


