# Operations

## Configuration

The backend distinguishes between **non-sensitive operational configurations** (passed via environment files such as `.env` or `--env-file`) and **sensitive secrets** (injected securely as Docker Secrets or secret files).

Configuration lookup order (`backend/src/config.py: get_config_value`); the first non-empty value wins:
1. Secret files named `<lowercase_name>`, in this order: `$SECRETS_DIR/` (only if `SECRETS_DIR` is set),
   `/run/secrets/` (Docker Secrets), `backend/.secrets/`, `./.secrets/` (current directory)
2. Environment variables (loaded via `--env-file .env`, a `.env` found by `python-dotenv`, or the system environment)
3. Application default values

`SECRETS_DIR` is optional and only adds a directory in front of the list. Inside Docker, a
`DATABASE_URL` host of `localhost`, `127.0.0.1`, `db`, `postgres-1` or `postgres_container` is
rewritten to `DB_HOST` (default `backend-postgres-1`).

> [!CAUTION]
> Never commit `.env`, `.secrets/`, private RSA keys (`data/keys`), or active Shopee tokens to version control. Both `.env` and `.secrets/` are listed in `.gitignore`.

---

## Environment Profiles

`APP_ENV` selects the startup rules. Allowed values are `development`, `staging` and `production`.

| Profile | Startup rules | Shopee host | Registration default | API docs default |
|---|---|---|---|---|
| `development` | local defaults allowed | sandbox (live needs an explicit override) | on | on |
| `staging` | production rules | sandbox (live needs an explicit override) | off | off |
| `production` | production rules | live allowed | off | off |

**Fail closed.** If `APP_ENV` is unset or unknown, production rules apply. Local setups set
`APP_ENV=development` explicitly (`.env.example`, `compose.test.yaml`). The base
`compose.yaml` does not set it, so production deployments use the
`compose.prod.yaml` override (see Deployment).

Under production rules the server **refuses to start**, listing every problem at once, if any of these hold:

- `ADMIN_PASSWORD` is empty, `admin`, or the `.env.example` placeholder
- `CORS_ORIGINS` contains `*`, or `CORS_ORIGIN_REGEX` is set. Leave CORS empty: the admin
  web app is served same-origin through nginx and the operator client is native, so neither
  needs CORS. If you must allow an origin, list it exactly.
- `MOCK_ORDER_BYPASS` is on
- `DATABASE_URL` is missing or SQLite (no silent SQLite fallback)
- `REDIS_URL` has no password
- `ALLOW_REGISTRATION` is on
- `RECIPIENT_RETENTION_DAYS` is above 90 (Shopee DPP maximum)

`STOCK_LOCATION_MODE` is deliberately **not** checked: both modes are valid in production.

**Live Shopee outside production.** In `development` and `staging`, startup refuses a live
Shopee host (any Shopee host other than the sandbox) unless `ALLOW_LIVE_SHOPEE_IN_NONPROD=1`
is set. Non-production work uses the sandbox and synthetic data (delta A-10: Shopee ToS and
DPP). Set the override only deliberately and temporarily.

## Secret Management: File-Backed vs. Environment-Backed

Docker Compose supports supplying secrets either as **Environment-Backed Secrets** (`environment: <VAR>`) or **File-Backed Secrets** (`file: <PATH>`). 

### Secret Classification & Sensitivity Tiers

