# Operations

## Configuration

The API checks `/run/secrets/<lowercase-name>`, then the matching environment
variable. Never commit `.env`, `.secrets`, Shopee tokens, or RSA keys.

| Name | Required | Notes |
| --- | --- | --- |
| `DATABASE_URL` | Production | `postgresql+psycopg://...`; localhost is rewritten to Compose service `db` |
| `REDIS_URL` | Yes | Compose uses `redis://redis:6379/0` |
| `ADMIN_USERNAME` | Yes | Seeded admin username; fallback is `admin` |
| `ADMIN_PASSWORD` | Yes | Seeded password; fallback `admin` logs a security warning |
| `PARTNER_ID`, `PARTNER_KEY`, `SHOP_ID` | Shopee sync | Shopee application/shop credentials |
| `SHOPEE_URL` | Shopee sync | OpenAPI host without a trailing path |
| `CORS_ORIGINS` | Public web | Comma-separated exact origins; `*` disables credentialed CORS |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`; default `INFO` |
| `LOG_FORMAT` | No | `json` (default) or `text` |
| `LOG_TO_FILE` | No | Default `true`; disable in immutable containers if stdout is collected |
| `LOG_DIR` | No | Default `temp/logs` |

The Flutter apps require `BASE_URL` and `WS_URL`. Use HTTPS/WSS in production.

## Deployment

```bash
cd backend
docker compose config --quiet
docker compose up --build -d
docker compose logs -f server
```

The server container runs `alembic upgrade head` before Uvicorn. A migration
failure prevents startup, which is safer than serving against an unknown schema.
Use a single API worker until WebSocket/cache coordination moves to Redis.

## Logging and auditability

JSON logs contain timestamp, level, logger, event name, request ID, HTTP method,
path, status, and duration where applicable. `X-Request-ID` is accepted from the
caller or generated per request and returned in the response. Exceptions include
stack traces. Tokens and outbound label contents are deliberately excluded.

The rotating local file is capped at 10 MiB with five backups. Container
deployments should ship stdout to centralized storage and set retention there.
Useful event names include `http.request.*`, `domain.error`,
`outbound.scan.*`, `outbound.scans.cleared`, and `websocket.*`.

## Backups

Back up all three durable assets together:

1. PostgreSQL data (`db-data`) for business state.
2. Redis data (`redis-data`) for Shopee credentials.
3. `backend/data/keys` for active JWT verification/signing keys.

Test restoration regularly. Restoring the database without key files forces all
users to log in again. Restoring without Redis requires re-entering Shopee tokens.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| API fails before Uvicorn | `docker compose logs server`; validate database URL and Alembic status |
| WebSocket cannot connect | Redis health, `/auth/ws-token`, 30-second expiry, WS/WSS URL |
| Tokens suddenly invalid | Persistent `data/keys`, clock synchronization, JWKS reachability |
| Shopee sync repeats/fails | partner/shop config, admin token screen, cache reset endpoint, upstream request IDs |
| Browser CORS rejection | exact scheme/host/port in `CORS_ORIGINS` |
| Inventory transfer rejected | source location exists and holds at least the requested quantity |

For an incident, capture the response `X-Request-ID`, UTC time, endpoint, status,
and relevant Shopee request ID. Do not paste bearer or Shopee tokens into tickets.

## Security checklist

- Replace fallback admin credentials before first startup.
- Restrict `CORS_ORIGINS`; terminate TLS at the ingress.
- Do not expose PostgreSQL or Redis ports outside a trusted network.
- Persist key files with owner-only permissions and rotate leaked credentials.
- Export required scan history before using the destructive clear endpoint.
- Monitor repeated authentication failures, config unlocks, and cache resets.
