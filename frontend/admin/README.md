# Order Checker - Frontend Admin

A Flutter application providing management, monitoring, and administration capabilities for the Order Checker system. It can be run natively as a desktop application (Windows) or hosted as a responsive Web application inside Docker using Nginx.

---

## Features

- **Registered Users**: Manage operator credentials and role assignments.
- **Item Finder**: Lookup warehouse inventory and physical storage locations.
- **Orders / Outbound**: Inspect Shopee orders, monitor packing and pick status, and trigger period closures.
- **Inventory Stocks**: Real-time view of inventory levels and CSV stock export.
- **Shopee Configuration**: Securely manage Shopee partner IDs, API secrets, and OAuth token refreshes.
- **BOM Viewer**: Interactive Bill of Materials (BOM) component tree viewer.

---

## Configuration & Environment Variables

The application loads its operational parameters using `flutter_dotenv`.

> [!CAUTION]
> **Security & Agent Rule**:
> Active `.env` files contain sensitive operational configuration and production secrets and are strictly excluded from version control via `.gitignore`.
> Automated agents, scripts, and code analysis tools **must only read `.env.example`** to understand configuration keys and defaults. Never commit or dump active `.env` files.

### Configuration Template (`.env.example`)

To configure your environment, create `.env` in the `frontend/admin/` directory based on `.env.example`:

```bash
cp .env.example .env
```

| Variable | Default | Description |
| :--- | :--- | :--- |
| `BASE` | `localhost` | Hostname or IP address of the Order Checker backend API. |
| `BASE_URL` | `http://${BASE}:8000` | Full HTTP/HTTPS base URL for backend REST API calls. |
| `WS_URL` | `ws://${BASE}:8000` | Full WS/WSS base URL for backend WebSocket real-time updates. |
| `WEB_PORT` | `80` (or `3000` in compose) | Web server listening port when running in Docker/Nginx. |
| `WEB_HOST` | `0.0.0.0` | Network interface binding address for the web server. |
| `WEB_BASE_HREF`| `/` | Base URL path if hosting under a sub-path or reverse proxy prefix. |

> [!TIP]
> **Backend CORS Coordination**: When hosting on web, ensure the web app's origin (e.g. `http://localhost:3000` or your production domain) is included in the backend's `CORS_ORIGINS` setting in `backend/.env`.

---

## Local Development

Ensure Flutter SDK (3.38+ / Dart 3.9+) is installed and on your PATH.

### 1. Install Dependencies
```bash
flutter pub get
```

### 2. Run as Web Application (Chrome)
```bash
flutter run -d chrome
```

### 3. Run as Desktop Application (Windows)
```bash
flutter run -d windows
```

---

## Web Hosting with Docker

The admin web application is containerized using a multi-stage Docker build:
1. **Builder stage**: Uses `ghcr.io/cirruslabs/flutter:stable` to compile a release web bundle (`flutter build web --release`).
2. **Runner stage**: Uses `nginx:alpine` to host static web assets with gzip compression, SPA fallback routing (`try_files $uri $uri/ /index.html;`), and static caching headers.

### Dynamic Runtime Configuration Injection

Flutter Web loads environment variables at runtime via an HTTP request to `/assets/.env`.
The container includes a startup hook (`/docker-entrypoint.d/40-generate-env.sh`) that automatically injects container environment variables (`BASE`, `BASE_URL`, `WS_URL`, `WEB_PORT`) directly into `/usr/share/nginx/html/assets/.env` before Nginx starts.

This allows you to change the target backend API at container launch **without rebuilding the Docker image**.

### Building the Docker Image
```bash
docker build -t order-checker-admin-web .
```

### Running Standalone Container
```bash
docker run -d \
  --name admin-web \
  -p 3000:80 \
  -e BASE_URL=http://localhost:8000 \
  -e WS_URL=ws://localhost:8000 \
  order-checker-admin-web
```

Access the admin web panel in your browser at `http://localhost:3000`.

### Running with Docker Compose
To launch along with the backend, PostgreSQL, and Redis:
```bash
cd ../../backend
docker compose --env-file .env up -d admin-web
```
