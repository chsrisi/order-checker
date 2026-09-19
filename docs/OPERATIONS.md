# Operations

## Configuration

The backend distinguishes between **non-sensitive operational configurations** (passed via environment files such as `.env` or `--env-file`) and **sensitive secrets** (injected securely as Docker Secrets or secret files).

Configuration lookup order:
1. Docker Secrets at `/run/secrets/<lowercase_name>`
2. Environment variables (loaded via `--env-file .env` or system environment)
3. Application default values

> [!CAUTION]
> Never commit `.env`, `.secrets/`, private RSA keys (`data/keys`), or active Shopee tokens to version control. Both `.env` and `.secrets/` are listed in `.gitignore`.

---

## Secret Management: File-Backed vs. Environment-Backed

Docker Compose supports supplying secrets either as **Environment-Backed Secrets** (`environment: <VAR>`) or **File-Backed Secrets** (`file: <PATH>`). 

### Secret Classification & Sensitivity Tiers

| Secret / Config Key | Sensitivity | Recommended Source | Current Setup in `compose.yaml` | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `postgres_password` | **Super Sensitive** | **File-backed** (`.secrets/postgres_password`) | `file: ./.secrets/postgres_password` | Master superuser password for the PostgreSQL container. |
| `app_password` | **Super Sensitive** | **File-backed** (`.secrets/app_password`) | `file: ./.secrets/app_password` | Application role (`bh_backend`) database password used by `init.sql`. |
| `database_url` | **Super Sensitive** | **File-backed** (`.secrets/database_url`) | `environment: DATABASE_URL` *(upgradeable)* | Full connection URI containing credentials, database name, and port. |
| `partner_key` | **Super Sensitive** | **File-backed** (`.secrets/partner_key`) | `environment: PARTNER_KEY` *(upgradeable)* | Shopee OpenAPI HMAC cryptographic signing secret key. |
| `admin_password` | **Super Sensitive** | **File-backed** (`.secrets/admin_password`) | `environment: ADMIN_PASSWORD` *(upgradeable)* | Initial admin password seeded into the database on first startup. |
| RSA Key Pairs (`.key`) | **Super Sensitive** | **Volume Mount** (`KEYS_VOLUME`) | Mounted `./data/keys` -> `/app/data/keys` | Asymmetric RS256 private keys generated/rotated by `KeyManager`. |
| `partner_id` | Medium | Env-backed / Secret | `environment: PARTNER_ID` | Shopee partner account identifier. |
| `shop_id` | Medium | Env-backed / Secret | `environment: SHOP_ID` | Shopee shop identifier. |
| `shopee_url` | Low | Env-backed (`.env`) | `environment: SHOPEE_URL` | Shopee Open Platform endpoint URL. |
| `admin_username` | Low | Env-backed (`.env`) | `environment: ADMIN_USERNAME` | Initial seeded administrator username. |
| `redis_url` | Low | Env-backed (`.env`) | `environment: REDIS_URL` | Internal container network address for Redis cache. |
| Operational Knobs (`PORT`, `LOG_*`, TTLs, CORS) | Non-sensitive | Env-backed (`.env`) | `env_file: .env` / `environment:` | Operational tuning, port mapping, and log levels. |

---

### Why Use File-Backed Secrets for Super-Sensitive Secrets?

In production and hardened deployments, **file-backed secrets (`file: ./.secrets/<name>`) should always be used for super-sensitive secrets** rather than environment variables or environment-backed secrets:

1. **Immunity to Process Inspection (`docker inspect`)**: Environment variables passed to containers can be read in plain text by any user with Docker daemon access via `docker inspect <container>`. Docker Secrets mounted at `/run/secrets/` are never shown in `docker inspect`.
2. **Immunity to Environment Dumps & Leakage**: Environment variables are exposed via `/proc/<pid>/environ`, inherited by spawned subprocesses, and frequently captured in crash logs, APM diagnostics, or Sentry error traces.
3. **Least Privilege & Memory-Only Storage**: Docker Secrets are mounted as in-memory `tmpfs` files with read-only permissions (`mode: 444`), readable only by the non-root application user (`appuser`, UID 10001).
4. **Clean Decoupling**: Configuration files (`.env`) can safely be shared across operations teams for non-sensitive tweaks without exposing database or third-party API master keys.

---

### Setting Up File-Backed Secrets

To configure file-backed secrets for all super-sensitive credentials:

