# Testing

## Test layers

The backend suite focuses on fast deterministic unit and contract tests:

- Pydantic boundary validation and safe mutable defaults.
- JWT type/claim behavior, login scope, and refresh rotation.
- Domain-service error translation and WebSocket notification side effects.
- Cache and one-use ticket manager behavior, including Redis failure handling.
- Structured logging fields and exception output.
- Generated OpenAPI completeness, security declarations, and regression routes.

PostgreSQL query behavior should additionally be exercised against the Compose
database before releases. SQLite is not an integration substitute because the
models use multiple PostgreSQL schemas.

The release migration smoke test must start with an empty PostgreSQL volume and
run `alembic upgrade head`; testing only an already-upgraded developer database
can hide schema qualification and migration ordering defects.

## Commands

The canonical backend run uses Docker and needs no host Python environment:

```bash
cd backend
docker compose -f compose.yaml -f compose.test.yaml run --build --rm tests
```

For a faster host-side loop after installing Python 3.14:

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest
```

Coverage is branch-aware and enforces the baseline configured in `pyproject.toml`. Raise it as query-level
integration coverage grows. To inspect HTML coverage:

```bash
.venv/bin/pytest --cov-report=html
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
