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

## Frontends

Both Flutter apps use `Provider` and a central `AppState` for authentication,
HTTP calls, cached view state, and WebSocket reconnection.

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
   cache interval, retain the old key for the access-token lifetime, then prune it.

### Shopee synchronization

1. A request checks the two-minute process-local cache and obtains an async lock.
2. The service requests order numbers per Shopee status with bounded concurrency.
3. Details and tracking numbers are fetched in chunks of at most 50 orders.
4. A transaction inserts/updates orders, packages, addresses, and items.
5. WebSocket updates are sent to administrators and the requesting operator.

The cache and lock are per API process. Multiple workers can therefore perform
parallel upstream synchronizations; distributed locking is a future scaling task.

### Fulfillment

Marketplace or standard BOM mappings expand sold items into warehouse components.
An operator atomically claims an unassigned order, builds pick entries, assigns
quantities, and scans the outbound label. Period closure deduplicates submitted
labels, closes open scans, and marks matching orders complete by order or tracking
number.

### Inventory

Stock is stored per SKU/location. Updates support `set`, `add`, or a transfer to
`move_to`. Transfers reject missing/insufficient source stock so the source cannot
become negative. Every mutation adds a stock audit-log row and broadcasts the new
inventory snapshot.

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