| Secret / Config Key | Sensitivity | Recommended Source | `compose.yaml` (dev) | `compose.prod.yaml` | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `postgres_password` | **Super Sensitive** | **File-backed** (`.secrets/postgres_password`) | `file: ./.secrets/postgres_password` | same | Master superuser password for the PostgreSQL container. |
| `app_password` | **Super Sensitive** | **File-backed** (`.secrets/app_password`) | `file: ./.secrets/app_password` | same | Application role (`bh_backend`) database password used by `init.sql`. |
| `database_url` | **Super Sensitive** | **File-backed** (`.secrets/database_url`) | `environment: DATABASE_URL` | `file: ./.secrets/database_url` | Full connection URI containing credentials, database name, and port. |
| `partner_key` | **Super Sensitive** | **File-backed** (`.secrets/partner_key`) | `environment: PARTNER_KEY` | `file: ./.secrets/partner_key` | Shopee OpenAPI HMAC cryptographic signing secret key. |
| `admin_password` | **Super Sensitive** | **File-backed** (`.secrets/admin_password`) | `environment: ADMIN_PASSWORD` | `file: ./.secrets/admin_password` | Initial admin password seeded into the database on first startup. |
| RSA Key Pairs (`.key`) | **Super Sensitive** | **Volume Mount** (`KEYS_VOLUME`) | Mounted `./data/keys` -> `/app/data/keys` | same | Asymmetric RS256 private keys generated/rotated by `KeyManager`. |
| `partner_id` | Medium | Env-backed / Secret | `environment: PARTNER_ID` | same | Shopee partner account identifier. |
| `shop_id` | Medium | Env-backed / Secret | `environment: SHOP_ID` | same | Shopee shop identifier. |
| `shopee_url` | Low | Env-backed (`.env`) | `environment: SHOPEE_URL` | same | Shopee Open Platform endpoint URL. |
| `admin_username` | Low | Env-backed (`.env`) | `environment: ADMIN_USERNAME` | same | Initial seeded administrator username. |
| `redis_url` | **Sensitive** (contains the Redis password in production) | Env-backed (dev) / **File-backed** (prod) | `environment: REDIS_URL` (no password) | `file: ./.secrets/redis_url` (with password) | Internal container network address for Redis cache. |
| Operational Knobs (`PORT`, `LOG_*`, TTLs, CORS) | Non-sensitive | Env-backed (`.env`) | `env_file: .env` / `environment:` | same; `APP_ENV=production`, `CORS_ORIGINS=` forced | Operational tuning, port mapping, and log levels. |

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
| `API_VERSION` | string | `[project].version` in `backend/pyproject.toml` | No | The backend version (OpenAPI `info.version`, later `GET /meta`) is read from `pyproject.toml`. This variable overrides it **in development only**; it is ignored with a warning elsewhere. |
| `JWT_VERSION` | string | — | No | **Deprecated and ignored** (logs a warning). Token identity now derives from `APP_ENV`. |
| `KEYS_DIR` | string | `data/keys` | No | Directory where RSA key pairs (`.key` and `.pub`) are stored and rotated. Mounted as a persistent host volume in Docker. |
| `KEY_CACHE_TTL_SECONDS` | int | `300` | No | In-memory cache duration for public JWKS keys before re-scanning disk (default: 5 minutes). |
| `KEY_RETENTION_SECONDS` | int | `REFRESH_TTL_SECONDS + ACCESS_TTL_SECONDS + JWT_LEEWAY_SECONDS` | No | How long a retired signing key stays published after its successor appears. It must cover the refresh-token lifetime, because refresh tokens are signed with the same keys. Lower values log idle devices out after a rotation. |
| `LOGIN_MAX_FAILURES` | int | `10` | No | Failed logins per username (case-insensitive) before `/auth/login` and `/auth/admin` return 429. Counted in Redis; if Redis is down, logins are allowed (fail open). |
| `LOGIN_LOCKOUT_SECONDS` | int | `900` | No | Failure-counting window and lockout duration. A successful login resets the counter. To unlock an operator early: `redis-cli DEL login_fail:<username>`. |
| `ACCESS_TTL_SECONDS` | int | `900` | No | Lifetime of issued JWT access tokens in seconds (default: 15 minutes). |
| `REFRESH_TTL_SECONDS` | int | `86400` | No | Lifetime of issued refresh tokens in seconds (default: 24 hours). |
| `REFRESH_CLEANUP_INTERVAL_SECONDS` | int | `3600` | No | Interval in seconds for background task purging expired/revoked refresh tokens from PostgreSQL (default: 1 hour). |
| `JWT_ALGORITHM` | string | `RS256` | No | Signing algorithm for JWT access and refresh tokens. |
| `JWT_AUDIENCE` | string | `api.bakingholic:<APP_ENV>` | No | Required JWT `aud` claim. Per environment, so development tokens are never accepted by production. **Changing it logs every device out**, so do it only in a planned relogin window (`docs/RELEASE.md`). |
| `JWT_ISSUER` | string | `auth.bakingholic:<APP_ENV>` | No | Required JWT `iss` claim; same rules as `JWT_AUDIENCE`. |
| `JWT_LEEWAY_SECONDS` | float | `30.0` | No | Clock-skew leeway in seconds for JWT verification (`nbf`/`exp`). |
| `WS_TICKET_TTL_SECONDS` | int | `30` | No | Validity duration in seconds for one-time WebSocket connection tickets generated via `/auth/ws-token`. |
| `SHOPEE_CONFIG_UNLOCK_TTL_SECONDS` | int | `120` | No | Validity duration in seconds for temporary admin configuration unlock tokens (`cfg_token:*`). |

