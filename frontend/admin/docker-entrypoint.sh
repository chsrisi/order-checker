#!/bin/sh
set -e

ENV_TARGET="/usr/share/nginx/html/assets/.env"
mkdir -p /usr/share/nginx/html/assets

# If an external .env file is mounted at /app/.env, use it
if [ -f "/app/.env" ]; then
    echo "[entrypoint] Copying mounted /app/.env to $ENV_TARGET"
    cp /app/.env "$ENV_TARGET"
elif [ -n "$BASE_URL" ] || [ -n "$WS_URL" ] || [ -n "$BASE" ]; then
    echo "[entrypoint] Generating $ENV_TARGET from container environment variables"
    BASE_VAL="${BASE:-localhost}"
    BASE_URL_VAL="${BASE_URL:-http://${BASE_VAL}:8000}"
    WS_URL_VAL="${WS_URL:-ws://${BASE_VAL}:8000}"

    cat <<EOF > "$ENV_TARGET"
# Auto-generated runtime environment
BASE=${BASE_VAL}
BASE_URL=${BASE_URL_VAL}
WS_URL=${WS_URL_VAL}
WEB_PORT=${WEB_PORT:-80}
WEB_HOST=${WEB_HOST:-0.0.0.0}
EOF
fi

if [ -f "$ENV_TARGET" ]; then
    cp "$ENV_TARGET" /usr/share/nginx/html/.env 2>/dev/null || true
    echo "[entrypoint] Serving frontend admin assets/.env and .env"
fi
