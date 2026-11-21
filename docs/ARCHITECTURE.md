# Architecture

## System context

```text
Operator Flutter app ----\
                         +-- HTTP/WebSocket --> FastAPI --> PostgreSQL
Admin Flutter app -------/                         |------> Redis
                                                   `------> Shopee OpenAPI
```

Order Checker is a modular monolith. One deployable API owns authentication,
warehouse state, order synchronization, and real-time fan-out. PostgreSQL is the
system of record. Redis stores renewable Shopee credentials and short-lived
security tickets; the in-process Shopee cache only suppresses redundant upstream
requests.

## Backend layers

```text
src/main.py
  -> routers/       HTTP/WebSocket transport, validation, response mapping
  -> services/      business workflows and domain-error translation
  -> services/queries/  transaction-scoped SQLAlchemy persistence
  -> services/managers/ long-lived key, ticket, cache, token, and socket state
  -> models.py      SQLAlchemy entities and Pydantic API models
```

Routers must not open database sessions or call Shopee directly. Services
coordinate work and notifications. Query functions own short database
transactions and return detached records. Managers are process-level stateful
objects; this matters when scaling horizontally.

**Sync persistence, async transport.** SQLAlchemy sessions and Argon2 are synchronous.
They must never run on the event loop:

- sync routes and dependencies (`get_current_user`, `require_admin`) are plain `def`, so
  FastAPI runs them in its threadpool
- async services call queries through `asyncio.to_thread`
- `ConnectionManager` builds WebSocket payloads in a thread

A new `async def` that touches the database must follow the same rule. This is guarded by
`tests/test_event_loop.py`.

## Frontends

Both Flutter apps use `Provider` and a central `AppState` for authentication,
HTTP calls, cached view state, and WebSocket reconnection.

Supported platforms: the operator client runs on **Android and Windows** (no web build).
The admin app runs on the **web**, served by nginx (`frontend/admin/nginx.conf.template`).
The admin Windows build was dropped, as was the client web build (delta D2.1).

- The client app handles order claiming, picking, scanning, item lookup, and stock
  adjustment/transfer.
- The admin app handles users, order/scan history, period closure, CSV exports,
  inventory, BOM inspection, and protected Shopee-token management.

Access/refresh tokens are stored with `flutter_secure_storage`. Each app verifies
access-token signatures against the backend JWKS and refreshes JWKS after a failed
verification to tolerate key rotation.

## Core flows

### Authentication

1. Login checks an Argon2 password hash in PostgreSQL.
2. The key manager signs a 15-minute access token and a 24-hour refresh token.
3. Only the refresh-token JTI is persisted.
4. Refresh deletes the old JTI before issuing a replacement pair.
5. Signing keys rotate daily: publish new public key, switch signer after the JWKS
   cache interval, retain the old key until every token it signed has expired (refresh TTL +
   access TTL + leeway by default), then prune it.

### Shopee synchronization

1. A request checks the two-minute process-local cache and obtains an async lock.
2. The service requests order numbers per Shopee status with bounded concurrency.
3. Order details are fetched in chunks of at most `SHOPEE_ORDER_CHUNK_SIZE` (50) orders. Package
   tracking numbers are fetched in chunks of `SHOPEE_PACKAGE_CHUNK_SIZE` (50) packages.
4. Orders that are still open locally but older than the list window are fetched too, so
   cancellations and shipments reach the database.
5. A transaction inserts or updates orders, packages, addresses and items. Existing orders get
   their ship-by, items and carrier refreshed. Buyer data past retention is never written
   back. If any chunk failed, the rest is stored, the sync is not marked complete, and the
   request answers 502.
6. WebSocket updates are sent to administrators and the requesting operator.

The cache and lock are per API process. Multiple workers can therefore perform
parallel upstream synchronizations; distributed locking is a future scaling task.

### Fulfillment and item resolution

Marketplace or standard BOM mappings expand sold items into warehouse components, supporting quantity scaling (`qty`) across root and child nodes.
Item lookups utilize a barcode resolution pipeline (`resolve_barcode_to_item`):
1. Extract the first line/token from the scanned barcode string.
2. Check if the part before any `*` matches a standard SKU candidate (`[a-zA-Z]\d{2}_\d{3}`, e.g., `A01_001`).
3. Normalize supplier barcodes (`prefix:value:suffix` → `value`; dashed forms reduced to their
   trailing groups) and match `supplier_barcode`.
4. Fall back to exact SKU matching in the warehouse items database.

All matches are case-insensitive and exact. Exact normalization rules: SYSTEM_REFERENCE §7.4.

An operator atomically claims an unassigned order, builds pick entries, assigns
quantities, and scans the outbound label. Period closure deduplicates submitted
labels, closes open scans, and marks matching orders complete by order or tracking
number.

### Inventory

Stock is stored per SKU/location, with at most one row per pair (unlocated included). One
engine (`queries/stocks.py`) serves both `STOCK_LOCATION_MODE`s. The mode only selects a
`LocationPolicy`:

- the target bin for set/add
- whether other bins merge into it (`single`)
- the transfer source
- the deduction order
- the restore target

Updates support `set`, `add`, or a transfer to `move_to`; a transfer never makes the source
negative.

A pick locks the item's stock rows (`ORDER BY sku, location FOR UPDATE`) and deducts bin by
bin. It writes one allocation per bin and a structured `stocks_log` row per change. A
shortfall never blocks the pick. Assign and unassign move allocations, oldest first, without
touching stock. A delete returns the allocations to stock. Each operation is one transaction,
and `stocks_update` / `pick_item_entries_update` are broadcast after the commit. Rules and log
reasons: OPERATIONS "Inventory".

Synchronizing the active mode to client frontends is scheduled under the future **Sync
Milestone**, alongside Over-The-Air (OTA) updates.

## Data ownership

| PostgreSQL schema | Important entities |
| --- | --- |
| `auth` | users, refresh tokens |
| `orders` | outbound scans/tags, pick entries/logs |
| `shopee` | orders, packages, recipients, sold items |
| `warehouse` | items, stock, stock logs, standard/marketplace BOMs |
| `alembic` | migration version |

Redis keys use these namespaces:

- `shopee:access_token`, `shopee:refresh_token`, `shopee:current_ip`
- `ws_token:<random>` for one-use 30-second WebSocket tickets
- `cfg_token:<random>` for two-minute admin configuration sessions
- `login_fail:<username>` failed-login counters (15-minute window)

## Scaling and failure model

- PostgreSQL and Redis are required for production; the SQLite fallback cannot
  represent the multi-schema model.
- WebSocket connections, cache validity, and the sync lock live in one process.
  Sticky sessions or a Redis pub/sub fan-out are required before adding workers.
- A Redis failure blocks new WebSocket/configuration tickets but normal bearer
  HTTP requests remain usable.
- A Shopee failure should leave the last synchronized database snapshot readable.
- RSA key files under `data/keys` must be on persistent storage; replacing them
  invalidates every outstanding token.

## Dependency direction

Allowed imports flow from routers to services to queries/models. Query modules
must not import routers, and domain services should not depend on Flutter-specific
payloads. Circular imports currently avoided through narrow local imports should
be removed as services mature.
