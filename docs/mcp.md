# LanLens MCP companion

LanLens ships an official Model Context Protocol (MCP) companion that lets Claude,
Codex, ChatGPT, and other MCP clients query the self-hosted LanLens REST API. The
companion is read-only by default and never returns credentials, secrets, password
locations, private device notes, raw authentication material, or arbitrary API paths.

## Prerequisites

Configure a persistent LanLens API token with at least 32 random characters:

```yaml
environment:
  - LANLENS_API_TOKEN=replace-with-a-random-token
  - LANLENS_API_TOKEN_READ_ONLY=true
```

Restart LanLens after changing the token. Keep the read-only policy unless the
allow-listed MCP metadata mutation is explicitly required.

## Claude Desktop one-click bundle

Download `lanlens-mcp-1.6.1.mcpb` from the GitHub release, then open Claude Desktop
and select **Settings → Desktop app → Extensions → Advanced settings → Install
Extension…**. Enter the LanLens URL and persistent API token. Device metadata writes
remain disabled unless enabled in the extension settings and by the LanLens token.

## Docker / Streamable HTTP

The companion image supports AMD64 and ARM64:

```bash
docker run --rm \
  -p 127.0.0.1:8787:8787 \
  -e LANLENS_URL=http://host.docker.internal:7765 \
  -e LANLENS_API_TOKEN=replace-with-a-random-token \
  -e LANLENS_MCP_HTTP_TOKEN=replace-with-a-different-random-token \
  -e LANLENS_MCP_ALLOWED_HOSTS=localhost,127.0.0.1,host.docker.internal \
  --add-host host.docker.internal:host-gateway \
  alexrosbach/lanlens-mcp:1.6.1-dev
```

Or use the optional Compose profile after setting `LANLENS_API_TOKEN` and
`LANLENS_MCP_HTTP_TOKEN` in a local `.env` file:

```bash
docker compose --profile mcp up -d
```

The MCP endpoint is `http://127.0.0.1:8787/mcp`. The unauthenticated companion
health endpoint is `http://127.0.0.1:8787/health` and contains no LanLens data.

## Codex

For a local HTTP companion:

```bash
codex mcp add lanlens --url http://127.0.0.1:8787/mcp \
  --bearer-token-env-var LANLENS_MCP_HTTP_TOKEN
```

For stdio from the repository checkout:

```toml
[mcp_servers.lanlens]
command = "node"
args = ["/path/to/LanLens/mcp/dist/index.js", "--transport=stdio"]
env = {
  LANLENS_URL = "http://127.0.0.1:7765",
  LANLENS_API_TOKEN = "replace-with-a-random-token"
}
```

## Claude Code

```bash
claude mcp add --transport http lanlens http://127.0.0.1:8787/mcp \
  --header "Authorization: Bearer $LANLENS_MCP_HTTP_TOKEN"
```

Claude Desktop users should prefer the `.mcpb` package because it avoids manual
configuration and runs the companion locally over stdio.

## ChatGPT and the OpenAI API

ChatGPT can connect to a public HTTPS MCP endpoint or to a private companion through
OpenAI Secure MCP Tunnel. Do not expose the plain HTTP example to the internet.
Terminate TLS at a trusted reverse proxy, keep the MCP Bearer token enabled, and
restrict access at the network layer. In the Responses API, configure an MCP tool
with the companion `server_url` and provide the MCP Bearer token as authorization.

## Tools and resources

Read-only tools:

- `get_health`
- `list_devices`
- `get_device`
- `list_services`
- `list_open_ports`
- `get_topology`
- `list_segments`
- `list_notifications`
- `list_network_changes`

Resources:

- `lanlens://health`
- `lanlens://devices/{deviceId}`

When `LANLENS_MCP_ENABLE_WRITES=true`, the server additionally advertises
`update_device_metadata`. It can change only device class, responsible person,
location, and description. The LanLens API token must separately be configured with
`LANLENS_API_TOKEN_READ_ONLY=false`; otherwise LanLens rejects the request. Every
successful change continues to use LanLens' existing device change events.

## Security model

- The LanLens URL is fixed at process startup; tools cannot select arbitrary URLs or paths.
- Redirects are rejected so the LanLens token cannot be forwarded to another origin.
- Inputs, result counts, response sizes, and request timeouts are bounded.
- Non-loopback HTTP binds require a separate `LANLENS_MCP_HTTP_TOKEN` and an explicit
  `LANLENS_MCP_ALLOWED_HOSTS` allowlist.
- Host and Origin validation protect local HTTP deployments from DNS rebinding.
- Streamable HTTP request bodies are limited to 1 MiB.
- The MCP endpoint should use HTTPS when traffic leaves the local machine.
