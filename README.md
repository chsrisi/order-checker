# Order Checker

Internal order-fulfillment and warehouse tooling for Bakingholic. The repository
contains a FastAPI backend plus separate Flutter apps for warehouse operators and
administrators.

## What it does

- Imports active Shopee orders and resolves marketplace items through recursive BOMs.
- Supports order claiming, pick lists, outbound label scanning, and batch closing.
- Tracks stock by SKU and location, including adjustments and transfers.
- Pushes orders, scans, picks, users, and stock changes over WebSockets.
- Uses RS256 access/refresh tokens, rotating signing keys, PostgreSQL, and Redis.

## Repository

```text
backend/          FastAPI API, SQLAlchemy models, Alembic migrations, Docker stack
frontend/client/  Flutter operator app (web, Android, Windows)
frontend/admin/   Flutter administration app (web, Windows)
docs/             Architecture, API, operations, testing, and review guides
```

## Quick start

Requirements: Docker with Compose, Flutter 3.x/Dart 3.9+ for the UIs.

1. Create `backend/.secrets/postgres_password` and
   `backend/.secrets/app_password`. Use the app password in `DATABASE_URL`.
2. Export the backend configuration:

   ```bash
   export DATABASE_URL='postgresql+psycopg://bh_backend:APP_PASSWORD@localhost:5432/bakingholic'
   export ADMIN_USERNAME='admin'
   export ADMIN_PASSWORD='change-me'
   export PARTNER_ID='your-shopee-partner-id'
   export PARTNER_KEY='your-shopee-partner-key'
   export SHOP_ID='your-shopee-shop-id'
   export SHOPEE_URL='https://partner.shopeemobile.com'
   export CORS_ORIGINS='http://localhost:3000'
   ```

3. Start the stack:

   ```bash
   cd backend
   docker compose up --build
   ```

   The API runs at `http://localhost:8000`; interactive OpenAPI docs are at
   `http://localhost:8000/docs`. Alembic migrations run on container startup.

4. Add this untracked `.env` to each Flutter app:

   ```dotenv
   BASE_URL=http://localhost:8000
   WS_URL=ws://localhost:8000
   ```

5. Run either UI:

   ```bash
   cd frontend/client   # or frontend/admin
   flutter pub get
   flutter run -d chrome
   ```

Shopee access and refresh tokens can be entered from the admin app's protected
configuration screen. Flutter `.env` files and generated backend key files are
ignored by Git; keep `backend/.secrets/` private as well.

## Development checks

```bash
docker compose -f backend/compose.yaml config --quiet
cd backend && docker compose -f compose.yaml -f compose.test.yaml run --build --rm tests
cd frontend/client && flutter analyze && flutter test
cd frontend/admin && flutter analyze && flutter test
```

Start with the [documentation index](docs/PROJECT.md), or jump to the
[architecture](docs/ARCHITECTURE.md), [API](docs/API.md),
[operations](docs/OPERATIONS.md), [testing](docs/TESTING.md), and
[code-review report](docs/CODE_REVIEW.md).
