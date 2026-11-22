"""Publish an operator-app APK for over-the-air updates (IMPLEMENTATION_PLAN T6.5).

    cd backend && uv run python -m scripts.publish_client_release app-release.apk \\
        --version-code 2 --version-name 2.0.1 [--min-supported 2] [--notes "..."] --confirm

Copies the APK to ``<CLIENT_RELEASES_DIR>/orderchecker-<versionCode>.apk`` and rewrites
``latest.json`` atomically. The versionCode must be higher than the published one (Android
refuses downgrades; a rollback is a new, higher versionCode built from older code).
``--min-supported`` defaults to the previous value. Without ``--confirm`` it only prints what
it would do. Verify the signature first: ``apksigner verify --print-certs app-release.apk``
(RELEASE.md "Operator app releases").
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

LATEST_FILE = "latest.json"


def apk_name(version_code: int) -> str:
    return f"orderchecker-{version_code}.apk"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_latest(releases: Path) -> dict | None:
    path = releases / LATEST_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".latest.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def publish(
    apk: Path,
    version_code: int,
    version_name: str,
    releases: Path,
    min_supported: int | None = None,
    notes: str | None = None,
    confirm: bool = False,
) -> dict:
    """Validate, then (with ``confirm``) copy the APK and write ``latest.json``.
    Returns the new metadata. Raises ``SystemExit`` with a message on invalid input."""
    if not apk.is_file():
        raise SystemExit(f"APK not found: {apk}")
    if version_code < 1:
        raise SystemExit("--version-code must be >= 1")
    current = _read_latest(releases)
    if current and version_code <= int(current["version_code"]):
        raise SystemExit(
            f"versionCode {version_code} is not higher than the published {current['version_code']}"
        )
    if min_supported is None and current:
        min_supported = current.get("min_supported_version_code")
    if min_supported is not None and not 1 <= min_supported <= version_code:
        raise SystemExit("--min-supported must be between 1 and --version-code")

    metadata = {
        "version_code": version_code,
        "version_name": version_name,
        "apk_file": apk_name(version_code),
        "sha256": sha256_of(apk),
        "size_bytes": apk.stat().st_size,
        "min_supported_version_code": min_supported,
        "notes": notes,
        "published_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if not confirm:
        return metadata
    releases.mkdir(parents=True, exist_ok=True)
    target = releases / metadata["apk_file"]
    tmp_target = target.with_suffix(".apk.tmp")
    shutil.copyfile(apk, tmp_target)
    os.chmod(tmp_target, 0o644)
    if sha256_of(tmp_target) != metadata["sha256"]:
        tmp_target.unlink()
        raise SystemExit("copy verification failed; nothing published")
    os.replace(tmp_target, target)
    # latest.json last: devices never see metadata for a file that is not there yet.
    _write_atomic(releases / LATEST_FILE, json.dumps(metadata, indent=2) + "\n")
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("apk", type=Path)
    parser.add_argument("--version-code", type=int, required=True)
    parser.add_argument("--version-name", required=True)
    parser.add_argument("--min-supported", type=int)
    parser.add_argument("--notes")
    parser.add_argument(
        "--dir",
        type=Path,
        help="releases directory (default: CLIENT_RELEASES_DIR, i.e. data/releases/client)",
    )
    parser.add_argument("--confirm", action="store_true", help="publish (otherwise dry run)")
    args = parser.parse_args(argv)
    releases = args.dir
    if releases is None:
        from src.services.client_releases import releases_dir

        releases = releases_dir()
    metadata = publish(
        args.apk,
        args.version_code,
        args.version_name,
        releases,
        min_supported=args.min_supported,
        notes=args.notes,
        confirm=args.confirm,
    )
    print(json.dumps(metadata, indent=2))
    if not args.confirm:
        print("dry run; re-run with --confirm to publish", file=sys.stderr)
        return 2
    print(f"published to {releases}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
