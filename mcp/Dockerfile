FROM node:22-alpine AS builder

WORKDIR /app/mcp
COPY mcp/package.json mcp/package-lock.json ./
RUN npm ci
COPY mcp/tsconfig.json ./
COPY mcp/src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine

ARG LANLENS_APP_VERSION=1.6.1
ARG LANLENS_BUILD_CODE=dev
ARG LANLENS_BUILD_COMMIT=unknown
ARG LANLENS_BUILD_BRANCH=unknown
ARG LANLENS_BUILD_CREATED=unknown

LABEL org.opencontainers.image.title="LanLens MCP" \
      org.opencontainers.image.description="Official MCP companion server for LanLens" \
      org.opencontainers.image.version=$LANLENS_APP_VERSION \
      org.opencontainers.image.revision=$LANLENS_BUILD_COMMIT \
      org.opencontainers.image.created=$LANLENS_BUILD_CREATED \
      org.opencontainers.image.licenses="MIT AND Apache-2.0" \
      org.opencontainers.image.source="https://github.com/AlexRosbach/LanLens"

WORKDIR /app
COPY --from=builder /app/mcp/package.json /app/package.json
COPY --from=builder /app/mcp/package-lock.json /app/package-lock.json
COPY --from=builder /app/mcp/node_modules /app/node_modules
COPY --from=builder /app/mcp/dist /app/dist

ENV NODE_ENV=production \
    LANLENS_MCP_TRANSPORT=http \
    LANLENS_MCP_HOST=0.0.0.0 \
    LANLENS_MCP_PORT=8787 \
    LANLENS_MCP_ENABLE_WRITES=false \
    LANLENS_MCP_VERSION=$LANLENS_APP_VERSION \
    LANLENS_MCP_BUILD_CODE=$LANLENS_BUILD_CODE \
    LANLENS_MCP_BUILD_COMMIT=$LANLENS_BUILD_COMMIT \
    LANLENS_MCP_BUILD_BRANCH=$LANLENS_BUILD_BRANCH \
    LANLENS_MCP_BUILD_CREATED=$LANLENS_BUILD_CREATED

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:8787/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

USER node
CMD ["node", "/app/dist/index.js", "--transport=http"]
