# Testing

## Test layers

The backend suite focuses on fast deterministic unit and contract tests:

- Pydantic boundary validation and safe mutable defaults.
- JWT type/claim behavior, login scope, and refresh rotation.
- Domain-service error translation and WebSocket notification side effects.
- Cache and one-use ticket manager behavior, including Redis failure handling.
- Structured logging fields and exception output.
- Generated OpenAPI completeness, security declarations, and regression routes.

PostgreSQL behavior (row locks, `RETURNING`, schema-qualified migrations, unique
indexes) is covered by the **integration layer** in `backend/tests/integration/`.
SQLite is not an integration substitute because the models use multiple PostgreSQL
schemas.

### PostgreSQL integration layer

- Runs only when `TEST_DATABASE_URL` is set. Otherwise those tests are skipped, so the
  fast loop needs no database.
- The URL must point at a **local, disposable** database whose name ends in `_test`;
  anything else fails the run. The URL is passed to Alembic explicitly, so a test run
  never falls back to a secret file or to `DATABASE_URL`.
- The schema is always built from an empty database with `alembic upgrade head`. The
  suite also checks the full downgrade/upgrade round trip, and that the models match the
  migrated schema (no autogenerate drift).
- Each test starts from truncated tables (`pg_session_factory` fixture), and every
  `get_db()` in the app is routed to the test database.

The Docker test stack starts a throwaway `test-postgres` service automatically. For a
host-side loop, any container engine works:

```bash
podman run -d --rm --name oc-test-pg -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=bakingholic_test -p 127.0.0.1:55432:5432 docker.io/library/postgres:18.4-alpine
cd backend && TEST_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:55432/bakingholic_test \
  uv run python -m pytest -m integration
podman stop oc-test-pg
```

The release migration smoke test must start with an empty PostgreSQL volume and
run `alembic upgrade head`; testing only an already-upgraded developer database
can hide schema qualification and migration ordering defects.

## Commands

The canonical backend run uses Docker and needs no host Python environment:

```bash
cd backend
docker compose -f compose.yaml -f compose.test.yaml run --build --rm tests
```

For a faster host-side loop (using `uv` or Python 3.14):

```bash
cd backend
uv run python -m pytest
```

When running `pytest` directly on the host, use `python -m pytest` or `uv run python -m pytest` to ensure `PYTHONPATH` includes `backend` so imports from `src` resolve properly.

Coverage is branch-aware and enforces the baseline configured in `pyproject.toml` (minimum 55%). Key test areas include:
- Barcode resolution pipeline (`_first_token`, `_sku_candidate`, `_supplier_barcode`, `resolve_barcode_to_item`).
- Marketplace BOM tree quantity scaling (`qty` parameter).
- Shopee order detail and package tracking list chunking.
- Auth JWT rotation, admin requirements, and domain exception handling.

To inspect HTML coverage:

```bash
uv run python -m pytest --cov-report=html
```

Flutter checks run separately:

```bash
cd frontend/client && flutter analyze && flutter test
cd frontend/admin && flutter analyze && flutter test
```

## Test conventions

- Name tests after observable behavior, not implementation methods.
- Replace PostgreSQL, Redis, Shopee, and WebSocket boundaries with fakes in unit
  tests; never call live Shopee endpoints.
- Add a regression test with every bug fix.
- Assert status and stable response shape at router boundaries.
- Never place real credentials, order numbers, labels, or customer data in fixtures.

Ruff currently enforces syntax/name correctness and deterministic formatting.
Modern typing/import rules are intentionally not enabled until the inherited
cleanup can be reviewed as a separate mechanical change.

## Release gate

Before release, run Python compilation, Ruff, backend tests with coverage, both
Flutter analyzers/tests, Compose validation, migrations against a disposable
PostgreSQL database, and a manual login/sync/claim/pick/scan/close smoke flow.

## Synthetic data

Tests and local development use invented data only (delta A-10: Shopee ToS and DPP). The
tracked seed `backend/scripts/seed_dev/` (see `docs/OPERATIONS.md`) is covered by
`tests/integration/test_seed_dev_pg.py`, so it stays in step with the schema. Never copy
production rows into fixtures.

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests and pushes to `dev` and `master`:

| Job | What it checks |
|---|---|
| `backend` | Ruff, `requirements.txt` in sync with `uv.lock` (`--no-dev`), the full pytest suite (unit + contract v1 + PostgreSQL integration) |
| `migrations` | `backend/scripts/ci_migration_gate.sh`: empty → head, and previous `v*` tag → head |
| `flutter (client/admin)` | `flutter analyze` and `flutter test` (with `.env` copied from `.env.example`) |

Run the migration gate locally against a disposable database:

```bash
TEST_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:55432/bakingholic_test \
  backend/scripts/ci_migration_gate.sh          # PREV_TAG=<ref> to test another base
```

Making these checks *required* and protecting `dev`/`master` are GitHub repository settings
(maintainer task).
