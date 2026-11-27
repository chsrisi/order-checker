# API guide

The development base URL is `http://localhost:8000`. Swagger UI is available at
`/docs`, ReDoc at `/redoc`, and the machine-readable schema at `/openapi.json`.

## Authentication

Use `POST /auth/login` for operators and `POST /auth/admin` for administrators.
Send the returned access token on protected routes:

```http
Authorization: Bearer <access_token>
```

Access tokens last 15 minutes. Every login starts a **session**; its id is the `sid` claim
of every access and refresh token of that login (required since v0.6.0). `POST /auth/refresh`
consumes a stored refresh token and rotates both tokens within the same session. Each request
checks that the token's session is still live, so ending a session (logout, password reset,
"log out everywhere", user deletion) makes its access **and** refresh tokens fail with 401 on
the next request and closes its WebSocket connections (code 1008). Public signing keys are at
`GET /.well-known/jwks.json`.

## HTTP endpoints

| Method | Path | Scope | Purpose |
| --- | --- | --- | --- |
| POST | `/auth/register` | Public | Create client account and tokens. **403** "Registration is disabled" unless `ALLOW_REGISTRATION` is on (off under production rules) |
| POST | `/auth/login` | Public | Operator login. **429** after 10 failed attempts for a username within 15 minutes |
| POST | `/auth/admin` | Public | Admin-only login (same 429 throttle) |
| POST | `/auth/refresh` | Public | Rotate refresh token pair |
| POST | `/auth/logout` | Public | End the refresh token's session (its tokens stop working at once, its sockets close) |
| POST | `/auth/ws-token` | User | Create 30-second one-use WS ticket |
| GET | `/.well-known/jwks.json` | Public | Token verification keys |
| GET | `/meta` | Public | `{api_version, client_contract: {min, max}, app_env, stock_location_mode, features}`; `client_contract` is `{min: 1, max: 2}` since v0.6.0. No secrets or hostnames. New clients read it to negotiate the contract and adapt the stock UX |
| GET/DELETE | `/admin/users` | Admin | List/delete client users. Delete restores the stock of the user's pick entries (like `DELETE /pick-items/{id}`), deletes its scans and tokens, releases its orders and closes its WebSocket sessions |
| POST | `/admin/users` | Admin | Create a client-scope operator `{username, password}`; 409 if the username exists |
| POST | `/admin/users/{username}/password` | Admin | Reset a client password `{password}`; revokes all sessions and closes sockets; 404 for unknown or admin accounts |
| GET | `/admin/devices` | Admin | v2 devices, most recently seen first: `id`, `status` (`pending`/`active`/`revoked`), `current_username`, `model`, `android_version`, `app_version_code`, `enrolled_at`, `last_seen_at`. Read-only (approve/revoke come with step 8) |
| GET | `/admin/login-requests` | Admin | Pending login requests, oldest first: `id`, `username`, `match_code`, device, IP, `created_at`, `expires_at` |
| POST | `/admin/login-requests/{id}/approve`, `/deny` | Admin | Decide. 404 expired or cancelled, 409 already decided |
| POST | `/admin/users/{username}/logout` | Admin | "Log out everywhere": revoke every session of a client account, close its sockets; the password is unchanged; 404 for unknown or admin accounts |
| GET | `/admin/history/outbound` | Admin | Closed scans, newest first, paged like order history (`limit`/`offset`, `X-Total-Count`). Optional filters (since 2026-11-24): `closed_from`/`closed_to` (close time, inclusive; ISO 8601, UTC without an offset), `day_from`/`day_to` (business days by scan time, `YYYY-MM-DD`), `q` (label, worker or tag, case-insensitive) |
| GET | `/admin/history/shopee/orders` | Admin | Completed order history, most recently completed first. `?limit=` (1–2000, default 500) and `&offset=`; the `X-Total-Count` header gives the total. Same optional filters, `closed_from`/`closed_to` on `done_at`; `q` matches SN, worker, tracking number, pickup code, courier or buyer name (buyer names only within the retention window) |
| GET | `/admin/history/days` | Admin | One row per business day (`BUSINESS_UTC_OFFSET`), newest first: `{day, outbound, orders_done, tags}`. A closed scan counts on the day it was **made**. `limit` 1–500 (default 50), `offset`, `day_from`/`day_to`, `q` (only days holding a matching scan or order, with their full counts); `X-Total-Count`. Replaces `/admin/history/closes` (V2_ORDERS_DELTA C2) |
| GET | `/admin/history/days/{day}` | Admin | `{day, orders, scans}`: all of one day, unpaged |
| GET | `/admin/lookup?label=` | Admin | Where an exact label is (V2_ORDERS_DELTA Q49): `{label, orders, scans}`, the orders whose SN or a tracking number is the label (ongoing or done; `done_at` is its close), its scans, open or closed, newest first, and `day` (the History day it left on, or null). Exact after trimming |
| GET | `/admin/tasks` | Admin | Tasks, oldest first. Filters `assigned_to`, `type` (`count`/`pick`), `status` (repeatable). Without `status`: open and blocked, plus those closed in the last 7 days (what `tasks_update` carries) |
| POST | `/admin/tasks/count` | Admin | `{sku, assigned_to, location?, note?}`: a blind count of one item. `location` (the bin) required in `multi` mode, refused (400) in `single` mode. 404 unknown item or worker |
| POST | `/admin/tasks/pick` | Admin | `{lines: [{sku, qty}], assigned_to, reference?, note?}`: a manual picking task; bundles expand by the standard BOM, stored with the task. 404 unknown item or worker |
| GET | `/admin/tasks/{id}` | Admin | The task plus `stock_log` (every row it caused) and, for a done count, `recorded_before` and `difference` (counted − recorded) |
| POST | `/admin/tasks/{id}/cancel` | Admin | `{return_stock: true}` (default) returns picked stock; `false` keeps it deducted. Open or blocked only (409) |
| POST | `/admin/tasks/{id}/reassign` | Admin | `{assigned_to}`: open or blocked → open for that worker; picks move with the task |
| POST | `/admin/tasks/{id}/close` | Admin | Close a **blocked** pick task as done with what was picked (409 otherwise) |
| GET | `/admin/order-tasks` | Admin | Claimed active orders not yet *Picked*, per worker (`?assigned_to=`): `{order_sn, owner_user, ship_by, status, state, done_skus, required_skus}`; read-only, derived |
| GET | `/admin/export/scans` | Admin | CSV of every outbound scan (open and closed), newest first |
| GET | `/admin/export/stocks` | Admin | Inventory CSV |
| DELETE | `/admin/clear/outbound-items` | Admin | Permanently clear scan records |
| GET | `/admin/bom/headers` | Admin | Standard and marketplace BOM roots |
| GET | `/admin/bom/tree` | Admin | Resolve one BOM: exactly one of `sku` / `shopee_id`; `qty` ≥ 1 (422 otherwise) |
| POST | `/admin/shopee-config/unlock` | Admin | Create 2-minute config session |
| GET/POST | `/admin/shopee-config` | Admin + `X-Config-Token` header | Read/update Shopee tokens (the token was a `?token=` query parameter before v0.5) |
| POST | `/admin/shopee-config/lock` | Admin + `X-Config-Token` header | End config session |
| GET/POST | `/outbound` | User | List/create open scans |
| POST | `/outbound/close` | Admin | Close scans and complete orders |
| GET | `/items/find` | User | Search SKU, name, or barcode (uses barcode resolution pipeline) |
| GET | `/stocks` | User | List inventory; `?join_warehouse=true` adds `item_name` |
| POST | `/stocks/update` | User | Set/add/transfer inventory |
| GET | `/shopee/orders` | User | Synchronize active orders; returns all for admins, only the caller's claimed orders for operators |
| POST | `/shopee/orders/acquire` | User | Atomically claim an order. 404 if unknown; 409 if another operator owns it or it is already completed |
| POST | `/shopee/reset-cache-state` | Admin | Reset sync circuit/cache |
| GET/POST | `/pick-items` | User | List/create pick entries (POST deducts stock bin by bin; a shortfall never fails the pick; `order_sn` must be claimed by the caller and not done: 404/409) |
| POST | `/pick-items/{id}/assign` | User | Assign quantity to a claimed, unfinished order (404/409); stock unchanged |
| POST | `/pick-items/unassign` | User | Return quantity to general picks |
| DELETE | `/pick-items/{id}` | User | Delete owned entry (admin: any) and return its deducted stock |

