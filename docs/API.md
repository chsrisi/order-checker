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
| POST | `/auth/register` | Public | Create client account and tokens |
| POST | `/auth/login` | Public | Operator login |
| POST | `/auth/admin` | Public | Admin-only login |
| POST | `/auth/refresh` | Public | Rotate refresh token pair |
| POST | `/auth/logout` | Public | Delete refresh-token record |
| POST | `/auth/ws-token` | User | Create 30-second one-use WS ticket |
| GET | `/.well-known/jwks.json` | Public | Token verification keys |
| GET/DELETE | `/admin/users` | Admin | List/delete client users |
| GET | `/admin/history/outbound` | Admin | Closed scan history |
| GET | `/admin/history/shopee/orders` | Admin | Completed order history |
| GET | `/admin/export/scans` | Admin | Open scans CSV |
| GET | `/admin/export/stocks` | Admin | Inventory CSV |
| DELETE | `/admin/clear/outbound-items` | Admin | Permanently clear scan records |
| GET | `/admin/bom/headers` | Admin | Standard and marketplace BOM roots |
| GET | `/admin/bom/tree` | Admin | BOM tree by `sku` or `shopee_id` |
| POST | `/admin/shopee-config/unlock` | Admin | Create 2-minute config session |
| GET/POST | `/admin/shopee-config` | Admin + config token | Read/update Shopee tokens |
| POST | `/admin/shopee-config/lock` | Admin | End config session |
| GET/POST | `/outbound` | User | List/create open scans |
| POST | `/outbound/close` | Admin | Close scans and complete orders |
| GET | `/items/find` | User | Search SKU, name, or barcode |
| GET | `/stocks` | User | List inventory |
| POST | `/stocks/update` | User | Set/add/transfer inventory |
| GET | `/shopee/orders` | User | Synchronize active orders |
| POST | `/shopee/orders/acquire` | User | Atomically claim an order |
| POST | `/shopee/reset-cache-state` | Admin | Reset sync circuit/cache |
| GET/POST | `/pick-items` | User | List/create pick entries |
| POST | `/pick-items/{id}/assign` | User | Assign quantity to claimed order |
| POST | `/pick-items/unassign` | User | Return quantity to general picks |
| DELETE | `/pick-items/{id}` | User | Delete owned entry; admin may delete any |

Request and response fields, examples, constraints, and error responses are kept
in OpenAPI so generated clients do not need to duplicate this table.

## Errors

Validation failures use FastAPI's `422` response. Authentication failures use
`401`; insufficient scope uses `403`; missing resources use `404`; ownership or
duplicate conflicts use `409`. Domain errors have one stable envelope:

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