**Key rotation lifecycle.** Every 24 hours the rotation task works in two stages:

1. It publishes the new `.pub` in the JWKS.
2. After `KEY_CACHE_TTL_SECONDS + 30` seconds it writes the new `.key`, and the new pair starts signing.

The previous pair stays on disk and in the JWKS until `KEY_RETENTION_SECONDS` (plus the cache window) has passed, so the JWKS normally lists 2–3 keys. An hourly check removes only expired pairs. It never removes the newest complete pair, and never a pending rotation.

If the server stops mid-rotation, it completes the half-written pair and removes nothing. Deploying during a rotation is therefore safe.

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
| `STOCK_LOCATION_MODE` | string | `multi` | No | `multi`: an item may have stock in several locations. `single`: at most one location per item. Both are valid in production. See "Stock Location Mode". |
| `SINGLE_LOCATION_STOCK_BYPASS`, `STOCK_SINGLE_LOCATION_BYPASS` | bool | unset | No | **Deprecated aliases** of `STOCK_LOCATION_MODE` (truthy = `single`). Used only when `STOCK_LOCATION_MODE` is unset; they log a deprecation warning. |

---

## Mock Order Bypass & Offline Development

### Purpose & Behavior
During local development or UI offline testing (e.g. without valid Shopee API partner credentials or sandbox connectivity), fetching live orders from Shopee would fail and return HTTP 500 errors to clients.

The **Mock Order Bypass** allows the server to swallow Shopee API synchronization failures and fall back to serving whatever orders currently exist in the PostgreSQL database (`shopee.orders`), including test orders seeded directly via `temp/seed_mock_order.py`.

- **`MOCK_ORDER_BYPASS=0` (default)**: Strict production behavior. If the Shopee OpenAPI is unreachable or returns an error, the exception is raised immediately to the caller.
- **`MOCK_ORDER_BYPASS=1` (or `true`)**: Development mode. If the Shopee API call fails, the failure is logged as a warning (`shopee.sync.fallback`), `cache_mgr.mark_synced()` is skipped (allowing subsequent requests to retry), and existing database orders are returned and broadcast to connected WebSocket clients.

### Seeding Synthetic Development Data
Use the tracked synthetic seed (no real data; delta A-10). It needs `APP_ENV=development` and refuses to run otherwise:

```bash
cd backend
APP_ENV=development uv run python -m scripts.seed_dev                      # idempotent
APP_ENV=development uv run python -m scripts.seed_dev --reset              # remove, then re-add
APP_ENV=development uv run python -m scripts.seed_dev --stock-mode single  # one bin per item
```

It creates:

- users `dev_op1` and `dev_op2` (password `dev-password`)
- items `Z90_*`, including nested standard BOMs and marketplace BOMs `9000000xx`
- stock: in multi mode, several bins plus one item with no stock (shortfall case)
- orders `DEV0001`–`DEV0008`: unclaimed, claimed, split into two packages, done, retry-ship,
  past ship-by, cancelled, and one past the 30-day retention

The old untracked `temp/seed_mock_order.py` is superseded.

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
   - Remove seeded rows with `python -m scripts.seed_dev --reset` (development only).

---

## Stock Location Mode

### Purpose & Behavior
`STOCK_LOCATION_MODE` selects how inventory locations work. Both modes are supported
business modes, not development bypasses (delta A-8), and the value is not restricted in production.

- **`multi` (default)**: an item may have stock in several bins. Adding or setting stock at
  location `A` does not affect stock at location `B`. Without a location, the item's only bin
  is used if it has exactly one, and the unlocated bin otherwise.
- **`single`**: an item has stock in at most **one** location:
  - **Add or set without a location (`location=None`)**: updates the item's sole existing
    location (or creates unlocated stock if no stock row exists).
  - **Add or set with a location (`location="LOC-X"`)**: first moves all existing stock of
    that item to `LOC-X` (removing the old rows), then applies the `add` or `set` there.
  - **Move / transfer (`move_to="LOC-Y"`)**: moves all stock of the item to `LOC-Y`.

