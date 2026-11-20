# API guide

The development base URL is `http://localhost:8000`. Swagger UI is available at
`/docs`, ReDoc at `/redoc`, and the machine-readable schema at `/openapi.json`.

## Authentication

Use `POST /auth/login` for operators and `POST /auth/admin` for administrators.
Send the returned access token on protected routes:

```http
Authorization: Bearer <access_token>
```

Access tokens last 15 minutes. `POST /auth/refresh` consumes a stored refresh
token and rotates both tokens. `POST /auth/logout` deletes the refresh-token JTI;
it does not blacklist the short-lived access token. Public signing keys are at
`GET /.well-known/jwks.json`.

## HTTP endpoints

| Method | Path | Scope | Purpose |
| --- | --- | --- | --- |
| POST | `/auth/register` | Public | Create client account and tokens. **403** "Registration is disabled" unless `ALLOW_REGISTRATION` is on (off under production rules) |
| POST | `/auth/login` | Public | Operator login. **429** after 10 failed attempts for a username within 15 minutes |
| POST | `/auth/admin` | Public | Admin-only login (same 429 throttle) |
| POST | `/auth/refresh` | Public | Rotate refresh token pair |
| POST | `/auth/logout` | Public | Delete refresh-token record |
| POST | `/auth/ws-token` | User | Create 30-second one-use WS ticket |
| GET | `/.well-known/jwks.json` | Public | Token verification keys |
| GET | `/meta` | Public | `{api_version, client_contract: {min, max}, app_env, stock_location_mode, features}`. No secrets or hostnames. New clients read it to negotiate the contract and adapt the stock UX |
| GET/DELETE | `/admin/users` | Admin | List/delete client users (delete also closes the user's WebSocket sessions) |
| POST | `/admin/users` | Admin | Create a client-scope operator `{username, password}`; 409 if the username exists |
| POST | `/admin/users/{username}/password` | Admin | Reset a client password `{password}`; revokes all refresh tokens and closes sockets; 404 for unknown or admin accounts |
| GET | `/admin/history/outbound` | Admin | Closed scans, newest first, paged like order history (`limit`/`offset`, `X-Total-Count`) |
| GET | `/admin/history/shopee/orders` | Admin | Completed order history, most recently completed first. `?limit=` (1–2000, default 500) and `&offset=`; the `X-Total-Count` header gives the total |
| GET | `/admin/export/scans` | Admin | Open scans CSV |
| GET | `/admin/export/stocks` | Admin | Inventory CSV |
| DELETE | `/admin/clear/outbound-items` | Admin | Permanently clear scan records |
| GET | `/admin/bom/headers` | Admin | Standard and marketplace BOM roots |
| GET | `/admin/bom/tree` | Admin | BOM tree by `sku` or `shopee_id` (supports optional `qty` multiplier, default 1) |
| POST | `/admin/shopee-config/unlock` | Admin | Create 2-minute config session |
| GET/POST | `/admin/shopee-config` | Admin + `X-Config-Token` header | Read/update Shopee tokens (the token was a `?token=` query parameter before v0.5) |
| POST | `/admin/shopee-config/lock` | Admin + `X-Config-Token` header | End config session |
| GET/POST | `/outbound` | User | List/create open scans |
| POST | `/outbound/close` | Admin | Close scans and complete orders |
| GET | `/items/find` | User | Search SKU, name, or barcode (uses barcode resolution pipeline) |
| GET | `/stocks` | User | List inventory |
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

Valid types are `users_update`, `outbound_update`, `shopee_orders_update`,
`pick_item_entries_update`, `stocks_update`, and `error`. Clients should ignore
unknown future event types and reconnect with a newly issued ticket.

**Frame rule (client contract v1):** `data` is always a JSON array of objects, for every
type and every audience, because the v1 apps parse `data` before they read `type`. Error
frames follow the rule too:

```json
{"type": "error", "data": [{"detail": "Unknown command: foo"}]}
```

`users_update` items contain only `username` and `scope`.