Request and response fields, examples, constraints, and error responses are kept
in OpenAPI so generated clients do not need to duplicate this table.

## Operator-client contract v2 (`/v2`)

The root routes above are contract v1 (frozen, KNOWN_LIMITATIONS #8). Since v0.6.0 the same
operations are also served under `/v2` for the v2 operator app, by **the same handlers**
(identical request, response and error behaviour):

| v2 path | Same as |
|---|---|
| `POST /v2/auth/login`, `/v2/auth/refresh`, `/v2/auth/logout`, `/v2/auth/ws-token` | `/auth/...` |
| `POST /v2/outbound` | `POST /outbound`, but 403 for admins |
| `GET /v2/shopee/orders`, `POST /v2/shopee/orders/acquire` | `/shopee/orders...`, but acquire answers 403 to admins |
| `GET /v2/items/find` | `GET /items/find` |
| `POST /v2/stocks/update` | `POST /stocks/update` |
| `GET /v2/meta` | `GET /meta` |

v2 only (V2_PICKING_DELTA; admins get 403):

| Endpoint | Purpose |
|---|---|
| `POST /v2/shopee/orders/{order_sn}/picks` `{sku, qty}` | Pick into a claimed order → `{order_sn, sku, qty, item_name}` with the resolved SKU and the line's total. 404 unknown item or order; 409 completed, not active on Shopee, or not enough stock (`STOCK_STRICT`) |
| `POST /v2/shopee/orders/{order_sn}/picks/unassign` `{sku, qty}` | Take a quantity off the order and return it to stock. 404 not picked; 409 completed, or more than is picked |

Tasks (T9.2; only the assigned worker, admins get 403; 404 when the task is not the caller's):

| Endpoint | Purpose |
|---|---|
| `GET /v2/tasks` | `{tasks, order_tasks}`: the caller's open and blocked tasks (oldest first) and claimed orders not yet *Picked* |
| `POST /v2/tasks/{id}/count` `{sku, qty, location?}` | Record a blind count: `set` the quantity, task done. 409 wrong item, wrong location (`multi`: the task's bin, required; `single`: where the item is; compared after trim and upper-case), or not open |
| `POST /v2/tasks/{id}/picks` `{sku, qty}` | Pick into the task → `{task_id, sku, qty, required, item_name, status}`; `status` is `done` once every line is exact. 404 unknown item; 409 not on the task, not open, or strict stock |
| `POST /v2/tasks/{id}/picks/unassign` `{sku, qty}` | Return a picked quantity to stock (same response). 409 more than is picked |
| `POST /v2/tasks/{id}/block` `{reason}` | Can't finish: open → blocked |

Not under `/v2`: the v1 `/pick-items` operations, registration, JWKS (the v2 app does not verify tokens locally), and every
admin operation (the admin API stays at the root).

**Version gate.** Every `/v2` operation except `/v2/meta` (and the update and device-registration
endpoints) requires `X-Client-Version: <versionCode>`:

- missing or not a non-negative integer → **400** `{"detail": "X-Client-Version header required"}`
- below the published `min_supported_version_code` → **426**
  `{"detail": "Client update required", "min_supported_version_code": N}`; the app shows its
  update screen

The minimum comes from the published release metadata (OPERATIONS "Publishing a client
release"); with nothing published there is no minimum.

**Login requests (no token, gated, signed by the device key).**
`POST /v2/auth/login-requests` `{username, public_key, nonce, signature}` →
`{id, match_code, expires_in}`; 403 device not registered or revoked, 429 limits.
`POST …/{id}/poll` `{nonce, signature}` → `{status, tokens}` with `pending`, `approved` (tokens,
once), `denied` or `expired`. `POST …/{id}/cancel` is idempotent. 400 bad signature or reused
nonce, 503 Redis down. Signed string: SYSTEM_REFERENCE §5.

**Device registration (operator token, not gated).** `POST /v2/device/register`
`{public_key, model, android_version, app_version_code, signature}` → the device
`{id, status, label, model, android_version, app_version_code, current_username, enrolled_at,
last_seen_at}`. `public_key` is the base64 DER SubjectPublicKeyInfo of the app's Android
Keystore EC P-256 key; `signature` is the base64 DER ECDSA/SHA-256 signature over the UTF-8
`sid` claim of the access token used for the call. New devices are `pending`; calling it again
is idempotent (call it after every login). **400** bad key or signature, **403** device revoked.
It binds the session to the device; from then on every gated `/v2` request updates the
device's `last_seen_at` and `app_version_code` (from `X-Client-Version`).

**Client updates (public, not gated).** `GET /v2/client/latest` →
`{version_code, version_name, apk_url, sha256, size_bytes, min_supported_version_code, notes,
published_at}` (404 while nothing is published); `GET /v2/client/apk/{version_code}` → the APK
(`application/vnd.android.package-archive`, 404 if unknown). `apk_url` is a path; resolve it
against the server address in use. Verify `sha256` before installing.

## Datetimes

Every datetime in HTTP responses and WebSocket frames is a UTC instant with a `Z` suffix, for
example `2026-11-20T21:05:00.123456Z`. Dart's `DateTime.parse` reads it as UTC, and `.toLocal()`
then shows the device's local time. Before v0.5 the values were naive and implicitly UTC. Both
forms parse, so the change is client-safe. In practice, the operator's outbound scan times and
the admin's order times now show in local time instead of UTC.

## Order payload

`GET /shopee/orders`, `/admin/history/shopee/orders` and the `shopee_orders_update` frame
share one shape:

- `item_list` holds the order's sold items expanded through marketplace and standard BOMs into
  warehouse components, summed per component and location.
- `info` holds **one entry per package**, ordered by creation. A split order (`split_up: true`)
  has several. Before v0.5 only one arbitrary package was shown.
- `split_up`, `shipping_carrier` and `done_at` are filled from the stored order. Before v0.5
  they were always `null`. These are additive changes within contract v1.

## Request size limits

Request bodies are bounded to stop abusive input; anything larger returns `422`.

| Field | Limit |
|---|---|
| `content` (`POST /outbound`), `sku` (pick, unassign, stock update) | 1024 characters |
| `order_sn` (pick, assign, unassign) | 64 characters |
| `location`, `move_to` (stock update) | 128 characters |
| `tags` (`POST /outbound`) | 16 items × 64 characters |
| `POST /outbound/close` body (admin) | 10,000 items × 1024 characters |

These are the only deliberate narrowings of client contract v1 (snapshot updated in T2.14).
They sit far above real scanner payloads.

## Errors

Validation failures use FastAPI's `422` response. Authentication failures use
`401`; insufficient scope uses `403`; missing resources use `404`; ownership or
duplicate conflicts use `409`. Shopee synchronization (`GET /shopee/orders`) uses
`502` when Shopee fails or returns an incomplete answer, and `503` while the Shopee
token circuit is open (re-authorization needed). Before v0.5 these were `400`/`500`. The
operator client only checks for `200`, so the change is client-safe. A failed sync is never
marked complete: the next request retries, and order details that did arrive are kept.
Domain errors have one stable envelope:

```json
{"detail": "Human-readable explanation"}
```

Every HTTP response includes `X-Request-ID`. Send your own safe opaque value in
that header to correlate a client failure with server logs.

## WebSocket protocol

OpenAPI does not describe WebSockets. Request a ticket with `/auth/ws-token`, then
connect to `WS_URL/ws?token=<ticket>` before its 30-second expiry. Tickets are
deleted on first use.

Commands:

```json
{"command": "get_items"}
{"command": "get_shopee_orders"}
{"command": "get_stocks"}
{"command": "get_users"}
```

`get_users` requires admin scope. `get_shopee_orders` emits both order and pick
updates. Responses and server broadcasts have this envelope:

```json
{"type": "outbound_update", "data": []}
```

Valid types are `users_update`, `login_requests_update` (admins), `outbound_update`, `shopee_orders_update`,
`pick_item_entries_update`, `stocks_update`, `tasks_update` (admins and v2 sockets only), and `error`. Clients should ignore
unknown future event types and reconnect with a newly issued ticket.

**Contract v2 socket (`/v2/ws`, since v0.6.0).** Ticket from `POST /v2/auth/ws-token`, then
`WS_URL/v2/ws?token=<ticket>` with the header `X-Client-Version: <versionCode>`. Same commands,
same events, same `data` payloads as v1 (built once per audience for both). Differences:

- Frames are `{"type": ..., "data": [...], "ts": "<UTC send time, ...Z>"}`; parse `type` first.
- Handshake failures are reported **after accept** with a close code: **4400** missing or
  malformed `X-Client-Version`, **4401** ticket missing/used/expired or its session revoked,
  **4426** client below `min_supported_version_code` (show the update screen). A revoked
  session's open socket is closed with **1008**, as for v1.
- `tasks_update` (T9.2) reaches only v2 sockets of the assigned worker (never a v1 socket) and
  admins. `data` is the recipient's task list, the same objects as `GET /v2/tasks` `tasks`
  (admins: as `GET /admin/tasks` without filters). Order-tasks follow the order and pick events.


**Frame rule (client contract v1):** `data` is always a JSON array of objects, for every
type and every audience, because the v1 apps parse `data` before they read `type`. Error
frames follow the rule too:

```json
{"type": "error", "data": [{"detail": "Unknown command: foo"}]}
```

`users_update` items contain only `username` and `scope`.