1. Create the local secrets directory:
   ```bash
   mkdir -p backend/.secrets
   ```
2. Populate secret files with trimmed plaintext values (one secret per file, no trailing newlines):
   ```bash
   echo "super_secret_pg_pass" > backend/.secrets/postgres_password
   echo "super_secret_app_pass" > backend/.secrets/app_password
   echo "postgresql+psycopg://bh_backend:super_secret_app_pass@backend-postgres-1:5432/bakingholic" > backend/.secrets/database_url
   echo "shopee_live_partner_secret_key" > backend/.secrets/partner_key
   echo "strong_initial_admin_password" > backend/.secrets/admin_password
   ```
3. Update the `secrets` section in `backend/compose.yaml`:
   ```yaml
   secrets:
     postgres_password:
       file: ./.secrets/postgres_password
     app_password:
       file: ./.secrets/app_password
     database_url:
       file: ./.secrets/database_url
     partner_key:
       file: ./.secrets/partner_key
     admin_password:
       file: ./.secrets/admin_password
   ```
4. The application's `get_config_value(key)` automatically checks `/run/secrets/<key>` first and seamlessly consumes the file content.


---

### 1. Deployment & Compose Customization

| Name | Type | Default | Required | Notes |
| --- | --- | --- | --- | --- |
| `PORT` | int | `8000` | No | Host port mapped to the FastAPI application (`${PORT:-8000}:8000`). |
| `DB_PORT` | int | `5432` | No | Host port mapped to the PostgreSQL service (`${DB_PORT:-5432}:5432`). |
| `REDIS_PORT` | int | `6379` | No | Host port mapped to the Redis service (`${REDIS_PORT:-6379}:6379`). |
| `WEB_PORT` | int | `3000` | No | Host port mapped to the Frontend Admin web service (`${WEB_PORT:-3000}:80`). |
| `DB_CONTAINER_NAME` | string | `backend-postgres-1` | No | Custom container name for the PostgreSQL service (`${DB_CONTAINER_NAME:-backend-postgres-1}`). |
| `REDIS_CONTAINER_NAME` | string | `backend-redis-1` | No | Custom container name for the Redis service (`${REDIS_CONTAINER_NAME:-backend-redis-1}`). |
| `ADMIN_WEB_CONTAINER_NAME` | string | `admin-web-1` | No | Custom container name for the Frontend Admin web service (`${ADMIN_WEB_CONTAINER_NAME:-admin-web-1}`). |
| `KEYS_VOLUME` | string | `./data/keys` | No | Host path mounted to container `/app/data/keys` for persistent JWT key storage. |
| `LOGS_VOLUME` | string | `./logs` | No | Host path mounted to container `/app/logs` for persistent file logs. |
| `ENV_FILE` | string | `.env` | No | Environment file path passed to docker compose service definition. |

---

### 2. Database & Cache Infrastructure

| Name | Type | Default | Required | Notes |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | string | `sqlite:///./local.db` | Production | PostgreSQL connection string (`postgresql+psycopg://user:pass@host:5432/dbname`). In Docker, `localhost`/`127.0.0.1`/`db` hostnames are automatically rewritten to `DB_HOST`. In production, prefer passing via Docker Secret `database_url`. |
| `DB_HOST` | string | `backend-postgres-1` | No | Docker network hostname for the PostgreSQL service used in database URL host resolution. |
| `REDIS_URL` | string | `redis://localhost:6379/0` | Yes | Redis connection URL (`redis://redis:6379/0` in Compose). Used for dynamic token storage, WebSocket tickets, and admin configuration sessions. |

---

### 3. Admin & Account Initialization

| Name | Type | Default | Required | Notes |
| --- | --- | --- | --- | --- |
| `ADMIN_USERNAME` | string | `admin` | Yes | Username of the initial administrator account seeded into the database on startup. |
| `ADMIN_PASSWORD` | string | `admin` | Yes | Password for the initial administrator. Fallback `admin` emits a security warning on startup. Prefer passing via Docker Secret `admin_password`. |
| `CORS_ORIGINS` | string | `*` | No | Comma-separated list of allowed origins (e.g., `http://localhost:3000,http://example.com`). Setting to `*` disables credentialed CORS. |

---

### 4. Application Logging (Two-Tier Architecture)

Logging is split into a console handler (stdout / docker logs) and an optional rotating file handler.

