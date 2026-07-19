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
src/main.py       Application lifecycle, middleware, and router assembly
src/models.py     SQLAlchemy entities and Pydantic schemas
src/routers/      HTTP and WebSocket transport
src/services/     Business workflows and external integration
src/services/queries/  PostgreSQL persistence functions
src/services/managers/ Process-level keys, cache, tickets, and sockets
alembic/          PostgreSQL migrations
compose.yaml      API, PostgreSQL, and Redis services
```

Architecture, routes, operations, testing, and review findings are indexed in
[docs/PROJECT.md](../docs/PROJECT.md).
