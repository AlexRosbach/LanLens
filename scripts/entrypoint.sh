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
    echo "   http://${FIRST_IP}:7765"
fi
echo "   http://localhost:7765  (from this host)"
echo ""
echo " Default credentials:"
echo "   Username: admin"
echo "   Password: ${DEFAULT_ADMIN_PASSWORD:-admin}"
echo "   (you will be prompted to change the password on first login)"
echo "──────────────────────────────────────────────────────"

# Ensure data directory exists (mounted volume)
mkdir -p /data

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
    --port 17765 \
    --workers 1 \
    --log-level info \
    --no-access-log
