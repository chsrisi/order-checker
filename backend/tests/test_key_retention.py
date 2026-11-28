"""T1.2 / F-C2: retired signing keys outlive every token they signed."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

from src.services.managers.key_manager import KID_FORMAT, KeyManager

RETENTION = 86400 + 900 + 30


def _write_pair(keys_dir, kid, *, private=True):
    open(os.path.join(keys_dir, f"{kid}.pub"), "w").close()
    if private:
        open(os.path.join(keys_dir, f"{kid}.key"), "w").close()


def _kid(dt):
    return dt.strftime(KID_FORMAT)


def _manager(tmp_path):
    return KeyManager(keys_dir=str(tmp_path), cache_ttl=300, access_ttl=900, retention=RETENTION)


def _kids(tmp_path):
    return sorted({f[:-4] for f in os.listdir(tmp_path)})


def _age_initial_pair(mgr, tmp_path, days=2):
    """Rename the generated pair to an older kid so a new rotation gets a distinct kid."""
    current = mgr.get_active_signer().kid
    old_kid = _kid(datetime.now(UTC) - timedelta(days=days))
    for ext in (".pub", ".key"):
        os.rename(os.path.join(tmp_path, current + ext), os.path.join(tmp_path, old_kid + ext))
    mgr._refresh_keys_from_disk(force=True)
    return old_kid


def test_rotation_keeps_previous_key_published(tmp_path):
    mgr = _manager(tmp_path)
    old_kid = _age_initial_pair(mgr, tmp_path)
    mgr.rotate_keys_force()
    assert mgr.get_active_signer().kid != old_kid
    published = {k["kid"] for k in mgr.get_jwks(force=True)}
    assert old_kid in published  # a refresh token signed by old_kid still verifies
    assert mgr.get_public_key(old_kid) is not None


def test_retired_key_pruned_only_after_retention(tmp_path):
    mgr = _manager(tmp_path)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    old, new = _kid(base), _kid(base + timedelta(days=1))
    for f in os.listdir(tmp_path):
        os.remove(os.path.join(tmp_path, f))
    _write_pair(str(tmp_path), old)
    _write_pair(str(tmp_path), new)

    retired_at = base + timedelta(days=1)
    grace = timedelta(seconds=RETENTION + 300 + 30)
    mgr._refresh_keys_from_disk = lambda force=False: None  # empty placeholder files

    assert mgr._prune_expired_keys(now=retired_at + grace - timedelta(seconds=1)) == []
    assert _kids(tmp_path) == [old, new]
    assert mgr._prune_expired_keys(now=retired_at + grace + timedelta(seconds=1)) == [old]
    assert _kids(tmp_path) == [new]


def test_prune_never_touches_newest_pair_or_pending_rotation(tmp_path):
    mgr = _manager(tmp_path)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for f in os.listdir(tmp_path):
        os.remove(os.path.join(tmp_path, f))
    signer, pending = _kid(base), _kid(base + timedelta(days=1))
    _write_pair(str(tmp_path), signer)
    _write_pair(str(tmp_path), pending, private=False)  # step 1 of a rotation
    mgr._refresh_keys_from_disk = lambda force=False: None

    assert mgr._prune_expired_keys(now=base + timedelta(days=30)) == []
    assert _kids(tmp_path) == [signer, pending]


@pytest.mark.asyncio
async def test_cancel_mid_rotation_completes_pair_and_keeps_old_keys(tmp_path):
    mgr = _manager(tmp_path)
    mgr.cache_ttl = 3600  # park the task in the step-1 sleep
    old_kid = _age_initial_pair(mgr, tmp_path)  # older than a day: the task rotates
    task = asyncio.create_task(mgr.rotate_keys_task())
    def pending_pub():
        kid = mgr._new_kid
        return kid if kid and mgr._rkey and os.path.exists(tmp_path / f"{kid}.pub") else None

    for _ in range(250):
        await asyncio.sleep(0.02)
        if pending_pub():
            break
    new_kid = pending_pub()
    assert new_kid is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    files = set(os.listdir(tmp_path))
    assert {f"{old_kid}.pub", f"{old_kid}.key", f"{new_kid}.pub", f"{new_kid}.key"} <= files