The legacy variables `SINGLE_LOCATION_STOCK_BYPASS` and `STOCK_SINGLE_LOCATION_BYPASS` still
work as deprecated aliases when `STOCK_LOCATION_MODE` is unset. Replace them with
`STOCK_LOCATION_MODE=single`.

### Switching modes
- `single` → `multi`: no data change is needed.
- `multi` → `single`: merge first, in a maintenance window:
  ```bash
  docker compose -f compose.yaml -f compose.prod.yaml exec server python -m scripts.stock_merge_single            # report only
  docker compose -f compose.yaml -f compose.prod.yaml exec server python -m scripts.stock_merge_single --confirm  # apply
  ```
  Each item's stock moves to its first bin in location order (unlocated stock last). Every move
  is logged as `mode_merge`. If the merge is skipped, `single` mode still merges an item on
  its next adjustment.

## Inventory

### Picks, allocations and restores
- A pick (`POST /pick-items`) deducts stock bin by bin, in location order with unlocated
  stock last. For each bin it records an **allocation** (`orders.pick_stock_allocations`).
  The schema has no per-item default bin, so location order is the whole rule.
- If there is not enough stock, the pick still succeeds (HTTP 200). The unmet quantity is
  logged as `pick_shortfall` and is never allocated.
- Assigning part of an entry to an order moves the **deducted** quantity first (oldest
  allocation first). Any shortfall stays with the remainder. Assign and unassign never
  change stock.
- A pick for an order (`order_sn`) needs an order claimed by the caller that is not done.
  Otherwise the API returns 404, or 409 for a completed order.

> **Deleting a pick entry returns its stock.** This applies to both unassigned and order-assigned
> entries. A delete means the item was not used. The amount returned is what the pick actually
> deducted. If a pick found less stock than requested, only the stock that existed is returned.
> The stock goes back to the bin it came from; in single-location mode it goes to the item's
> current location. Every return is logged with the user who deleted the entry. Operations had
> not reached this case before this change. If an entry was deleted to correct a shipment that
> actually left the warehouse, adjust stock manually afterwards.

### Stock audit log
`warehouse.stocks_log` rows carry `sku, location, delta, before, after, reason, actor,
ref_type, ref_id`. Rows from before v0.5 have only `message`. Reasons:

| Reason | Written by |
|---|---|
| `adjust_set`, `adjust_add` | `POST /stocks/update` without `move_to` |
| `transfer_out`, `transfer_in` | `POST /stocks/update` with `move_to` |
| `pick`, `pick_shortfall` | `POST /pick-items` (`ref_type=pick_entry`) |
| `pick_restore` | `DELETE /pick-items/{id}` (actor = the deleting user, admin included) |
| `mode_merge` | `single` mode merging bins, or `scripts.stock_merge_single` |
| `cutover_clear` | `scripts.clear_open_pick_entries` (one row; `ref_id` = entries deleted) |
| `migration_merge` | the T4.3 migration folding duplicate `(sku, location)` rows |

Each `(sku, location)` pair, including an unlocated one, has at most one stock row (unique
index `uq_stocks_sku_location`). A row that reaches 0 is deleted, and a restore recreates it.

### Cutover of legacy pick entries (one time)
Entries created before the allocation table existed cannot be restored correctly. The release
that ships it clears them once, without touching stock (`docs/RELEASE.md`, delta D5):
`python -m scripts.clear_open_pick_entries --confirm`.

---

## Data Retention

Recipient data is used only for quick order matching by workers. Shopee's Data Protection
Policy allows keeping it for at most **90 days**; this deployment keeps it for **30 days**.

| Variable | Default | Rule |
|---|---|---|
| `RECIPIENT_RETENTION_DAYS` | `30` | Must be 1–90 under production rules (startup refuses otherwise) |
| `RECIPIENT_RETENTION_INTERVAL_SECONDS` | `86400` | How often the purge runs; it also runs once at startup |

The purge task:

- **deletes** `shopee.order_recipient_address` rows and **clears** `shopee.order_info.note`
- covers orders completed (`done_at`) more than N days ago, and orders never completed whose
  `ship_by` is more than N days ago
- **keeps** order numbers, items, status and tracking numbers (outbound matching and history
  still work)
- logs **counts only**, never names, cities or notes

Related rules:

- **Backups:** keep database backups no longer than 90 days, ideally 30, so purged data does
  not live on in old backups. Restoring an old backup brings purged data back; the next purge
  run removes it again.
