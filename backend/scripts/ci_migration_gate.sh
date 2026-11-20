#!/usr/bin/env bash
# Migration gate (docs/TESTING.md release gate, IMPLEMENTATION_PLAN T3.3).
#   1. empty database -> head with the current code
#   2. previous release tag (v*) schema -> head with the current code
# Uses TEST_DATABASE_URL (a disposable *_test database). Never point it at real data.
set -euo pipefail

: "${TEST_DATABASE_URL:?TEST_DATABASE_URL must be set}"
case "$TEST_DATABASE_URL" in
  *_test) ;;
  *) echo "TEST_DATABASE_URL must name a *_test database" >&2; exit 2 ;;
esac

ROOT="$(git rev-parse --show-toplevel)"
export APP_ENV=development LOG_TO_FILE=false

reset_db() {
  (cd "$ROOT/backend" && uv run --quiet python - <<'PY'
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["TEST_DATABASE_URL"])
with engine.begin() as conn:
    for schema in ("alembic", "auth", "orders", "shopee", "warehouse"):
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
PY
  )
}

upgrade_head() {  # $1 = backend directory to run alembic from
  # -x url= wins over secret files in the current code; old release checkouts are fresh
  # worktrees without .secrets/, so their DATABASE_URL fallback is the test database too.
  (cd "$1" && DATABASE_URL="$TEST_DATABASE_URL" uv run --quiet alembic -x url="$TEST_DATABASE_URL" upgrade head)
}

echo "== empty -> head"
reset_db
upgrade_head "$ROOT/backend"

PREV_TAG="${PREV_TAG:-$(git -C "$ROOT" describe --tags --abbrev=0 --match 'v*' HEAD^ 2>/dev/null || true)}"
if [[ -z "$PREV_TAG" ]]; then
  echo "== no previous v* tag; skipping release -> head"
  exit 0
fi

echo "== $PREV_TAG -> head"
WORKTREE="$(mktemp -d)"
trap 'git -C "$ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true' EXIT
git -C "$ROOT" worktree add --detach "$WORKTREE" "$PREV_TAG" >/dev/null
reset_db
upgrade_head "$WORKTREE/backend"
upgrade_head "$ROOT/backend"
echo "== migration gate passed"
