"""Published operator-client releases (IMPLEMENTATION_PLAN T6.3/T6.5, V2_DELTA Q5).

``<CLIENT_RELEASES_DIR>/latest.json`` describes the newest APK; it is written atomically by
``scripts.publish_client_release``. The file is re-read only when its modification time
changes, so the version gate costs one ``stat`` per request.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from .. import config

logger = logging.getLogger("backend.services.client_releases")

LATEST_FILE = "latest.json"

_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "value": None}


def releases_dir() -> Path:
    return Path(config.CLIENT_RELEASES_DIR or "data/releases/client")


def apk_name(version_code: int) -> str:
    return f"orderchecker-{version_code}.apk"


def latest() -> dict[str, Any] | None:
    """The published ``latest.json`` as a dict, or ``None`` when nothing is published (or the
    file is unreadable, which is logged)."""
    path = releases_dir() / LATEST_FILE
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _lock:
        if _cache["key"] == key:
            return _cache["value"]
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or not isinstance(value.get("version_code"), int):
                raise ValueError("latest.json has no integer version_code")
        except (OSError, ValueError) as exc:
            logger.error("client_release_metadata_invalid", extra={"error": str(exc)})
            value = None
        _cache["key"], _cache["value"] = key, value
        return value


def min_supported_version_code() -> int | None:
    release = latest()
    if not release:
        return None
    value = release.get("min_supported_version_code")
    return value if isinstance(value, int) else None