| Name | Type | Default | Required | Notes |
| --- | --- | --- | --- | --- |
| `LOG_LEVEL` | string | `WARNING` | No | General / fallback log level for console output (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `LOG_LEVEL_CONSOLE` | string | `WARNING` | No | Explicit log level for stdout / Docker console logs. Defaults to `WARNING` to keep container stdout clean. |
| `LOG_LEVEL_FILE` | string | `DEBUG` | No | Explicit log level for rotating file logs (`backend.log`). Defaults to `DEBUG` for full diagnostic capture. |
| `LOG_FORMAT` | string | `json` | No | `json` for structured JSON logs in container environments, or `text` for readable local development. |
| `LOG_TO_FILE` | bool | `true` | No | Enables rotating file logger. Set to `false` in environments collecting only stdout. |
| `LOG_DIR` | string | `logs` | No | Filesystem directory where rotating file logs (`backend.log`) are stored. |
| `LOG_MAX_BYTES` | int | `10485760` | No | Maximum file size in bytes before log rotation triggers (default: 10 MiB). |
| `LOG_BACKUP_COUNT`| int | `5` | No | Number of rotated log backup files to retain. |

---

### 5. Application Versioning, Security & JWT Key Management

| Name | Type | Default | Required | Notes |
| --- | --- | --- | --- | --- |
| `API_VERSION` | string | `0.3.0-alpha` | No | Application/API version exposed via FastAPI OpenAPI metadata (`schema["info"]["version"]`). |
| `JWT_VERSION` | string | `v0.3a` | No | Version tag embedded in default JWT audience and issuer claims (`api.bakingholic:<version>` and `auth.bakingholic:<version>`). |
| `KEYS_DIR` | string | `data/keys` | No | Directory where RSA key pairs (`.key` and `.pub`) are stored and rotated. Mounted as a persistent host volume in Docker. |
| `KEY_CACHE_TTL_SECONDS` | int | `300` | No | In-memory cache duration for public JWKS keys before re-scanning disk (default: 5 minutes). |
| `ACCESS_TTL_SECONDS` | int | `900` | No | Lifetime of issued JWT access tokens in seconds (default: 15 minutes). |
| `REFRESH_TTL_SECONDS` | int | `86400` | No | Lifetime of issued refresh tokens in seconds (default: 24 hours). |
| `REFRESH_CLEANUP_INTERVAL_SECONDS` | int | `3600` | No | Interval in seconds for background task purging expired/revoked refresh tokens from PostgreSQL (default: 1 hour). |
| `JWT_ALGORITHM` | string | `RS256` | No | Signing algorithm for JWT access and refresh tokens. |
| `JWT_AUDIENCE` | string | `api.bakingholic:<JWT_VERSION>` (`api.bakingholic:v0.3a`) | No | Required JWT `aud` claim during token creation and verification. Defaults to `api.bakingholic:${JWT_VERSION}`. |
| `JWT_ISSUER` | string | `auth.bakingholic:<JWT_VERSION>` (`auth.bakingholic:v0.3a`) | No | Required JWT `iss` claim during token creation and verification. Defaults to `auth.bakingholic:${JWT_VERSION}`. |
| `JWT_LEEWAY_SECONDS` | float | `30.0` | No | Clock-skew leeway in seconds for JWT verification (`nbf`/`exp`). |
| `WS_TICKET_TTL_SECONDS` | int | `30` | No | Validity duration in seconds for one-time WebSocket connection tickets generated via `/auth/ws-token`. |
| `SHOPEE_CONFIG_UNLOCK_TTL_SECONDS` | int | `120` | No | Validity duration in seconds for temporary admin configuration unlock tokens (`cfg_token:*`). |

---

### 6. Shopee OpenAPI & Synchronization

| Name | Type | Default | Required | Notes |
| --- | --- | --- | --- | --- |
| `PARTNER_ID` | string | - | Shopee sync | Shopee OpenAPI Partner ID (e.g. `123456`). |
| `PARTNER_KEY` | string | - | Shopee sync | Shopee OpenAPI Partner HMAC signing key. Prefer passing via Docker Secret `partner_key`. |
| `SHOP_ID` | string | - | Shopee sync | Shopee Shop ID identifier. |
| `SHOPEE_URL` | string | - | Shopee sync | Base URL of Shopee Open Platform (`https://openplatform.sandbox.test-stable.shopee.sg` or `https://partner.shopeemobile.com`). |
| `SHOPEE_CACHE_TTL_SECONDS` | int | `120` | No | Process-local cache TTL in seconds for synchronized active orders (default: 2 minutes). |
| `SHOPEE_MAX_CONCURRENCY` | int | `5` | No | Maximum concurrent HTTP requests made against Shopee OpenAPI endpoints. |
| `SHOPEE_MAX_RETRIES` | int | `3` | No | Maximum retry attempts when hitting HTTP 429 or rate-limiting responses from Shopee. |
| `SHOPEE_BACKOFF_DELAY` | float | `1.5` | No | Initial exponential backoff delay in seconds for rate-limited Shopee requests. |
| `SHOPEE_PAGE_SIZE` | int | `100` | No | Number of order SNs requested per page in `/api/v2/order/get_order_list`. |
| `SHOPEE_ORDER_CHUNK_SIZE` | int | `50` | No | Maximum number of order SNs per batch detail lookup (`/api/v2/order/get_order_detail`). |
| `SHOPEE_PACKAGE_CHUNK_SIZE` | int | `50` | No | Maximum number of packages per batch tracking lookup (`/api/v2/logistics/get_mass_tracking_number`). |
| `SHOPEE_SYNC_WINDOW_DAYS` | int | `2` | No | Time window in days backwards from `now` to pull active/recent Shopee orders (default: 2 days). |

---

### 7. Mock, Bypass & Offline Development Settings

| Name | Type | Default | Required | Notes |
| --- | --- | --- | --- | --- |
| `MOCK_ORDER_BYPASS` | bool (int/str) | `0` (false) | No | Set to `1`, `true`, `yes`, or `on` to bypass Shopee OpenAPI synchronization failures and serve local/seeded database orders. Default `0` raises exceptions on sync failure. |
| `SINGLE_LOCATION_STOCK_BYPASS` | bool (int/str) | `0` (false) | No | Set to `1`, `true`, `yes`, or `on` to restrict inventory items to a single warehouse location. Default `0` preserves standard multi-location stock. |

---

## Mock Order Bypass & Offline Development

### Purpose & Behavior
During local development or UI offline testing (e.g. without valid Shopee API partner credentials or sandbox connectivity), fetching live orders from Shopee would fail and return HTTP 500 errors to clients.

The **Mock Order Bypass** allows the server to swallow Shopee API synchronization failures and fall back to serving whatever orders currently exist in the PostgreSQL database (`shopee.orders`), including test orders seeded directly via `temp/seed_mock_order.py`.

- **`MOCK_ORDER_BYPASS=0` (default)**: Strict production behavior. If the Shopee OpenAPI is unreachable or returns an error, the exception is raised immediately to the caller.
- **`MOCK_ORDER_BYPASS=1` (or `true`)**: Development mode. If the Shopee API call fails, the failure is logged as a warning (`shopee.sync.fallback`), `cache_mgr.mark_synced()` is skipped (allowing subsequent requests to retry), and existing database orders are returned and broadcast to connected WebSocket clients.

### Seeding a Mock Order
To insert a sample test order (`250801MOCK0001`) with recipient address, items, and logistics tracking:
```bash
cd backend
uv run temp/seed_mock_order.py
```

### Complete Removal Instructions (Code Cleanup)
If the project no longer requires the mock order bypass mechanism and you wish to permanently remove it at the codebase level (rather than just setting `MOCK_ORDER_BYPASS=0`):

1. **Modify `backend/src/services/shopee_service.py`**:
   - In `sync_shopee_orders()`, remove the `try:` / `except Exception:` block wrapper around the Shopee API fetch tasks. Call the API fetch, detail chunk queries, `queries.sync_shopee_orders_to_db(chunk_results)`, and `cache_mgr.mark_synced()` directly at the top level of the lock block.
   - Remove the `MOCK_ORDER_BYPASS = get_config_bool("MOCK_ORDER_BYPASS", False)` variable and unused `get_config_bool` import if applicable.
2. **Clean `.env.example` and `.env`**:
   - Delete the `MOCK_ORDER_BYPASS` configuration variable and its documentation section.
3. **Purge Seeded Database Mock Orders**:
   - Run the following SQL statements against PostgreSQL:
     ```sql
     DELETE FROM shopee.order_recipient_address WHERE order_sn = '250801MOCK0001';
     DELETE FROM shopee.order_info               WHERE order_sn = '250801MOCK0001';
     DELETE FROM shopee.order_item_list          WHERE order_sn = '250801MOCK0001';
     DELETE FROM shopee.orders                   WHERE order_sn = '250801MOCK0001';
     ```
4. **Remove the Mock Seed Script**:
   - Delete `backend/temp/seed_mock_order.py`.

---

## Single-Location Stock Bypass

### Purpose & Behavior
The default inventory data model allows a many-to-one relationship between stock records and warehouse items (i.e., an item can be distributed across multiple physical storage bins or shelf locations).

The **Single-Location Stock Bypass** (`SINGLE_LOCATION_STOCK_BYPASS=1`) enforces an operational constraint where an item can only exist in at most **one** warehouse location:

- **`SINGLE_LOCATION_STOCK_BYPASS=0` (default)**: Multi-location stock enabled. Adding or setting stock at location `A` does not affect stock at location `B`.
- **`SINGLE_LOCATION_STOCK_BYPASS=1` (or `true`)**: Single-location bypass enabled:
  - **Add or Set without Location (`location=None`)**: Updates or sets the quantity in the item's sole existing location (or default item location if none exists).
  - **Add or Set with Location (`location="LOC-X"`)**: Automatically transfers all existing stock from other locations to `LOC-X` first (deleting the old location records), and then applies the `add` or `set` operation at `LOC-X`.
  - **Move / Transfer (`move_to="LOC-Y"`)**: Transfers all stock for that item to `LOC-Y`.

### Complete Removal Instructions (Code Cleanup)
If the project permanently moves away from single-location bypass support:

1. **Modify `backend/src/services/queries/stocks.py`**:
   - Remove `_is_single_location_bypass_active()`, `SINGLE_LOCATION_STOCK_BYPASS`, and the `if _is_single_location_bypass_active():` branches in `update_or_move_stock` and `get_or_merge_stock`.
2. **Clean `.env.example` and `.env`**:
   - Remove `SINGLE_LOCATION_STOCK_BYPASS`.
3. **Update Documentation**:
   - Remove the Single-Location Stock Bypass section from `docs/OPERATIONS.md`.

---

## Shopee Token Storage & Initial Seeding

Shopee OpenAPI authentication uses dynamic OAuth access and refresh tokens:

1. **In-Memory Dynamic Storage (Redis)**:
   - Live tokens are stored in Redis under `shopee:access_token` and `shopee:refresh_token`.
   - The backend automatically refreshes the `access_token` using the `refresh_token` when expired.
   - Administrators can view and update tokens live at runtime via the protected Admin UI (`/admin/shopee-config`) without restarting the service.
   - Because tokens are dynamic, they are **omitted** from `.env.example`.

2. **Cold Start & Initial Token Seeding**:
   - On a fresh deployment where Redis is empty, the token manager checks for optional configuration fallback values:
     - `SHOPEE_ACCESS_TOKEN` or `ACCESS_TOKEN`
     - `SHOPEE_REFRESH_TOKEN` or `REFRESH_TOKEN`
   - If provided via `.env` / `--env-file` or Docker secrets, these values are automatically seeded into Redis on first access.
   - Subsequent token refreshes and manual updates in the Admin UI will update Redis directly.

| Seed Variable | Fallback Alias | Storage Target | Description |
| --- | --- | --- | --- |
| `SHOPEE_ACCESS_TOKEN` | `ACCESS_TOKEN` | Redis `shopee:access_token` | Optional initial access token seed value for cold startup |
| `SHOPEE_REFRESH_TOKEN` | `REFRESH_TOKEN` | Redis `shopee:refresh_token` | Optional initial refresh token seed value for cold startup |


---

## Deployment & Running

### Using Docker Compose

```bash
cd backend
# 1. Provide non-sensitive configuration in .env or pass --env-file:
cp .env.example .env

# 2. Provide secrets in backend/.secrets/ (postgres_password, app_password)
# 3. Start services with Docker Compose:
docker compose --env-file .env up --build -d

# 4. View container logs (filtered to WARNING+ by default):
docker compose logs -f server
```

The server container applies Alembic migrations on startup before serving the API on `${PORT:-8000}`.
Keys and logs are persisted to host directories via configurable volume binds (`KEYS_VOLUME` and `LOGS_VOLUME`).

### Running with Docker CLI (Standalone)

When running the container standalone, pass configs via `--env-file` and mount secrets to `/run/secrets/`:

```bash
docker run -d \
  --name order-checker-api \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/data/keys:/app/data/keys \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/.secrets/app_password:/run/secrets/app_password:ro \
  -v $(pwd)/.secrets/partner_key:/run/secrets/partner_key:ro \
  order-checker-backend:latest
```

---

## Frontend Admin Web Hosting & Deployment

The Frontend Admin application (`frontend/admin`) can be hosted as a containerized web application using Nginx on Alpine Linux.

### Configuration & Security Policy

Configuration is managed via `.env` in `frontend/admin/.env`, modeled after `frontend/admin/.env.example`.

> [!CAUTION]
> **Active `.env` Inspection & Secret Isolation**:
> Active `.env` files in `backend/` and `frontend/admin/` contain live secrets, sensitive hosts, and production configurations.
> Automated agents, scripts, and code analysis tools **must only inspect `.env.example`** templates. Never commit active `.env` files.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `BASE` | Empty in Docker | Optional hostname or IP for direct backend access. |
| `BASE_URL` | `/` in Docker | Full HTTP/HTTPS base URL for backend REST API calls. |
| `WS_URL` | `/` in Docker | Full WS/WSS base URL for backend WebSocket real-time updates. |
| `WEB_PORT` | `80` (container) / `3000` (host) | Nginx listening port. |
| `WEB_HOST` | `0.0.0.0` | Interface binding address for the web server. |
| `WEB_BASE_HREF` | `/` | Base href prefix if hosted behind a reverse proxy subpath. |

### Dynamic Runtime Environment Injection

Flutter Web loads environment variables via an HTTP request to `/assets/.env`. When the Docker container starts, an entrypoint script (`/docker-entrypoint.d/40-generate-env.sh`) writes `/usr/share/nginx/html/assets/.env` using the runtime environment variables passed to the container (`BASE_URL`, `WS_URL`, etc.). By default, both URLs are `/`, so Nginx proxies API and WebSocket requests on the same origin used to open the web page. A mounted `/app/.env` overrides the generated file.

### Deploying Frontend Admin with Docker Compose

To run the admin web portal alongside the backend API, database, and Redis:
```bash
cd backend
docker compose --env-file .env up -d admin-web
```
By default, the web interface is exposed on `http://localhost:${WEB_PORT:-3000}`.

No CORS setting is needed for the default same-origin proxy. If `BASE_URL` and `WS_URL` point directly at another origin, allow the web origin with `CORS_ORIGINS`.

### Standalone Docker Deployment

```bash
cd frontend/admin
# Build container image
docker build -t order-checker-admin-web .

# Run standalone container
docker run -d \
  --name admin-web \
  -p 3000:80 \
  --add-host=host.docker.internal:host-gateway \
  -e BACKEND_HOST=host.docker.internal \
  order-checker-admin-web
```

For standalone Docker, `BACKEND_HOST` must resolve inside the web container. The example maps the Docker host to `host.docker.internal`; alternatively, place both containers on the same Docker network and use the backend service name.

---

## Backups & Persistence

Back up all three durable assets together:

1. PostgreSQL data (`db-data`) for relational business state.
2. Redis data (`redis-data`) for live Shopee credentials.
3. Key storage directory (`KEYS_VOLUME`, default `./data/keys`) for active JWT signing and verification keys.

Test restoration regularly. Restoring the database without key files forces all users to log in again. Restoring without Redis requires re-entering Shopee tokens via the Admin UI or seed variables.

---

## Troubleshooting

| Symptom | Check |
| --- | --- |
| API fails before Uvicorn | `docker compose logs server`; validate database URL and Alembic status |
| WebSocket cannot connect | Redis health, `/auth/ws-token`, `WS_TICKET_TTL_SECONDS` expiry, WS/WSS URL |
| Tokens suddenly invalid | Persistent `KEYS_VOLUME` (`data/keys`), clock synchronization, JWKS reachability |
| Shopee sync repeats/fails | Partner/shop credentials, admin token screen, cache reset endpoint, upstream request IDs |
| Browser CORS rejection | Exact scheme/host/port in `CORS_ORIGINS` |
| Detailed logs missing in stdout | Stdout defaults to `WARNING`. Detailed `DEBUG` logs are recorded in `logs/backend.log` or set `LOG_LEVEL_CONSOLE=DEBUG` |
