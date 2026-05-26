#!/bin/sh
set -eu

LANLENS_PORT="${LANLENS_PORT:-7765}"
BACKEND_PORT="${BACKEND_PORT:-17765}"
TLS_DIR="${LANLENS_TLS_DIR:-/data/tls}"
TLS_CONFIG="${TLS_DIR}/config.json"
OUTPUT_CONFIG="${LANLENS_NGINX_CONFIG:-/etc/nginx/nginx.conf}"
TMP_CONFIG="$(mktemp /tmp/lanlens-nginx.XXXXXX.conf)"
trap 'rm -f "${TMP_CONFIG}"' EXIT

HTTPS_ENABLED="false"
HTTPS_PORT="${LANLENS_PORT}"
HTTPS_REDIRECT_HTTP="false"
HTTPS_CERTIFICATE="${TLS_DIR}/lanlens.crt"
HTTPS_PRIVATE_KEY="${TLS_DIR}/lanlens.key"

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

case "${LANLENS_PORT}" in
    ''|*[!0-9]*)
        echo "ERROR: LANLENS_PORT must be a numeric TCP port."
        exit 1
        ;;
esac

case "${BACKEND_PORT}" in
    ''|*[!0-9]*)
        echo "ERROR: BACKEND_PORT must be a numeric TCP port."
        exit 1
        ;;
esac

case "${HTTPS_PORT}" in
    ''|*[!0-9]*)
        echo "ERROR: HTTPS port must be a numeric TCP port."
        exit 1
        ;;
esac

write_app_locations() {
    cat <<EOF
        # Serve built React app (SPA - all unknown routes -> index.html)
        location / {
            root /app/frontend/dist;
            try_files \$uri \$uri/ /index.html;
            add_header Cache-Control "no-store, no-cache, must-revalidate";
        }

        # Cache static assets
        location ~* \.(js|css|svg|png|ico|woff2?)$ {
            root /app/frontend/dist;
            expires 7d;
            add_header Cache-Control "public, max-age=604800, immutable";
        }

        # Proxy API requests to FastAPI
        location /api/ {
            proxy_pass http://127.0.0.1:${BACKEND_PORT};
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_read_timeout 120s;
        }

        # WebSocket proxy for live scan updates
        location /ws/ {
            proxy_pass http://127.0.0.1:${BACKEND_PORT};
            proxy_http_version 1.1;
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_read_timeout 86400s;
        }
EOF
}

{
    cat <<'EOF'
worker_processes 1;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    keepalive_timeout 65;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
EOF

    if [ "${HTTPS_ENABLED}" = "true" ] && [ -r "${HTTPS_CERTIFICATE}" ] && [ -r "${HTTPS_PRIVATE_KEY}" ]; then
        if [ "${LANLENS_PORT}" != "${HTTPS_PORT}" ]; then
            cat <<EOF

    server {
        listen ${LANLENS_PORT};
        server_name _;
EOF
            if [ "${HTTPS_REDIRECT_HTTP}" = "true" ]; then
                cat <<EOF
        return 301 https://\$host:${HTTPS_PORT}\$request_uri;
    }
EOF
            else
                write_app_locations
                cat <<'EOF'
    }
EOF
            fi
        fi

        cat <<EOF

    server {
        listen ${HTTPS_PORT} ssl http2;
        server_name _;
        ssl_certificate ${HTTPS_CERTIFICATE};
        ssl_certificate_key ${HTTPS_PRIVATE_KEY};
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_prefer_server_ciphers off;
        ssl_session_cache shared:SSL:10m;
        ssl_session_timeout 10m;
EOF
        write_app_locations
        cat <<'EOF'
    }
EOF
    else
        cat <<EOF

    server {
        listen ${LANLENS_PORT};
        server_name _;
EOF
        write_app_locations
        cat <<'EOF'
    }
EOF
    fi

    cat <<'EOF'
}
EOF
} > "${TMP_CONFIG}"

nginx -t -c "${TMP_CONFIG}"
mv "${TMP_CONFIG}" "${OUTPUT_CONFIG}"
trap - EXIT