- **Logs:** recipient data must never be written to logs. Do not add request/response body
  logging for Shopee order endpoints.

## Dormant Hardening Switches

Some hardening rules are already written but commented out, so they can be enabled later
without new design work. Each spot carries a grep-able tag:

```bash
grep -rn "HARDENING(" backend/
```

| Tag | What it enforces | Where |
|---|---|---|
| `HARDENING(password-min-length)` | Minimum 8 characters for passwords set by an admin (create user, reset password). Login and the v1 client's register request are unaffected; existing passwords keep working. | `backend/src/models.py` (`AdminUserCreate`, `AdminPasswordReset`), test in `backend/tests/test_admin_users.py` |

To enable a switch:

1. In the code, delete the line directly above the tag comment and uncomment the line below it.
2. Uncomment the tagged test block, then run the test suite.
3. Update `KNOWN_LIMITATIONS.md` (remove or amend the entry) and release as a normal backend update.

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

### Production Deployment

Production uses the base file plus the production override:

```bash
cd backend
cp .env.production.example .env        # non-sensitive settings only
# create the files listed at the top of compose.prod.yaml in backend/.secrets/ (chmod 600)
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

The override:

- sets `APP_ENV=production`, so startup refuses unsafe configuration (see Environment Profiles)
- forces `CORS_ORIGINS` empty
- publishes **no** ports for PostgreSQL or Redis
- starts Redis with `requirepass` taken from `.secrets/redis_password`, with an authenticated healthcheck
- reads `DATABASE_URL`, `ADMIN_PASSWORD`, `PARTNER_KEY` and `REDIS_URL` from `.secrets/` files instead of the environment
- uses `restart: unless-stopped` for every service

It needs Docker Compose v2.24.4 or later.

To reach the database for maintenance, use `docker compose exec db psql -U postgres bakingholic`
instead of publishing the port. For releases and maintenance windows, see `docs/RELEASE.md`.
After changing `.secrets/admin_password` for an **existing** admin account, run
`docker compose -f compose.yaml -f compose.prod.yaml exec server python -m scripts.set_admin_password`
(the startup seed only creates a missing admin).

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

### Using a Separate PostgreSQL Container

To use a PostgreSQL container that is not managed by `compose.yaml`, put it and the backend on
the same **user-defined** Docker network. Docker resolves container names only on user-defined
networks, not on the default `bridge`. If the backend is not on that network, startup fails with
`failed to resolve host '<name>'`. The names `my-postgres` and `my-pg-net` below are placeholders.

```bash
docker network create my-pg-net

docker run -d \
  --name my-postgres \
  --network my-pg-net \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password \
  -e POSTGRES_DB=bakingholic \
  -v $(pwd)/.secrets/postgres_password:/run/secrets/postgres_password:ro \
  -v $(pwd)/init-scripts:/docker-entrypoint-initdb.d:ro \
  -v my-pg-data:/var/lib/postgresql \
  postgres:18.4-alpine
```

Put the container name in the URL host, for example
`postgresql+psycopg://bh_backend:<app_password>@my-postgres:5432/bakingholic`, and attach the
backend to the same network:

```bash
docker run -d \
  --name order-checker-api \
  --network my-pg-net \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/.secrets/database_url:/run/secrets/database_url:ro \
  order-checker-backend:latest
```

With Compose, declare the network as external and list it under the `server` service. Forgetting
the service-level `networks:` entry is the usual cause of the resolve error:

```yaml
services:
  server:
    networks: [default, my-pg-net]

networks:
  my-pg-net:
    external: true
```

If the URL uses one of the rewritten hosts instead (`localhost`, `127.0.0.1`, `db`, `postgres-1`,
`postgres_container`), set `DB_HOST=my-postgres` so that the rewrite in `backend/src/config.py`
points at the container.

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
docker compose --env-file .env up -d --build admin-web
```
By default, the web interface is exposed on `http://localhost:${WEB_PORT:-3000}`.

### Vue console at `/console/` (v2 admin, in progress)

The same image also serves the new Vue admin (`frontend/admin-web`) at `/console/`. The Dockerfile
builds it in a Node stage from the named build context `admin-web`, which `compose.yaml` passes as
`additional_contexts` (Docker Compose 2.17 or newer). A plain build needs
`docker build --build-context admin-web=../admin-web .` from `frontend/admin`.

