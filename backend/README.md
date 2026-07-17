# Bakingholic backend

FastAPI service for authentication, Shopee order synchronization, BOM expansion,
outbound validation, pick lists, inventory, exports, and WebSocket updates.

## Run

Configure the environment and secret files described in the
[repository README](../README.md), then:

```bash
docker compose up --build
```

The container applies Alembic migrations and serves the API on port `8000`.
Interactive API documentation is available at `/docs` and `/redoc`.

## Layout

```text
src/main.py       API, auth, sync, and WebSocket flows
src/models.py     SQLAlchemy entities and Pydantic schemas
src/keys.py       RS256 signing-key lifecycle and JWKS
src/cache.py      Shopee sync cache/lock state
src/redis_client.py  Shopee token persistence
alembic/          PostgreSQL migrations
compose.yaml      API, PostgreSQL, and Redis services
```

Architecture, route groups, configuration, and known gaps are documented in
[docs/PROJECT.md](../docs/PROJECT.md).
