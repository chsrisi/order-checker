# System reference

State as of **2026-11-22**, branch `feat/v2-step6` (on top of `v0.5.0`): backend `0.6.0`
(`backend/pyproject.toml`), operator client contracts **v1** (root, frozen) and **v2** (`/v2`,
§10A), Alembic head `e5b8f3a1c2d4`.

This file describes what the code does now, precisely enough to reason about behaviour
without reading the source. It complements the other guides and does not repeat them:

| Topic | Authoritative place |
|---|---|
| HTTP endpoint list, error codes, size limits, datetime format | [API.md](API.md) and `/openapi.json` |
| Configuration keys, deployment, secrets, logging, backups | [OPERATIONS.md](OPERATIONS.md), `backend/.env.example` |
| Layering rules, high-level flows | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Test layers and commands | [TESTING.md](TESTING.md) |
| Release / maintenance window | [RELEASE.md](RELEASE.md) |
| Policies, known limitations | [../KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md) |
| Task plan and tracker (T3.5, T3.6 still open) | [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |
| Reviews and decision logs (history, not maintained) | [archive/](archive/README.md) |

When this file and the code disagree, the code wins; fix this file in the same change.
IDs such as `F-M8`, `A-10b`, `D4.3`, `T4.5` in code comments refer to the archived reviews
and the implementation plan.

---

## 1. Glossary

| Term | Meaning in this codebase |
|---|---|
| **Operator / client** | A user with `scope = "client"`, using the Flutter operator app (`frontend/client`) on Android or Windows. |
| **Admin** | A user with `scope = "admin"`, using the Flutter admin web app (`frontend/admin`). Exactly the users created by the startup seed (`ADMIN_USERNAME`); the API never creates other admins. |
| **Order** | A Shopee order, key `order_sn` (string, starts with `YYMMDD`). Table `shopee.orders`. |
| **Package / info** | One Shopee package of an order (`shopee.order_info`). A split order (`split_up = true`) has several. Carries tracking number, pickup code, logistics status and buyer note. |
| **Active order** | `done = false` AND `status IN (READY_TO_SHIP, PROCESSED, RETRY_SHIP)` (`queries/orders.py: active_orders_query`). Only active orders appear in order lists. There is no ship-by cutoff (V2_ORDERS_DELTA F4): a late order stays active until the sync sees it leave those statuses. |
| **Claim / acquire** | Setting `shopee.orders.owner_user` to an operator. Atomic; see §7.2. |
| **Pick entry (PIE)** | Row in `orders.pick_item_entries`: "user U picked `qty` of resolved SKU S, optionally for order O". One row per `(sku, order_sn, owner_user)` by construction (not by constraint). `order_sn = NULL` means a *general* (unassigned) pick. |
| **Allocation** | Row in `orders.pick_stock_allocations`: which bin a pick's deducted stock came from. Sum of allocations ≤ entry qty; the difference is a *shortfall*. |
| **Bin / location** | `warehouse.stocks.location` (free text, may be `NULL` = "unlocated"). At most one row per `(sku, coalesce(location, ''))`. |
| **Outbound scan** | Row in `orders.outbound_items`: a scanned shipping label (`content`), with tags. *Open* until closed by period closure. |
| **Period closure** | Admin action `POST /outbound/close` with the list of label values physically handed over; closes matching scans and completes matching orders. |
| **Standard BOM** | `warehouse.bom_headers` (+ `bom_details`): an internal SKU made of component SKUs. Recursive. |
| **Marketplace BOM** | `warehouse.bom_headers_marketplace` (+ `bom_details_marketplace`): a Shopee listing (`shopee_id` = Shopee `model_id` or `item_id`) made of internal SKUs. Rendered with the pseudo-SKU `MP:<shopee_id>`. |
| **Location mode** | `STOCK_LOCATION_MODE` = `multi` (default) or `single`; selects a `LocationPolicy` (§7.6). |
| **Contract v1** | The frozen API surface the shipped operator client depends on (§10, KNOWN_LIMITATIONS #8). |

---

## 2. Repository map

```text
backend/
  src/main.py                 app factory, lifespan, request-ID/log middleware, CORS, router wiring
  src/config.py               config lookup (secret files → env → default), APP_ENV, versions, JWT iss/aud,
                              stock_location_mode()
  src/settings_guard.py       startup rules per APP_ENV (refuses unsafe production settings)
  src/logging_config.py       JSON/text logging, request_id context, rotating file handler
  src/exceptions.py           DomainException(status, detail) → {"detail": ...}
  src/dependencies.py         re-exports get_current_user / require_admin
  src/models.py               SQLAlchemy entities, Pydantic request/response models, Shopee API models,
                              UTCDateTime type, request size limits
  src/routers/                HTTP/WS transport only (no sessions, no Shopee calls)
    auth.py                   /auth/* and /.well-known/jwks.json (public_router)
    admin.py                  /admin/users*, /admin/history/*, /admin/export/*, /admin/clear/*;
                              mounts bom.py (/admin/bom/*) and admin_shopee.py (/admin/shopee-config*)
    outbound.py  items.py  stocks.py  shopee.py  pick_items.py  meta.py  websocket.py
  src/services/               workflows: error translation + WS notifications after commit
    auth_service.py           tokens, login (+throttle), refresh rotation, user admin
    shopee_service.py         Shopee signing/transport/retry/circuit, sync orchestration, acquire
    order_payload.py          batched order → response builder (BOM expansion)
    outbound_service.py  pick_item_service.py  stock_service.py  bom_service.py
    retention_service.py      daily recipient-data purge
    redis_service.py          async Redis wrapper (lazy connect from REDIS_URL)
    queries/                  one short transaction per public function, returns detached rows
      engine.py               engine + get_db() (SQLite fallback only when DATABASE_URL is missing)
      users.py orders.py outbound.py pick_items.py stocks.py warehouse.py bom.py csv_export.py
    managers/                 process-level singletons (see §3)
      key_manager.py ticket_manager.py connection_manager.py shopee_token_manager.py
      shopee_cache_manager.py login_throttle.py
  alembic/versions/           8 migrations (§4.3)
  scripts/                    maintenance CLIs (§11)
  tests/                      unit/contract tests; tests/integration/ = PostgreSQL layer
  compose.yaml / compose.prod.yaml / compose.test.yaml, Dockerfile(.test), init-scripts/init.sql
frontend/client/              operator app: lib/{main,app_state,models}.dart, lib/screens/*
frontend/admin/               admin web app: lib/{main,app_state,models,safe_storage*}.dart, lib/views/*,
                              nginx.conf.template, docker-entrypoint.sh
.github/workflows/ci.yml      backend lint+tests, migration gate, flutter analyze/test per app
```

---

## 3. Runtime model

**One process owns everything.** Uvicorn runs one worker. The following state is per process
and is lost on restart; running several workers would split it (see §14):

| Singleton (`services/managers/__init__.py`) | State |
|---|---|
| `conn_mgr: ConnectionManager` | open WebSockets per username, scope per socket |
| `cache_mgr: ShopeeOrderCacheManager` | last successful sync time (TTL `SHOPEE_CACHE_TTL_SECONDS`, 120), sync `asyncio.Lock`, Shopee token circuit flag |
| `key_mgr: KeyManager` | JWKS cache (refresh from disk every `KEY_CACHE_TTL_SECONDS`, 300), active signer, rotation context |
| `ticket_mgr`, `token_mgr`, `login_throttle` | stateless wrappers over Redis |
| `shopee_service.TOKEN_REFRESH_LOCK`, `SHOPEE_SEMAPHORE` (`SHOPEE_MAX_CONCURRENCY`, 5) | Shopee call coordination |

**Startup (`main.lifespan`), in order:**

1. `enforce_startup_rules()`: under production rules, refuses to start on any violation
   (list in OPERATIONS "Environment Profiles").
2. Background tasks: key rotation (`key_mgr.rotate_keys_task`), refresh-token cleanup
   (every `REFRESH_CLEANUP_INTERVAL_SECONDS`, 3600; deletes expired rows), recipient retention
   (at startup, then every `RECIPIENT_RETENTION_INTERVAL_SECONDS`, 86400).
3. One shared `aiohttp.ClientSession` for Shopee.
4. Admin seed: creates `ADMIN_USERNAME` (default `admin`) with `ADMIN_PASSWORD` **only if
   missing**. Changing the secret later needs `python -m scripts.set_admin_password`.

Migrations are not run by the app; the container command runs `alembic upgrade head` first.

**Per HTTP request (`main.log_requests`):** `X-Request-ID` is taken from the request (first
128 chars) or generated, bound to a context var used by every log line, and echoed on the
response. Logs `request_started` / `request_completed` (status, duration) or
`request_failed`.

**Threading rule.** SQLAlchemy and Argon2 are synchronous. Sync routes/dependencies are plain
`def` (threadpool); async services call queries via `asyncio.to_thread`; WS payloads are built
in a thread. Guarded by `tests/test_event_loop.py`.

**Unit of work.** Each public `queries.*` function opens its own session (`get_db()`,
`expire_on_commit=False`) and commits once. Services publish WebSocket events only after it
returns. Functions in `queries/stocks.py` that take `db` never commit.

---

## 4. Data model

PostgreSQL, five schemas. Timestamps are `timestamptz` and every connection runs in
UTC (`queries/engine.py`); the API serializes them as `...Z` (`models.UTCDateTime`). Exception:
the imported dates on `warehouse.items`, the marketplace BOM tables and `shopee_items` are naive,
zone unknown, and unused. `src/timezone.py` holds the business clock: one fixed
`BUSINESS_UTC_OFFSET` (default +07:00) for History days, the auto-sync pause and exports. Column types: `str` = `VARCHAR`, `float` = double precision.

### 4.1 Tables

**`auth.users`**: `username` PK; `password_hash` (Argon2 via passlib); `scope` (`"admin"` |
`"client"`; plain string, no enum or constraint).

**`auth.sessions`** (T6.2): one row per login. `id` PK (= the `sid` token claim);
`username` FK → users (indexed); `created_at`; `expires_at` (indexed; extended to the newest
refresh token's expiry on every rotation); `last_seen_at` (written at most once per 60 s);
`revoked_at` nullable (set on logout, password reset, "log out everywhere"); `ip_address`,
`agent` (from the login request, agent ≤ 256 chars). Live = `revoked_at IS NULL`. Deleted by
the refresh-cleanup task once `expires_at` passed, and with the user.

**`auth.devices`** (T6.6): `id` PK (uuid hex); `public_key` UNIQUE (base64 DER SPKI, P-256);
`status` `pending`|`active`|`revoked` (CHECK); `label`, `model`, `android_version`,
`app_version_code`; `token_hash` (unused until step 8); `current_username` FK → users
`ON DELETE SET NULL` (the SQL word `current_user` is reserved); `enrolled_at`, `last_seen_at`.
`auth.sessions.device_id` FK → devices `ON DELETE SET NULL` (indexed, NULL for v1 and admin).

**`auth.refresh_tokens`**: `jti` PK; `username` FK → users; `session_id` FK → sessions
`ON DELETE CASCADE` (indexed); `created_at`; `expires_at` (indexed); `revoked_at` nullable
(never set: revocation deletes rows); `ip_address`, `agent` nullable (never written; the
session holds them).

**`shopee.orders`**: `order_sn` PK; `split_up` bool; `ship_by` (from Shopee `ship_by_date`;
column was `created_at` before migration `bcc1283662c5`); `owner_user` FK → users, nullable
(claim); `status` (Shopee order status string); `shipping_carrier` nullable (carrier of the
first package); `done` bool default false; `done_at` nullable.

**`shopee.order_info`** (one row per package): `id` PK; `order_sn` FK; `package_number`;
`logistics_status`; `tracking_number` (indexed); `pickup_code`; `note` (buyer note, copied to
every package row; cleared by retention).

**`shopee.order_recipient_address`**: `id` PK; `order_sn` FK; `name`; `city`. One row per
order at most (relationship is scalar). Deleted by retention.

**`shopee.order_item_list`**: `id` PK; `order_sn` FK; `item_id`, `model_id` (bigint; `model_id`
is stored `NULL` when Shopee sends `0`); `item_name`, `item_sku`, `model_name`, `model_sku`;
`model_quantity_purchased`; `image_url`. Replaced wholesale on every sync of the order.

**`orders.outbound_items`**: `id` PK; `content` (indexed, stripped scan text); `created_at`;
`owner_user` FK; `closed` default false; `closed_at`.

**`orders.tags`**: `id` PK; `outbound_id` FK → outbound_items `ON DELETE CASCADE`; `content`.
Exposed as `OutboundItem.tags: list[str]` (association proxy, eager-joined).

**`orders.pick_item_entries`**: `id` PK; `sku` (indexed; always a resolved warehouse SKU);
`qty`; `order_sn` FK → shopee.orders, nullable; `timestamp` (bumped on every change);
`owner_user` FK.

**`orders.pick_stock_allocations`**: `id` PK; `pick_entry_id` FK → pick_item_entries
`ON DELETE CASCADE` (indexed); `sku`; `location` nullable; `qty`; `created_at`.

**`warehouse.items`**: `sku` PK plus ~60 descriptive columns imported from the ERP (names,
prices, dimensions, packing, flags). Columns the code reads: `sku`, `item_name`,
`supplier_barcode` (barcode pipeline), `note` (BOM headers). `location` is **not** a column:
it is a Python property joining the item's distinct non-null bin names with `", "`.

**`warehouse.stocks`**: `id` PK; `sku` FK → items; `stock` int; `location` nullable. Unique
index `uq_stocks_sku_location` on `(sku, coalesce(location, ''))`. Rows never hold 0: a row
reaching 0 is deleted.

**`warehouse.stocks_log`**: `id`; `message` (legacy free text, still written); `timestamp`;
structured since T4.3: `sku` (indexed), `location`, `delta`, `before`, `after`, `reason`,
`actor`, `ref_type`, `ref_id`. Reasons: `adjust_set`, `adjust_add`, `transfer_out`,
`transfer_in`, `pick`, `pick_shortfall`, `pick_restore`, `mode_merge`, `cutover_clear`,
`migration_merge` (meanings: OPERATIONS "Stock audit log").

**`warehouse.bom_headers`**: `id` PK; `sku` FK → items, unique; `quantity_standard`,
`factor_f5` (not used by expansion).
**`warehouse.bom_details`**: `id`; `bom_header_id` FK; `component_sku` FK → items;
`quantity_standard` NOT NULL (multiplier per parent unit); `is_not_primary_child`.
**`warehouse.bom_headers_marketplace`**: `shopee_id` bigint PK; `item_name`, `model_name`;
`quantity_standard` (listing multiplier, `NULL` → 1); `marketplace`; `created_date`.
**`warehouse.bom_details_marketplace`**: `id`; `shopee_id` FK; `component_sku` FK → items;
`quantity_standard` (`NULL` → 1); `is_not_primary_child`; `created_date`.
**`warehouse.shopee_items`**: listing → SKU mapping with price factors. **Not read by any
code path** (reference data).

BOM, item and ERP tables are populated outside this application (no API writes them).

### 4.2 Relationships that matter

- Deleting an order is never done by the app. Deleting a user (§7.8) unassigns its orders.
- `ShopeeOrder.info` is a list ordered by `order_info.id` (creation order).
- `WarehouseItem.stocks` loads with `selectin`, so `item.location` is available on detached
  rows.

### 4.3 Migration chain

| Revision | Change |
|---|---|
| `e09271f5005e` | initial schema (auth, orders, shopee, warehouse) |
| `bcc1283662c5` | `shopee.orders.created_at` → `ship_by` |
| `e2d7906a02ff` | indexes on `outbound_items.content`, `order_info.tracking_number` |
| `aa5a426a95ff` | `shopee.orders.shipping_carrier` |
| `9383471fa90d` | `outbound_items.tag` column → `orders.tags` table |
| `4e6ef916e20d` | BOM tables, `shopee_items`, ERP columns on `warehouse.items` |
| `d862d86e8707` | `bom_details.quantity_standard` NOT NULL; `items.barcode_supplier` → `supplier_barcode` |
| `b7c4e1a9d2f3` | `pick_stock_allocations`, structured `stocks_log` columns, duplicate-bin merge (`migration_merge`), unique `uq_stocks_sku_location` |
| `c3f8a2d5e6b1` | drops the never-used `orders.pick_item_entries_log` (downgrade recreates it empty) |
| `d4a7e2c9b1f0` | `auth.sessions`, `refresh_tokens.session_id`; deletes pre-session refresh tokens (one relogin) |
| `e5b8f3a1c2d4` | `auth.devices`, `sessions.device_id` (additive) |

Integration tests build the schema from empty with `alembic upgrade head`, check the full
down/up round trip and assert no autogenerate drift. CI's migration gate upgrades from the
previous release tag.

### 4.4 Redis keys (complete)

| Key | Value | TTL | Written by |
|---|---|---|---|
| `shopee:access_token`, `shopee:refresh_token` | Shopee tokens | none | admin config save, token refresh; seeded on first read from `SHOPEE_ACCESS_TOKEN` / `ACCESS_TOKEN` (and `..._REFRESH_TOKEN`) config |
| `shopee:current_ip` | egress IP Shopee reported as undeclared | none | `shopee_request` on `source_ip_undeclared` |
| `ws_token:<urlsafe32>` | JSON `{username, sid}` | `WS_TICKET_TTL_SECONDS` (30) | `POST /auth/ws-token`; consumed with `GETDEL` |
| `cfg_token:<hex64>` | admin username | `SHOPEE_CONFIG_UNLOCK_TTL_SECONDS` (120) | `POST /admin/shopee-config/unlock` |
| `login_fail:<lowercased username>` | failure count | `LOGIN_LOCKOUT_SECONDS` (900), reset to a full window at the locking failure | failed logins |

Redis needs ≥ 6.2 (`GETDEL`). Compose ships `redis:8.8-alpine`.

---

## 5. Authentication and sessions

**Tokens.** RS256 JWTs signed by `key_mgr` with header `kid`. Claims: `sub` (username),
`sid` (session id), `type` (`access` | `refresh`), `jti` (random hex), `iat`, `nbf`, `exp`,
`aud`, `iss`.
`aud`/`iss` default to `api.bakingholic:<APP_ENV>` / `auth.bakingholic:<APP_ENV>`
(overridable with `JWT_AUDIENCE`/`JWT_ISSUER`); a token from another environment is rejected.
Verification requires all claims, checks `type`, allows `JWT_LEEWAY_SECONDS` (30) of skew.
Access TTL `ACCESS_TTL_SECONDS` (900); refresh TTL `REFRESH_TTL_SECONDS` (86400). Scope is
**not** in the token: every request loads the user row **joined with its live session**
(`queries.get_user_for_session`, one query), so a scope change, a user deletion or a revoked
session applies to the very next HTTP request (401). Endpoints that need the session use the
`get_current_principal` dependency (`Principal(user, sid)`).

**Sessions** (`auth.sessions`, T6.2). Login and registration start one; refresh rotation stays
in it (a refresh token whose session is gone, revoked or different fails with 401). Ending a
session revokes it and deletes its refresh tokens in one transaction, then closes its sockets
(1008): logout ends that session only (`ConnectionManager.disconnect_session`); password reset,
`POST /admin/users/{username}/logout` and user deletion end all of the user's sessions.
`scripts.set_admin_password` revokes the admin's sessions. v1 clients see a 401, fail their one
refresh and return to the login screen.

**Login** (`/auth/login` any scope, `/auth/admin` admin only). Username `^[a-zA-Z0-9_]+$`,
1–64 chars; password 1–256. Unknown users still pay one Argon2 verify (timing). Wrong scope,
unknown user and wrong password all return 401 "Incorrect username or password". Throttle:
`LOGIN_MAX_FAILURES` (10) failed attempts per lowercased username within the window → 429
with `Retry-After`; success resets; Redis down → throttle fails open.

**Refresh.** `consume_refresh_token` deletes the row by `jti` with `RETURNING` (single use even
under races), then checks expiry, the session (same `sid`, still live) and user existence, and
issues a new pair in that session. Logout ends the whole session (400 if the token does not
verify; see **Sessions**).

**Key rotation** (`key_manager.py`, files `<KEYS_DIR>/key_YYYYmmdd_HHMMSS.{pub,key}`,
default `data/keys`):

1. Hourly check; when the active key is older than 24 h, write the new `.pub` only and
   reload, so JWKS publishes it.
2. Wait `KEY_CACHE_TTL_SECONDS + 30` s, write the `.key`; the newest complete pair now signs.
3. A key is deleted once its successor is older than
   `KEY_RETENTION_SECONDS` (default refresh TTL + access TTL + leeway) + cache TTL + 30 s.
   The newest complete pair is never pruned. Cancellation mid-rotation completes the pair.

Verification looks the `kid` up in the cached JWKS, then forces a disk reload once before
failing. Both apps cache JWKS client-side for 15 min and force-refresh after a failed
verification. Replacing `data/keys` invalidates every token (forced relogin).

**WebSocket ticket.** `POST /auth/ws-token` (bearer) stores a one-use ticket in Redis with the
caller's username and `sid` (503 if Redis fails). `WS /ws?token=<ticket>` consumes it with
`GETDEL`, loads the user for that live session, and accepts; a missing/used/expired ticket, a
pre-session ticket or a revoked session is rejected **before accept** with HTTP 403 (contract
v1 relies on this). The socket remembers its `sid` so it can be closed with its session.

**Shopee config session.** `POST /admin/shopee-config/unlock {password}` re-verifies the
admin's password (401 otherwise) and returns `{token, expires_in: 120}`. `GET`/`POST
/admin/shopee-config` and `POST .../lock` require header `X-Config-Token` whose Redis value
equals the calling admin's username (401 otherwise). `GET` returns both Shopee tokens and
`current_ip`. `POST` stores both tokens, clears the circuit flag and invalidates the sync
cache.

---

## 6. Authorization matrix

| Capability | Operator | Admin |
|---|---|---|
| List active orders (HTTP and WS) | **only orders it claimed** | all active orders |
| Claim an order | yes | yes (same rules) |
| Pick entries: list | own | all |
| Pick entries: create/assign/unassign | own, only for orders it claimed | same rule (admin must own the order too) |
| Pick entries: delete | own | any |
| Outbound scans: list (open) | own | all open |
| Outbound: create scan | yes | yes |
| Outbound: close period, clear all, history, exports | – | yes |
| Stocks: read, adjust, transfer | yes | yes |
| Item search | yes | yes |
| Users, BOM, Shopee config, sync reset | – | yes |
| WS `get_users` | error frame "Forbidden" | yes |

`require_admin` returns 403 "Not authorized" for operators.

---

## 7. Domain behaviour

### 7.1 Shopee synchronization (`shopee_service.sync_shopee_orders`)

Triggered by `GET /shopee/orders[?refresh=true]` (operator and admin), and by the background
`auto_sync_task` every `SHOPEE_AUTO_SYNC_SECONDS` (default 300, 0 = off; V2_ORDERS_DELTA Q48),
which runs as admin with no requesting user, skips while the token circuit is open and in the nightly
`SHOPEE_AUTO_SYNC_PAUSE` (default 21:00-06:00 business time, start included, end excluded; other
syncs still run then), and logs a failed run without stopping. Not triggered by the WebSocket `get_shopee_orders` command, which
only reads the database.

1. `refresh=true` invalidates the cache. If the cache is still valid (last full sync < 120 s
   ago) the database is read and returned; no WS broadcast.
2. Otherwise take `cache_mgr.lock` (re-check validity inside).
3. For each status in `READY_TO_SHIP, PROCESSED, SHIPPED, COMPLETED, CANCELLED`, page through
   `/api/v2/order/get_order_list` (`time_range_field=create_time`, window
   `SHOPEE_SYNC_WINDOW_DAYS` (2) days, `SHOPEE_PAGE_SIZE` 100). Any failed page → 502.
4. Add every locally open order (`done = false`, status active) not in that list, whatever its
   age, so cancellations/shipments of old orders reach the database.
5. Fetch details in chunks of `SHOPEE_ORDER_CHUNK_SIZE` (50) via `get_order_detail`
   (recipient, note, items, split_up, carrier, packages). For orders **not** in
   `READY_TO_SHIP`, fetch tracking numbers via `logistics/get_mass_tracking_number` in chunks
   of `SHOPEE_PACKAGE_CHUNK_SIZE` (50). A failed tracking chunk marks its packages as failed.
6. Store all successful chunks in one transaction (`sync_shopee_orders_to_db`):
   - new order: insert order (unowned), recipient, items, packages;
   - existing order: refresh `status`, `ship_by`, `split_up`, `shipping_carrier`, replace items;
     recipient and note are updated only while the order is inside retention, and a purged
     recipient row is never recreated;
   - package rows keyed by `package_number`: failed-tracking packages are skipped (keep old
     values); for non-`READY_TO_SHIP` orders tracking/pickup code are overwritten.
   - Orders are never deleted.
   Then, also after a partial sync, `close_shipped_outbound` (V2_ORDERS_DELTA C1): every open
   scan whose label is exactly the SN or a tracking number of an order in `SHIPPED`,
   `TO_CONFIRM_RECEIVE` or `COMPLETED` is closed and the order marked done. It matches the
   database, not this sync's batch; cancelled and returned orders and unscanned ones are left
   alone. If it closed any, admins get `outbound_update`. Logged as `outbound.auto_closed`.
7. If any detail chunk failed: the rest is stored, the cache is **not** marked synced, 502.
   Otherwise `mark_synced()` (also clears the circuit flag).
8. Broadcast `shopee_orders_update` to admins and to the caller, then return the caller's view.

**Transport rules (`shopee_request`).** HMAC-SHA256 signing with `PARTNER_KEY`; params
`partner_id, timestamp, access_token, shop_id, sign`. HTTP 429 and payload errors
`request_limit_exceeded`/`frequency_limited` retry `SHOPEE_MAX_RETRIES` (3) times with
exponential backoff from `SHOPEE_BACKOFF_DELAY` (1.5 s). Token errors
(`invalid_access_token`, `invalid_acceess_token`, `error_access_token`) trigger one refresh
under `TOKEN_REFRESH_LOCK` (skipped if another caller already rotated the token) and one
retry. A failed refresh trips the **circuit** (`cache_mgr.set_token_fatal`): every Shopee call
then fails fast with **503** until an admin saves new tokens or `POST
/shopee/reset-cache-state`. Logged URLs and exceptions are redacted (`redact()`). Missing
configuration (host, partner, shop, token) makes the call return `None`, which surfaces as 502.

**Mock bypass.** With `MOCK_ORDER_BYPASS` on (refused under production rules), any failure in
steps 3–7 is swallowed: database orders are served (e.g. from `scripts.seed_dev`) and the
sync is not marked complete.

### 7.2 Order visibility and claiming

- Lists use `active_orders_query()` ordered by `ship_by DESC`. A **late** order (ship-by passed)
  stays listed until Shopee reports it shipped or cancelled, or a close completes it: the sync
  re-fetches every locally open order whatever its age (`local_active_order_sns`, §7.1), so
  statuses stay current without a ship-by cutoff (removed in V2_ORDERS_DELTA F4).
- `POST /shopee/orders/acquire?order_sn=` (query parameter) runs one conditional `UPDATE ...
  WHERE owner_user IS NULL OR owner_user = caller AND done = false RETURNING`. Results: 200
  (claimed, or already the caller's); 404 order unknown; 409 "Order already completed" or
  "Order is already assigned to another operator". Claiming ignores `status` and `ship_by`.
  On success the sync cache is invalidated and the caller plus admins get
  `shopee_orders_update`.
- There is no unclaim endpoint. Orders lose their owner only when the user is deleted.
- Operators therefore find orders by **scanning the order number**: the client calls acquire;
  on 404 it calls `GET /shopee/orders?refresh=true` and retries once (contract v1).

### 7.3 Order payload (`order_payload.build_order_responses`)

`ShopeeOrderResponse` = order fields + `info` (all packages, by id) + `recipient_address` +
`item_list`, where `item_list` is **expanded to warehouse components**:

1. For each sold item: `sku = model_sku or item_sku`, `shopee_id = model_id or item_id`,
   `qty = model_quantity_purchased or 1`.
2. If a marketplace BOM exists for `shopee_id`: total = `qty × header.quantity_standard`;
   each detail contributes `standard_leaves(component, detail.quantity_standard × total)`.
   A marketplace BOM with no details yields one leaf `MP:<shopee_id>`.
3. Else if a standard BOM exists for `sku`: `standard_leaves(sku, qty)`.
4. Else the item itself is the leaf (name from warehouse item, else Shopee item name).
5. `standard_leaves` recurses through `bom_details` multiplying quantities; a cycle or empty
   BOM makes the node a leaf. Each leaf carries the warehouse item's name (else the SKU) and
   `location` (the derived bin list).
6. Leaves are summed per `(sku, name, location)` in first-seen order.

The builder uses a bounded number of queries regardless of how many orders are built. The
admin BOM endpoints (`/admin/bom/tree`) build the **unflattened** tree with the same
multipliers (`queries/bom.py`).

### 7.4 Barcode / SKU resolution (`queries/warehouse.resolve_barcode_to_item`)

Used by item search, pick creation and stock updates. Input is a raw scan.

1. Take the first non-empty line, then its first whitespace-separated token.
2. **SKU candidate**: the part before the first `*`; if it fully matches `[a-zA-Z]\d{2}_\d{3}`
   (e.g. `A01_001`), look up `items.sku` case-insensitively (exact, not `LIKE`). Hit → done.
3. **Supplier barcode**: if the token matches `<alnum>:<middle>:<alnum>`, use `<middle>`.
   Then: four dash-separated alphanumeric groups → keep as is; three parts → last two joined
   with `-`; two parts → the second; otherwise unchanged. Look up `items.supplier_barcode`
   case-insensitively. Hit → done.
4. Exact case-insensitive match of the token on `items.sku`.

`GET /items/find?query=` returns `[resolved item]` on a hit, else up to 50 items whose SKU or
name contains the query (`ILIKE`, with `\ % _` escaped).

### 7.5 Pick lifecycle (`queries/pick_items.py`, one transaction each)

Lock order everywhere: order (v2 picks and worker deletion) → pick entry → allocations → stock
rows. v1 operations do not lock the order. The table covers the v1 operations; v2 is below it.

| Operation | Rules | Stock effect | Errors |
|---|---|---|---|
| `POST /pick-items {sku, qty>0, order_sn?}` | `sku` resolved via §7.4. With `order_sn`, the order must be owned by the caller and not done. Adds to the existing `(sku, order_sn, caller)` entry or creates it. | deduct `qty` (§7.6); shortfall allowed | 404 unknown item / order not claimed by caller; 409 order done |
| `POST /pick-items/{id}/assign {order_sn, qty?}` | entry must be the caller's; target order as above. `qty` defaults to and is capped at the entry qty. Same order → no-op. Moves qty into the `(sku, order_sn, caller)` entry; deletes the source at 0. | none; allocations move FIFO, deducted quantity first | 404; 409; 400 "Invalid quantity" |
| `POST /pick-items/unassign {order_sn, sku, qty>0}` | entry `(sku, order_sn, caller)` must exist (`sku` must be the stored resolved SKU). Moves `min(qty, entry.qty)` into the caller's general entry. Order state is not checked. | none | 404 |
| `DELETE /pick-items/{id}` | owner, or any entry for admins | every allocation returned (`pick_restore`) | 404 "Entry not found or unauthorized" |

Create, assign and unassign set the receiving entry's `timestamp` to now. Events after commit: caller +
admins get `pick_item_entries_update`; create and delete also broadcast `stocks_update` to
everyone.

**Contract v2** (`pick_for_order`, `unassign_from_order`; V2_PICKING_DELTA): the order is locked
`FOR NO KEY UPDATE`, so picks, unassigns and closes of one order run one at a time. Entries never
have `order_sn = NULL`; a duplicate row left by v1 is merged.

| Operation | Rules | Stock effect | Errors |
|---|---|---|---|
| `POST /v2/shopee/orders/{order_sn}/picks {sku, qty>0}` | order claimed by the caller, not done, and active on Shopee; `sku` resolved via §7.4 | deduct (§7.6) | 404; 409 done, not active, or strict stock |
| `POST /v2/shopee/orders/{order_sn}/picks/unassign {sku, qty>0}` | order claimed by the caller and not done (a cancelled one is allowed); `sku` is the stored SKU | `restore_pick_quantity` (§7.6) | 404; 409 done, or more than is picked |

### 7.6 Inventory engine

`queries/stocks.py`. All rows of a SKU are locked (`ORDER BY sku, location FOR UPDATE`);
pre-migration duplicate rows are folded on load.

| Decision | `multi` (default) | `single` |
|---|---|---|
| target of set/add | requested `location`; else the SKU's only bin; else the unlocated bin | requested `location`; else the SKU's first bin |
| before set/add | – | merge every other bin into the target (`mode_merge`) |
| transfer source | requested bin (same rule as target), requested quantity | all bins, everything |
| pick deduction order | `location` ascending, unlocated last | same (normally one row) |
| restore target | the allocation's original bin (recreated if deleted) | the SKU's current first bin, else the original |

`POST /stocks/update {sku, stock≥0, mode: set|add, location?, move_to?}`:

- `location`/`move_to` are trimmed; empty → `NULL`.
- Without `move_to`: `set` writes `stock` (delta = stock − current), `add` adds it. An
  adjustment that changes nothing is still logged (`adjust_set` / `adjust_add`, delta 0).
- With `move_to` (transfer): `stock` must be > 0 and `location != move_to` (422). Source ==
  destination after resolution → no-op. Source has nothing → 400 "Source location has no
  stock"; not enough → 400 "Insufficient stock at source location". In `single` mode the
  whole stock moves regardless of `stock`.
- Unknown item → 404. Response: `{success, sku, stock, item_name, location}`; a deleted (0)
  row is returned as `stock: 0`.
- Broadcasts `stocks_update` to everyone.

**Picks:** deduction takes bin by bin in deduction order, writing one allocation and one
`pick` log row per bin. Unmet quantity is logged `pick_shortfall` (log row with `delta = 0`
and a warning) and is never restored. A pick never fails for lack of stock unless
`STOCK_STRICT=1` (then 409 and nothing changes: `InsufficientStockError`, checked on the locked
rows). Stock never goes negative. `restore_pick_quantity` is the exact reverse of a pick: the
shortfall first, then the newest allocations. Stock is *deducted* at pick time; there is no reservation (KNOWN_LIMITATIONS
#5).

### 7.7 Outbound scans and period closure

`POST /outbound {content, tags?}`: `content` is trimmed. 409 "Duplicate scan detected" if the
caller already has an **open** scan with the same content (other users may scan the same
label). If `content` equals an order's `order_sn` or any package `tracking_number`, that
order's `shipping_carrier` is appended to the tags. Events: admins + the scanning user get
`outbound_update`.

`POST /outbound/close [values…]` (admin, ≤ 10,000 × 1024 chars):

1. Trim, drop empties, de-duplicate preserving order. Matching is **exact**
   everywhere below (V2_ORDERS_DELTA Q57), like the console's pairing.
2. Close all **open** scans (any user) whose `content` is in the list: `closed = true`,
   `closed_at = now`.
3. `unknown` = submitted values that closed no scan.
4. Orders matched by `order_sn`; values that are not order numbers are matched against
   `tracking_number`. Matched orders with `done = false` get `done = true`, `done_at = now`.
   Orders are completed even when no scan matched.
5. Returns `{outbound, unknown, orders_done}`; invalidates the sync cache; broadcasts
   `outbound_update` and `shopee_orders_update` **to admins only** (operators' lists update on
   their next request).

`DELETE /admin/clear/outbound-items` deletes every scan (open and closed) and their tags;
admins get `outbound_update`. `/admin/history/outbound` lists closed scans; exports: §9.

### 7.8 User administration

- `POST /admin/users {username, password}` creates a `client` user (409 if taken). `POST
  /auth/register` does the same and returns tokens, but only with `ALLOW_REGISTRATION` (403
  otherwise; 400 if the name exists).
- `POST /admin/users/{username}/password` (client accounts only, else 404): new hash, all
  refresh tokens deleted, sockets closed (code 1008).
- `DELETE /admin/users?username=` (client accounts only, else 404), in one transaction:
  delete the user's pick entries exactly like `DELETE /pick-items/{id}` (allocated stock
  restored, `pick_restore` rows with the deleting admin as actor), its outbound scans and
  refresh tokens; unassign its orders; delete the user. Then its sockets are closed and
  `pick_item_entries`, `outbound_items` and `shopee_orders` go to admins, `stocks_update`
  to everyone.
- All three broadcast `users_update` (`[{username, scope}]`) to admins.
- Admin accounts cannot be created, reset or deleted through the API.
- Password minimum length is a dormant switch (KNOWN_LIMITATIONS #9).

### 7.9 Recipient data retention

Cutoff = now − `RECIPIENT_RETENTION_DAYS` (default 30, max 90 under production rules). An
order is past retention when `done_at < cutoff`, or `done = false AND ship_by < cutoff`. The
purge deletes its recipient row and clears `note` on its packages; order numbers, items and
tracking numbers stay. Sync never writes buyer data back for such orders. Only counts are
logged.

---

## 8. WebSocket protocol in detail

Frame: `{"type": <event>, "data": [<object>, ...]}`. `data` is **always a list of objects**,
including errors (`[{"detail": "..."}]`). Unknown commands → error frame
`Unknown command: <first 64 chars>`.

Two endpoints share one `ConnectionManager` and one command loop (`routers/websocket.py`,
T6.4): `/ws` (contract v1, rejection = HTTP 403 before accept) and `/v2/ws` (contract v2:
`X-Client-Version` header; failures close after accept with 4400 / 4401 / 4426). Each socket
is tagged with its contract (`socket_contracts`) and its session (`socket_sessions`).
`ConnectionManager.frame()` wraps the shared payload per socket: v1 `{type, data}`, v2
`{type, data, ts}`. Payloads are still built once per audience, whatever the mix of contracts,
so every event reaches v1 and v2 devices and both admins alike.

**Commands → reply to this socket only:**

| Command | Reply |
|---|---|
| `get_items` | `outbound_update` (open scans: own; admins all) |
| `get_shopee_orders` | `shopee_orders_update` (active orders: claimed by caller; admins all), then `pick_item_entries_update` (own; admins all) |
| `get_stocks` | `stocks_update` (all bins with item name; same for everyone) |
| `get_users` | `users_update` (admins) or error `Forbidden` |

**Server pushes (after commit):**

| Trigger | Event | Recipients |
|---|---|---|
| user created/registered/reset/deleted | `users_update` | admins |
| outbound scan created | `outbound_update` | admins + the scanning user |
| period closed | `outbound_update`, `shopee_orders_update` | admins |
| all scans cleared | `outbound_update` | admins |
| sync performed (cache miss) | `shopee_orders_update` | admins + the requesting user |
| order claimed | `shopee_orders_update` | the claimer + admins |
| pick create / delete | `pick_item_entries_update`; `stocks_update` | caller + admins; everyone |
| pick assign / unassign | `pick_item_entries_update` | caller + admins |
| stock update / transfer | `stocks_update` | everyone |

Each recipient's payload is computed for its audience: one shared payload for all admins,
one per operator, one for scope-independent events (`users_update`, `stocks_update`). Payload
items use the same response models as HTTP (`OutboundResponse`, `ShopeeOrderResponse`,
`PickItemEntryResponse` with `item_name`, `StockResponse`, `UserResponse`). Socket closure on
user deletion/reset uses code 1008. A failed send drops that socket.

---

## 9. Exports and history

- `GET /admin/export/scans`: CSV of every scan (open and closed), newest first.
- `GET /admin/export/stocks`: inventory CSV. Both are `StreamingResponse` text/csv built in
  `queries/csv_export.py`. The admin web app saves them through a Blob URL and a hidden
  `<a download>` (`frontend/admin/lib/csv_download_web.dart`).
- `GET /admin/history/outbound`, `/admin/history/shopee/orders`: `limit` 1–2000 (default
  500), `offset`; total in `X-Total-Count`; the body stays a list. Order history is sorted
  `done_at DESC NULLS LAST, ship_by DESC, order_sn`.
  Optional server-side filters (`queries/history.py`, V2_DELTA D9): `closed_from`/`closed_to`
  on the close time (`closed_at` / `done_at`, inclusive), `day_from`/`day_to` on business days, and
  `q` (ILIKE with `%`/`_` escaped) over label, worker and tags, or SN, worker, tracking number,
  pickup code, courier and buyer name (V2_ORDERS_DELTA Q49; buyer names exist only within
  `RECIPIENT_RETENTION_DAYS`).
- `GET /admin/history/days` and `/days/{day}` (V2_ORDERS_DELTA C2, R4.2): one row per business
  day, and all of one day unpaged. A closed scan belongs to the day it was **made**; a done order
  is on every day one of its closed scans was made, or on the day it was done when it has none.
  A past day can grow when its scans close later. With `q`, only days holding a matching scan or
  order are listed, with their full counts.
- `GET /admin/lookup?label=` (`queries/history.lookup_label`): orders whose SN or a tracking
  number equals the label and the scans of it, open or closed; trimmed, then exact, at
  most 10 orders and 20 scans, and the History `day` it left on. The console's History answers "did it leave?" from it.

---

## 10. Operator client contract v1

The shipped operator client depends on exactly this; breaking any of it needs a client
major and side-by-side `/v2` routes (policy: KNOWN_LIMITATIONS #8). Guarded by
`backend/tests/test_client_contract_v1.py` (HTTP snapshot `tests/contracts/client_v1.json`)
and `backend/tests/test_ws_contract_v1.py`.

| Call | Shape relied on |
|---|---|
| `POST /auth/login`, `/auth/register` | `{username, password}` → 200 `{access_token, refresh_token}`; 400/401/409 → show `detail` |
| `POST /auth/refresh` | `{refresh_token}` → 200 new pair; anything else → logout |
| `POST /auth/logout` | `{refresh_token}`; result ignored |
| `POST /auth/ws-token` | 200 `{token}`; ≥ 500 → retry; other non-200 → logout |
| `GET /.well-known/jwks.json` | RS256 JWKS; access tokens JWS-verifiable, `exp` an int |
| `POST /outbound` | `{content, tags: null}` → 200; 409 → alert with `detail` |
| `POST /pick-items` | `{sku, qty, order_sn?}` → 200 |
| `POST /pick-items/{id}/assign` | `{order_sn, qty?}` → 200 |
| `POST /pick-items/unassign` | `{order_sn, sku, qty}` → 200 |
| `DELETE /pick-items/{id}` | → 200 |
| `POST /shopee/orders/acquire?order_sn=` | 200 / **404 drives refresh-and-retry** / other → error |
| `GET /shopee/orders?refresh=true` | only `statusCode == 200` matters |
| `GET /items/find?query=` | query **not URL-encoded** by the client; 200 → `[{sku, item_name, location}]` |
| `POST /stocks/update` | `{sku, stock, mode, location?, move_to?}` → 200 |
| `WS /ws?token=` | rejection must surface as HTTP 403 |
| WS commands | `get_items`, `get_shopee_orders`, `get_stocks` |

- **Success is exactly 200** on every call. 401 → refresh and retry once; 409 → alert;
  ≥ 500 → "Server error".
- **Frame rule:** the client parses `data` as `List<Map>` before reading `type`.
- **Required response fields** (missing/null/wrong type crashes parsing):
  `OutboundItem.id:int, created_at`; `ShopeeOrder.order_sn, ship_by`, `info[].id`,
  `recipient_address.id`, `item_list[].quantity:int`; `PickItemEntry.id, timestamp`;
  `Stock.id:int` (synthetic `0` is fine).
- **Safe changes:** new response fields, endpoints, WS event types with list-of-object data,
  timezone suffixes, stricter validation that still answers 200/401/409/handled errors.
  Deliberate narrowings so far: the request size limits (API.md).

---

## 10A. Operator client contract v2 (`/v2`)

Since v0.6.0 (T6.3). Not frozen, but guarded like v1: `tests/test_client_contract_v2.py`
(snapshot `tests/contracts/client_v2.json`, additive unless regenerated on purpose) and the
committed export `backend/openapi/v2.json`.

- `src/routers/v2/__init__.py` mirrors the v1 client operations at `/v2<path>` (list in API.md
  "Operator-client contract v2"), **reusing the v1 endpoint functions**, response models,
  summaries and error declarations; tags are prefixed `v2 · `. No register, JWKS or admin
  operations.
- Gate (`require_client_version`): `X-Client-Version` integer required (400 otherwise); below
  `min_supported_version_code` from `<CLIENT_RELEASES_DIR>/latest.json` → 426
  `{detail, min_supported_version_code}` (`exceptions.ClientUpgradeRequired`). `/v2/meta` is
  ungated. The metadata file is re-read only when its mtime changes
  (`services/client_releases.py`).
- `config.CLIENT_CONTRACT = 2`, `/meta` reports `{min: 1, max: 2}`.
- OTA (T6.5, `routers/client_release.py`): `GET /v2/client/latest` and
  `GET /v2/client/apk/{version_code}`, public and ungated. Files in `CLIENT_RELEASES_DIR`
  (`orderchecker-<code>.apk`, `latest.json`), written only by `scripts.publish_client_release`
  (higher versionCode required, SHA-256 checked after copy, metadata replaced atomically last);
  compose mounts `RELEASES_VOLUME` read-only.
- Devices (T6.6, `routers/device.py`, `services/device_service.py`, `queries/devices.py`):
  `POST /v2/device/register` verifies an ECDSA P-256 signature over the caller's `sid`
  (`cryptography`), upserts by public key (new → `pending`, `revoked` → 403, row lock + retry
  on a first-registration race) and sets `sessions.device_id`. The gate stores the version in
  `request.state.client_version`; `get_current_principal` passes it to
  `get_user_for_session`, which updates the device in the same transaction: `last_seen_at` on
  the 60 s throttle, `app_version_code` at once when it changed. Root (v1) requests never touch
  devices. `GET /admin/devices` lists them (`AdminDeviceResponse`: the device plus `online`,
  true when a live session of the device has an open WebSocket right now, from
  `conn_mgr.live_session_ids()` → `queries.device_ids_for_sessions`; V2_DELTA Q35). `last_seen_at`
  moves only on HTTP requests, so `online` is what the console shows as status.

---

## 11. Maintenance scripts (`backend/scripts`, run as `python -m scripts.<name>`)

| Script | Purpose |
|---|---|
| `set_admin_password` | apply the configured `ADMIN_PASSWORD` to the existing admin; refuses defaults; revokes its refresh tokens |
| `clear_open_pick_entries --confirm` | one-time T4.4 cutover: delete all pick entries and allocations **without** restoring stock; logs `cutover_clear` |
| `stock_merge_single [--confirm]` | merge multi-bin SKUs onto their first bin before switching to `single` (dry run without `--confirm`) |
| `seed_dev [--reset]` | synthetic orders/items for development; refuses under production rules |
| `ci_migration_gate.sh` | CI: upgrade from the previous release tag to head |

---

## 12. Frontends

Both apps: Flutter, `provider` with one `ChangeNotifier` `AppState`; `http`;
`web_socket_channel`; `jose` for JWKS verification; `flutter_dotenv` reading a bundled
`.env` asset (`BASE_URL`, `WS_URL`). Tokens and username live in `flutter_secure_storage`.

**Shared session behaviour.** On start, a stored access token is verified against the
cached JWKS (15 min; force-refresh on failure); if it is invalid the app tries a refresh, and
shows the login screen if that fails. Every request
has a 15 s timeout (a 5 s "taking longer" notice in the client); a 401 triggers one refresh
(concurrent refreshes share one `Completer`) and one retry. WebSocket: fetch a ticket,
connect `WS_URL/ws?token=`; on close/error retry every 2 s up to 5 times, then show a
connection-failed banner with a manual retry. An error containing `403` triggers a token
refresh and reconnect, or logout.

### 12.1 Operator client (`frontend/client`, Android + Windows)

Production devices run a **debug** build: release builds lack the `INTERNET` permission
(KNOWN_LIMITATIONS #10).

Drawer navigation; Inbound, Outbound and Stocks have **Input / History** sub-tabs.

| Index | Screen | Behaviour |
|---|---|---|
| 0 | Orders · Inbound (`orders_view.dart`) | scan an order number (must match `^\d{6}`) → acquire (404 → sync + retry once) → select it; scan SKUs + quantity → `POST /pick-items` with that `order_sn`; lists claimed orders with their expanded components and picks; assign general picks to an order, unassign, delete |
| 1 | Orders · Outbound (`scanner_view.dart`) | scan a label → `POST /outbound` (tags null); history filterable by tag |
| 2 | Item Finder (`item_finder_screen.dart`) | `GET /items/find`, 5-minute in-memory cache per query |
| 3 | Stocks (`stocks_view.dart`) | set/add/transfer via `POST /stocks/update`; location suggestions from the SKU's existing bins |
| 4 | Account | user name, logout |

Data arrives through WebSocket commands (`get_shopee_orders` on Inbound, `get_items` on
Outbound, `get_stocks` on Stocks), not HTTP lists. Uses `IOWebSocketChannel` (`dart:io`; no
web build). Login screen also offers registration (works only where `ALLOW_REGISTRATION` is
on). The client does not read `GET /meta`.

### 12.2 Admin app (`frontend/admin`, web only)

`NavigationRail`: Users, Finder, Orders, Stocks, Config, BOM (+ account). Logs in with
`POST /auth/admin`.

| View | Endpoints |
|---|---|
| Users | WS `get_users`; `POST /admin/users`; `POST /admin/users/{u}/password`; `DELETE /admin/users?username=` |
| Finder | `GET /items/find` |
| Orders | WS `get_shopee_orders` / `get_items`; `GET /shopee/orders`; `POST /shopee/reset-cache-state`; history pages (`limit`/`offset`, "Load older history"); `POST /outbound/close`; `DELETE /admin/clear/outbound-items`; scan export |
| Stocks | WS `get_stocks`; stock export |
| Config | unlock / read / save / lock Shopee config with `X-Config-Token` |
| BOM | `GET /admin/bom/headers`, `GET /admin/bom/tree?sku=|shopee_id=&qty=` |

- Uses `WebSocketChannel.connect` (works in the browser; KNOWN_LIMITATIONS #7).
- `SafeStorage` falls back to `localStorage`/memory when secure storage is unavailable (plain
  HTTP, non-secure context).
- Served by nginx (`nginx.conf.template`): static app. Flutter web file names are not
  content-hashed, so static files are sent `Cache-Control: no-cache` (revalidated by ETag)
  and `index.html`, `/.env`, `/assets/.env` `no-store`; `/auth /admin /outbound /items /stocks /shopee /pick-items /meta /.well-known`
  and `/ws` (with upgrade headers) are proxied to `BACKEND_HOST:BACKEND_PORT`, so the app is
  same-origin and needs no CORS.
- `docker-entrypoint.sh` writes `assets/.env` at container start from a mounted `/app/.env`
  or from `BASE`/`BASE_URL`/`WS_URL` (defaults `/`, i.e. same origin).
- The admin app does not read `GET /meta` yet.

---

## 13. Tests and CI

- `backend/tests/test_*.py`: unit, contract, OpenAPI, settings guard, event-loop guard,
  logging, managers, request limits, datetime format. No database needed.
- `backend/tests/integration/*_pg.py`: run only with `TEST_DATABASE_URL` pointing at a local
  database named `*_test`; schema from `alembic upgrade head`; covers locks, stock engine
  (both modes), sync, history, retention, outbound, migrations, seed.
- CI (`.github/workflows/ci.yml`): Ruff, `requirements.txt` ↔ `uv.lock` check, pytest with a
  PostgreSQL service; migration gate; `flutter analyze` + `flutter test` per app.
- Commands: TESTING.md and IMPLEMENTATION_PLAN §1.4.

---

## 14. Open gaps observed in code

Facts verified against the source on 2026-11-21. Fixing them is not scheduled unless the
plan says so.

1. Process-local state (sockets, sync cache/lock, Shopee circuit): one worker only.
2. ~~Access tokens stay valid until expiry after logout~~: fixed by sessions (T6.2).
3. `warehouse.shopee_items` is unused; `refresh_tokens.revoked_at/ip_address/agent` are
   never written (sessions hold IP and agent since T6.2).
4. `queries/engine.py` still falls back to SQLite when `DATABASE_URL` is missing; production
   rules refuse that at startup, development would fail on the multi-schema model.
5. Period closure pushes updates to admins only; operators see closed scans disappear on
   their next `get_items`.
6. `AppState` in both apps holds all network and view state in one class (1–1.2k lines).

---

## 15. Change checklist

| If you change… | Also check |
|---|---|
| anything the operator client calls | §10; run the contract tests; never change success codes or WS `data` shape |
| a datetime field | use `UTCDateTime` |
| a model column | new Alembic revision; integration drift test; ARCHITECTURE "Data ownership" |
| stock logic | `LocationPolicy` only for mode differences; log every change with a reason; tests in both modes |
| a new `async def` touching the DB | `asyncio.to_thread`; `test_event_loop.py` |
| a broadcast | send only after commit; keep `data` a list of objects |
| a config key | `.env.example`, OPERATIONS, and `settings_guard` if it is unsafe in production |
| token identity (`JWT_*`, `APP_ENV`, `data/keys`) | forced relogin; RELEASE.md window |
| an admin endpoint | admin app + API.md; nginx proxy list if it is a new top-level path |
