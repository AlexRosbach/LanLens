# ─── Stage 1: Build React frontend ───────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

ARG LANLENS_APP_VERSION=1.5.4
ARG LANLENS_BUILD_CODE=dev
ARG LANLENS_BUILD_COMMIT=unknown
ARG LANLENS_BUILD_BRANCH=unknown
ARG LANLENS_BUILD_CREATED=unknown

# Copy package files first for layer caching
COPY frontend/package.json ./
# Use package-lock.json if available for reproducible builds
COPY frontend/package-lock.json* ./
# npm ci if lock file exists, otherwise npm install
RUN [ -f package-lock.json ] && npm ci --silent || npm install --silent

COPY frontend/ ./
RUN printf "export const APP_VERSION = '%s'\nexport const GITHUB_REPO = 'AlexRosbach/LanLens'\nexport const BUILD_CODE = '%s'\nexport const BUILD_COMMIT = '%s'\nexport const BUILD_BRANCH = '%s'\nexport const BUILD_CREATED = '%s'\n" \
    "$LANLENS_APP_VERSION" \
    "$LANLENS_BUILD_CODE" \
    "$LANLENS_BUILD_COMMIT" \
    "$LANLENS_BUILD_BRANCH" \
    "$LANLENS_BUILD_CREATED" \
    > src/version.ts
RUN npm run build

# ─── Stage 2: Runtime image ───────────────────────────────────────────────────
FROM python:3.12-slim

ARG LANLENS_APP_VERSION=1.5.4
ARG LANLENS_BUILD_CODE=dev
ARG LANLENS_BUILD_COMMIT=unknown
ARG LANLENS_BUILD_BRANCH=unknown
ARG LANLENS_BUILD_CREATED=unknown

LABEL org.opencontainers.image.title="LanLens" \
      org.opencontainers.image.description="Self-hosted network monitoring dashboard" \
      org.opencontainers.image.version=$LANLENS_APP_VERSION \
      org.opencontainers.image.revision=$LANLENS_BUILD_COMMIT \
      org.opencontainers.image.created=$LANLENS_BUILD_CREATED \
      org.opencontainers.image.licenses="MIT AND GPL-2.0-only AND GPL-3.0-only AND LGPL-2.1-only AND Apache-2.0" \
      org.opencontainers.image.source="https://github.com/AlexRosbach/LanLens"

# System dependencies + Python build tools (gcc needed for netifaces C extension).
# Build tools are removed after pip install to keep the image lean.
COPY backend/requirements.txt /tmp/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    nmap \
    iputils-ping \
    snmp \
    libpcap-dev \
    libpcap0.8 \
    net-tools \
    iproute2 \
    curl \
    gcc \
    python3-dev \
  && rm -f /etc/nginx/sites-enabled/default \
  && pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r /tmp/requirements.txt \
  && apt-get purge -y --auto-remove gcc python3-dev \
  && rm -rf /var/lib/apt/lists/* /tmp/requirements.txt

WORKDIR /app

# Copy requirements again for explicit layer documentation (already installed above)
COPY backend/requirements.txt /app/backend/requirements.txt

# Copy backend source
COPY backend/ /app/backend/
RUN printf 'APP_VERSION = "%s"\nBUILD_CODE = "%s"\nBUILD_COMMIT = "%s"\nBUILD_BRANCH = "%s"\nBUILD_CREATED = "%s"\n' \
    "$LANLENS_APP_VERSION" \
    "$LANLENS_BUILD_CODE" \
    "$LANLENS_BUILD_COMMIT" \
    "$LANLENS_BUILD_BRANCH" \
    "$LANLENS_BUILD_CREATED" \
    > /app/backend/version.py

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Copy nginx config
COPY nginx/nginx.conf /etc/nginx/nginx.conf

# Copy and prepare entrypoint
COPY scripts/entrypoint.sh /entrypoint.sh
COPY scripts/render-nginx-config.sh /usr/local/bin/render-lanlens-nginx
RUN chmod +x /entrypoint.sh /usr/local/bin/render-lanlens-nginx

# Create the reset-password CLI wrapper
RUN printf '#!/bin/sh\nexec python /app/backend/cli/reset_password.py "$@"\n' \
    > /usr/local/bin/reset-password \
  && chmod +x /usr/local/bin/reset-password

# Persistent data volume (SQLite database lives here)
VOLUME ["/data"]

# Environment defaults
# SECRET_KEY MUST be overridden at runtime — the app and entrypoint both validate this
ENV DB_PATH=/data/lanlens.db \
    SECRET_KEY="" \
    DEFAULT_ADMIN_PASSWORD=admin \
    LANLENS_PORT=7765 \
    BACKEND_PORT=17765 \
    TZ=UTC \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 7765

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD sh -c 'if python -c "import json,sys; data=json.load(open(\"/data/tls/config.json\")); sys.exit(0 if data.get(\"enabled\") else 1)" 2>/dev/null; then port=$(python -c "import json; print(json.load(open(\"/data/tls/config.json\")).get(\"port\") or \"${LANLENS_PORT:-7765}\")"); curl -kfs "https://localhost:${port}/api/health"; else curl -fs "http://localhost:${LANLENS_PORT:-7765}/api/health"; fi || exit 1'

ENTRYPOINT ["/entrypoint.sh"]
