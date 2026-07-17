# Project documentation

## Architecture

```text
Flutter client/admin
  |-- HTTPS + bearer JWT --> FastAPI --> PostgreSQL
  |-- WS + one-use ticket ->    |-----> Redis
                                `-----> Shopee OpenAPI
```

The backend is currently a modular monolith: routes, authentication, Shopee sync,
and WebSocket orchestration live mainly in `backend/src/main.py`. SQLAlchemy models
and Pydantic DTOs are in `models.py`; `keys.py` rotates RSA signing keys;
`cache.py` coordinates the two-minute in-process Shopee cache; `redis_client.py`
stores Shopee tokens and short-lived configuration sessions.

PostgreSQL is split into `auth`, `orders`, `shopee`, `warehouse`, and `alembic`
schemas. The Docker entrypoint applies Alembic migrations before starting Uvicorn.

### Applications

| Component | Main responsibilities |
| --- | --- |
| Client | Register/login, claim orders, pick/assign items, outbound scan, find items, adjust or move stock |
| Admin | Users, active/history orders, close scans, exports, inventory, Shopee credentials, BOM viewer |
| Backend | Auth, validation, persistence, Shopee synchronization, BOM expansion, real-time broadcasts |

## Authentication and real-time updates

Client users register through `/auth/register`; the configured admin is seeded at
backend startup. Login returns a 15-minute RS256 access token and a rotating
24-hour refresh token. Send the access token as `Authorization: Bearer <token>`.

For WebSockets, call `POST /auth/ws-token`, then connect to
`WS_URL/ws?token=<ticket>` within 30 seconds. Supported commands are `get_users`
(admin only), `get_items`, `get_shopee_orders`, and `get_stocks`. Messages use:

```json
{"type": "shopee_orders_update", "data": []}
```

Other event types are `users_update`, `outbound_update`,
`pick_item_entries_update`, `stocks_update`, and `error`.

## API map

FastAPI exposes the full request/response schemas at `/docs` and `/redoc`. Except
for register, login, admin login, refresh/logout, and JWKS, business routes require
a bearer access token. `/admin/*` routes additionally check the `admin` scope.

| Area | Routes |
| --- | --- |
| Auth | `POST /auth/register`, `/auth/login`, `/auth/admin`, `/auth/logout`, `/auth/refresh`, `/auth/ws-token`; `GET /.well-known/jwks.json` |
| Users/history | `GET, DELETE /admin/users`; `GET /admin/history/outbound`, `/admin/history/shopee/orders` |
| Export | `GET /admin/export/scans`, `/admin/export/stocks` |
| Outbound | `GET, POST /outbound`; `POST /outbound/close` |
| Items/stock | `GET /items/find?query=`; `POST /stocks` |
| Shopee | `GET /shopee/orders?refresh=`; `POST /shopee/orders/acquire?order_sn=`, `/shopee/reset-cache-state` |
| Pick list | `GET, POST, DELETE /pick-item`; `POST /pick-item/assign`, `/pick-item/unassign` |
| BOM | `GET /admin/bom/headers`, `/admin/bom/tree` |
| Shopee config | `POST /admin/shopee-config/unlock`, `/lock`; `GET, POST /admin/shopee-config` |

Common request bodies:

```json
// POST /outbound
{"content": "scanned-label", "tags": ["optional"]}

// POST /pick-item
{"sku": "SKU-1", "qty": 2, "order_sn": null}

// POST /stocks
{"sku": "SKU-1", "stock": 5, "mode": "add", "location": "A1", "move_to": null}
```

## Core workflows

### Order fulfillment

1. `GET /shopee/orders` syncs eligible Shopee orders; `refresh=true` invalidates
   the short-lived local cache.
2. A client claims an order with `/shopee/orders/acquire`.
3. Marketplace SKUs are expanded into warehouse components using BOM mappings.
4. The operator creates picks and assigns quantities to the claimed order.
5. Outbound labels are scanned; duplicate and carrier checks run server-side.
6. An admin closes a batch, archives scans, and marks matching orders complete.

### Shopee credentials

Shopee partner metadata comes from backend configuration. Access/refresh tokens
live in Redis. To view or update them, an admin re-enters their password to receive
a two-minute configuration token, uses it on `/admin/shopee-config`, then locks the
session or lets it expire.

## Configuration

The backend reads Docker secrets from `/run/secrets/<lowercase-name>` first, then
environment variables. Required production values are:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy PostgreSQL URL; Compose rewrites a localhost host to `db` |
| `REDIS_URL` | Redis connection; Compose supplies `redis://redis:6379/0` |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Startup-seeded admin account |
| `PARTNER_ID`, `PARTNER_KEY`, `SHOP_ID`, `SHOPEE_URL` | Shopee OpenAPI credentials and host |
| `ACCESS_TOKEN`, `REFRESH_TOKEN` | Optional initial Redis token seed |

Both Flutter apps require `BASE_URL` and `WS_URL` in their local `.env`. Use HTTPS
and WSS outside local development. Backend logs go to stdout and
`backend/temp/logs/backend.log`; signing keys are generated under
`backend/data/keys`.

## Migrations and maintenance

Run migration commands from `backend/` with `DATABASE_URL` available:

```bash
alembic current
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

The default SQLite URL in the code is only a fallback; the mapped schema design is
PostgreSQL-oriented, so PostgreSQL is the supported development path. Back up the
database, Redis token data, and RSA key directory for a recoverable deployment.

## Known gaps

- The admin app calls legacy `/admin/clear/outbound_items` and
  `/admin/export/outbound` paths; the backend currently exposes no clear route and
  uses `/admin/export/scans` for scan export.
- Backend behavior has no automated test suite. Each Flutter app has one basic
  login-screen widget test.
- CORS currently allows every origin while also enabling credentials; restrict it
  before exposing the API publicly.
- `main.py` combines several domains and is the main maintainability bottleneck;
  routers/services are the natural next refactor boundary.