nginx serves `/console/assets/*` (content-hashed by Vite) as `immutable` for a year, and
`/console/index.html` with `no-cache`, so a redeploy shows up on the next page load without a
hard reload. Other `/console/...` paths fall back to the console's `index.html`. The console
uses the same proxied API paths and `/ws` as the Flutter admin. The rebuild steps below rebuild
both apps.

### Rebuilding the Admin Web After a Code Change

The admin bundle is compiled **inside the image** (`frontend/admin/Dockerfile`, builder stage).
A running container never picks up new Dart code by itself, so every admin change needs a new
image. In production:

```bash
cd backend
docker compose -f compose.yaml -f compose.prod.yaml build admin-web    # add --no-cache to rule out stale layers
docker compose -f compose.yaml -f compose.prod.yaml up -d admin-web    # recreates the container from the new image
docker compose -f compose.yaml -f compose.prod.yaml images admin-web   # the image's CREATED time must be just now
```

`up -d` without `--build` (or a prior `build`) reuses the existing image, which is the usual
reason a redeploy still shows the old admin. A local `frontend/admin/build/` is not used:
`.dockerignore` excludes it, and so are `frontend/admin/.env*` (the container writes
`assets/.env` at start).

Browsers revalidate every static file (`Cache-Control: no-cache` in `nginx.conf.template`),
because Flutter web output such as `main.dart.js` keeps the same name in every build.
**Releases up to v0.4.0 served `.js` files as `immutable` for one year**, so a browser that
opened such a build keeps its old copy. After the first deploy of v0.5.0, do one hard reload
(Ctrl+Shift+R) or clear the site data on every admin browser. Later deploys need only a normal
reload. To check what a browser runs, compare `/version.json` and the `Last-Modified` header
of `/main.dart.js` with the image build time.

The builder image is pinned to `ghcr.io/cirruslabs/flutter:3.44.0`. That project stopped
publishing images after 3.44.0, while CI analyzes and tests the admin app with Flutter 3.47.5.
Raise the pin when a newer image exists, or switch the builder to another Flutter source.

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

## Publishing a client release

The v2 operator app updates itself from the backend (V2_DELTA Q5, IMPLEMENTATION_PLAN T6.5).
APKs and `latest.json` live in `RELEASES_VOLUME` (default `./data/releases`, mounted read-only
at `/app/data/releases`; the app reads `CLIENT_RELEASES_DIR=data/releases/client`).

1. Build and sign the release APK (`frontend/client-android`, RELEASE.md "Operator app
   releases"), then check it: `apksigner verify --print-certs app-release.apk`.
2. Dry run on the host, from `backend/`:

   ```bash
   uv run python -m scripts.publish_client_release app-release.apk \
     --version-code 3 --version-name 2.0.2 --dir data/releases/client
   ```

3. Repeat with `--confirm`. The APK is copied to `orderchecker-<versionCode>.apk`, verified
   by SHA-256, and `latest.json` is replaced atomically **last**. No restart needed: the
   backend re-reads the file when it changes.

Rules: the versionCode must be higher than the published one (a rollback is a new, higher
versionCode built from older code). `--min-supported N` forces every older app to update: its
gated `/v2` calls answer 426 and `/v2/ws` closes with 4426. Omitted, the previous minimum is
kept. Old APK files stay; delete them by hand once no device runs them.

Endpoints (public, ungated): `GET /v2/client/latest`, `GET /v2/client/apk/{versionCode}`.

---

## Backups & Persistence

Back up all three durable assets together:

1. PostgreSQL data (`db-data`) for relational business state.
2. Redis data (`redis-data`) for live Shopee credentials.
3. Key storage directory (`KEYS_VOLUME`, default `./data/keys`) for active JWT signing and verification keys.
4. Client releases (`RELEASES_VOLUME`, default `./data/releases`): can be republished from the
   signed APKs, but keep `latest.json` so `min_supported_version_code` survives.

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
| `PermissionError: ... '/app/logs/backend.log'` at startup | The container runs as `appuser` (UID 10001) and writes to the bind-mounted `LOGS_VOLUME` (`./logs`). If that host folder didn't exist, rootful Docker created it owned by `root`, mode 755. Fix: `sudo chown 10001:10001 backend/logs`, or for a throwaway run set `LOG_TO_FILE=false`. Create the folder before the first `up` on a new host. |
