#!/bin/bash
set -e

# ─── LanLens Entrypoint ───────────────────────────────────────────────────────

echo "Starting LanLens..."

# Validate SECRET_KEY before doing anything
if [ -z "${SECRET_KEY}" ] || [ "${SECRET_KEY}" = "CHANGE_THIS_TO_A_LONG_RANDOM_STRING" ]; then
    echo "ERROR: SECRET_KEY environment variable is not set or still uses the placeholder value."
    echo "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    echo "Then set it in docker-compose.yml or as an environment variable."
    exit 1
fi

LANLENS_PORT="${LANLENS_PORT:-7765}"
BACKEND_PORT="${BACKEND_PORT:-17765}"
TLS_DIR="${LANLENS_TLS_DIR:-/data/tls}"
TLS_CONFIG="${TLS_DIR}/config.json"
HTTPS_ENABLED="false"
HTTPS_PORT="${LANLENS_PORT}"
HTTPS_REDIRECT_HTTP="false"
HTTPS_CERTIFICATE="${TLS_DIR}/lanlens.crt"
HTTPS_PRIVATE_KEY="${TLS_DIR}/lanlens.key"

# Ensure data directory exists (mounted volume)
mkdir -p /data

# Render nginx config with the selected HTTP/HTTPS settings.
render-lanlens-nginx

if [ -f "${TLS_CONFIG}" ]; then
    eval "$(
        python - "${TLS_CONFIG}" "${LANLENS_PORT}" <<'PY'
import json
import shlex
import sys

config_path, default_port = sys.argv[1], sys.argv[2]
try:
    with open(config_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    data = {}

values = {
    "HTTPS_ENABLED": "true" if data.get("enabled") is True else "false",
    "HTTPS_PORT": str(data.get("port") or default_port),
    "HTTPS_REDIRECT_HTTP": "true" if data.get("redirect_http") is True else "false",
    "HTTPS_CERTIFICATE": str(data.get("certificate_path") or ""),
    "HTTPS_PRIVATE_KEY": str(data.get("private_key_path") or ""),
}
for key, value in values.items():
    print(f"{key}={shlex.quote(value)}")
PY
    )"
fi
if [ -z "${HTTPS_CERTIFICATE}" ]; then
    HTTPS_CERTIFICATE="${TLS_DIR}/lanlens.crt"
fi
if [ -z "${HTTPS_PRIVATE_KEY}" ]; then
    HTTPS_PRIVATE_KEY="${TLS_DIR}/lanlens.key"
fi
HTTPS_AVAILABLE="false"
if [ "${HTTPS_ENABLED}" = "true" ] && [ -r "${HTTPS_CERTIFICATE}" ] && [ -r "${HTTPS_PRIVATE_KEY}" ]; then
    HTTPS_AVAILABLE="true"
fi

# Show network interfaces, IP addresses and access info
echo "──────────────────────────────────────────────────────"
echo " LanLens is starting up"
echo "──────────────────────────────────────────────────────"
echo " Network interfaces:"
ip -4 addr show scope global | awk '
  /^[0-9]+:/ { iface = $2 }
  /inet /    { printf "   %-14s %s\n", iface, $2 }
'
echo ""
FIRST_IP=$(ip -4 addr show scope global | awk '/inet / { print $2 }' | head -1 | cut -d'/' -f1)
echo " Access LanLens at:"
if [ -n "$FIRST_IP" ]; then
    if [ "${HTTPS_AVAILABLE}" = "true" ] && [ "${HTTPS_PORT}" = "${LANLENS_PORT}" ]; then
        echo "   https://${FIRST_IP}:${LANLENS_PORT}"
    else
        if [ "${HTTPS_AVAILABLE}" = "true" ] && [ "${HTTPS_REDIRECT_HTTP}" = "true" ]; then
            echo "   http://${FIRST_IP}:${LANLENS_PORT}  (redirects to HTTPS)"
        else
            echo "   http://${FIRST_IP}:${LANLENS_PORT}"
        fi
        if [ "${HTTPS_AVAILABLE}" = "true" ] && [ "${HTTPS_PORT}" != "${LANLENS_PORT}" ]; then
            echo "   https://${FIRST_IP}:${HTTPS_PORT}"
        fi
    fi
fi
if [ "${HTTPS_AVAILABLE}" = "true" ] && [ "${HTTPS_PORT}" = "${LANLENS_PORT}" ]; then
    echo "   https://localhost:${LANLENS_PORT}  (from this host)"
else
    echo "   http://localhost:${LANLENS_PORT}  (from this host)"
    if [ "${HTTPS_AVAILABLE}" = "true" ] && [ "${HTTPS_PORT}" != "${LANLENS_PORT}" ]; then
        echo "   https://localhost:${HTTPS_PORT}  (from this host)"
    fi
fi
echo ""
echo " Default credentials:"
echo "   Username: admin"
echo "   Password: ${DEFAULT_ADMIN_PASSWORD:-admin}"
echo "   (you will be prompted to change the password on first login)"
echo "──────────────────────────────────────────────────────"

# Initialize database tables (idempotent)
echo "Initializing database..."
python /app/backend/cli/init_db.py

# Apply incremental schema migrations (idempotent)
echo "Running database migrations..."
python /app/backend/cli/migrate_db.py

# Create default admin user if no users exist
echo "Checking admin user..."
python /app/backend/cli/init_admin.py

# Start nginx in background
echo "Starting nginx..."
nginx -g "daemon off;" &

# Start FastAPI with uvicorn (foreground, single worker for scheduler consistency)
echo "Starting LanLens API..."
exec uvicorn backend.main:app \
    --host 127.0.0.1 \
    --port "${BACKEND_PORT}" \
    --workers 1 \
    --log-level info \
    --no-access-log
