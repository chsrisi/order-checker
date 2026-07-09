# Bakingholic Backend API 🍰

Welcome to the **Bakingholic Backend**! This repository houses the API services designed to power bakingholic order verification, real-time inventory and warehouse management, and seamless marketplace sync (Shopee Integration). 

The backend is built as a high-performance asynchronous API using **FastAPI**, with real-time state updates propagated via **WebSockets**, securely backed by **PostgreSQL** (ORMed via SQLAlchemy) and cached via **Redis**.

---

## 🚀 Key Features
*   **Asymmetric JWT Auth (RS256)**: Secure token authentication using standard RS256 signing keys rotated automatically by a background runner, exposing a standard JWKS endpoint.
*   **Shopee API Synchronization**: Real-time integration with the Shopee V2 API to fetch active orders (`READY_TO_SHIP`, `PROCESSED`, etc.) with built-in concurrency control and memory/database caching.
*   **Real-time WebSockets**: Duplex connections that instantly broadcast updates (Outbound scans, Stock levels, Pick List entries, and user lists) to administrative dashboards and clients.
*   **Inventory & Bill of Materials (BOM) Resolution**: Fully recursive BOM system that maps compound Shopee item listings and models to their respective individual physical warehouse SKU quantities.
*   **Outbound Validation**: Double-scan detection, carrier-matching scans, and bulk batch closure validation for fulfillment logs.

---

## 📁 Project Structure

Below is an overview of the backend directory structure and the main responsibilities of each file:

```text
backend/
├── alembic/                 # Alembic database migration scripts
├── init-scripts/            # Database initialization scripts (e.g., init.sql)
├── src/                     # Application source code
│   ├── main.py              # Main API entry point (endpoints, WebSockets, Shopee Sync engine)
│   ├── models.py            # SQLAlchemy database models and Pydantic schemas
│   ├── keys.py              # KeyManager for rotating RSA key-pairs and generating JWKS
│   ├── cache.py             # Memory/lock coordination for the Shopee order cache
│   ├── config.py            # Dynamic configuration loading (env, secrets)
│   └── redis_client.py      # Redis client wrapper for persistent Shopee token store
├── test/                    # Suite of automated test scripts
├── alembic.ini              # Alembic configuration file
├── compose.yaml             # Docker compose configuration (App, PostgreSQL, Redis)
├── Dockerfile               # Production Docker container definition
├── pyproject.toml           # Project dependencies and packaging settings
└── requirements.txt         # Explicit pinned dependency list
```

---

## 🛠️ Tech Stack & Dependencies

The backend requires **Python >= 3.14** and uses the following dependencies:

| Dependency | Purpose |
| :--- | :--- |
| **`fastapi[standard]`** | Core asynchronous ASGI web framework. |
| **`sqlalchemy`** | SQL Database Toolkit and Object-Relational Mapper (ORM). |
| **`psycopg[binary]`** | PostgreSQL database adapter for Python. |
| **`alembic`** | Database migration management tool. |
| **`redis[hiredis]`** | Redis client for access token storage and caching. |
| **`aiohttp[speedups]`** | Asynchronous HTTP client utilized to fetch Shopee details rapidly. |
| **`pyjwt[crypto]`** | JWT validation and creation using public-key cryptography (RS256). |
| **`passlib[argon2]`** | Password hashing context configured with Argon2. |
| **`pycryptodome`** | Low-level cryptographic primitives. |
| **`python-dotenv`** | Local environment variable parser. |

---

## 📡 Endpoint Routes (Categorized)

All endpoints (except key JWKS and login routes) require authentication. Authenticated users are divided into two scopes: `admin` and `client`.

### 🔑 1. Authentication & Security (`/auth/*` & `/.well-known/*`)

| Method | Route | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| **POST** | `/auth/register` | Register a new client user. Returns `access_token` and `refresh_token`. | No |
| **POST** | `/auth/login` | Authenticate client credentials. Returns tokens. | No |
| **POST** | `/auth/admin` | Authenticate admin credentials. Returns tokens. | No |
| **POST** | `/auth/logout` | Revokes the provided refresh token and invalidates the session. | Token |
| **POST** | `/auth/refresh` | Consumes a refresh token to generate a new pair of rotated tokens. | Token |
| **POST** | `/auth/ws-token` | Generate a short-lived (30s) ticket used to authenticate a WebSocket connection. | Token |
| **GET** | `/.well-known/jwks.json` | Public JWKS endpoint returning current signing keys for JWT verification. | No |

---

### 🔌 2. Real-time Communication (WebSockets)

| Protocol | Route | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| **WS** | `/ws` | Establishes a duplex connection. Expects authentication ticket parameter. Sends real-time updates for: `USERS`, `OUTBOUNDS`, `SHOPEE_ORDERS`, `PICK_ITEM_ENTRIES`, and `STOCKS`. | Yes (via WS Ticket) |

---

### 🛡️ 3. Administrative Management (`/admin/*`)

*All administrative routes require an `admin` scope credential.*

| Method | Route | Description | Scope |
| :--- | :--- | :--- | :--- |
| **GET** | `/admin/users` | Lists all active registered client users. | Admin |
| **DELETE** | `/admin/users` | Permenantly deletes a user, their refresh tokens, and scanning history. | Admin |
| **GET** | `/admin/history/outbound` | Fetches history of closed/archived outbound scans. | Admin |
| **GET** | `/admin/history/shopee/orders`| Fetches historical list of completed/archived Shopee orders. | Admin |
| **GET** | `/admin/export/scans` | Streams a CSV of current open outbound scans. | Admin |
| **GET** | `/admin/export/stocks` | Streams a CSV of current warehouse stock inventories. | Admin |

---

### 📦 4. Outbound Operations (`/outbound/*`)

| Method | Route | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| **POST** | `/outbound` | Record an outbound item scan. Rejects duplicates and appends carrier tags. | Yes |
| **GET** | `/outbound` | Fetches active open scans (user-scoped for client, all for admin). | Yes |
| **POST** | `/outbound/close` | Batch close a list of scans and mark matched Shopee orders as completed. | Admin |

---

### 🗺️ 5. Warehouse & Stock Management (`/items/*` & `/stocks/*`)

| Method | Route | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| **GET** | `/items/find` | Queries warehouse items by name or resolves standard barcode mappings. | Yes |
| **POST** | `/stocks` | Add, set, or transfer quantities of items across storage locations. | Yes |

---

### 🛍️ 6. Shopee Integration (`/shopee/*`)

| Method | Route | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| **GET** | `/shopee/orders` | Synchronize active marketplace orders (accepts optional `refresh` param). | Yes |
| **POST** | `/shopee/orders/acquire` | Claim ownership/responsibility of a Shopee order for the active client. | Yes |
| **POST** | `/shopee/reset-cache-state`| Clears fatal lock status in the synchronization cache. | Admin |

---

### 📋 7. Pick List Entries (`/pick-item/*`)

| Method | Route | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| **POST** | `/pick-item` | Records/creates a picked item quantity (general or linked to an order). | Yes |
| **GET** | `/pick-item` | Fetch current active pick entries for the logged-in user. | Yes |
| **DELETE** | `/pick-item` | Removes a pick entry. | Yes |
| **POST** | `/pick-item/assign` | Links a specific quantity of picked items to a pending Shopee order. | Yes |
| **POST** | `/pick-item/unassign` | Unlinks picked items from an order, placing them back in the general list. | Yes |
