# LanLens Knowledge Base

This page collects common setup issues and fixes for LanLens integrations.

## i-doit integration FAQ

### `Authentication error: api.authenticated-users-only is enabled`

**Symptom**

The i-doit connection test fails with a JSON-RPC error similar to:

```json
{
  "code": -32604,
  "message": "Authentication error : System setting 'api.authenticated-users-only' is enabled. Please provide valid user credentials by http basic auth or use an existing session id."
}
```

**Meaning**

i-doit accepted the JSON-RPC endpoint, but the i-doit system setting `api.authenticated-users-only` requires an authenticated i-doit user in addition to the API key.

**Fix**

In LanLens, open **Settings → CMDB → i-doit integration** and configure:

- **i-doit Base URL**: your i-doit instance base URL, for example `https://example.i-doit.cloud`
- **JSON-RPC path**: usually `/src/jsonrpc.php`
- **API Key**: the i-doit API key
- **HTTP Basic username**: an i-doit user allowed to use the API
- **HTTP Basic password**: that user's password

Then run **Test connection** again.

**Alternative i-doit-side fix**

If you do not want LanLens to send HTTP Basic Auth, disable the i-doit setting that requires authenticated API users. This is less strict and depends on your security policy.

### Connection test uses the wrong endpoint

LanLens builds the JSON-RPC endpoint from:

```text
Base URL + JSON-RPC path
```

Examples:

| Base URL | JSON-RPC path | Tested endpoint |
| --- | --- | --- |
| `https://example.i-doit.cloud` | `/src/jsonrpc.php` | `https://example.i-doit.cloud/src/jsonrpc.php` |
| `https://example.i-doit.cloud/src/jsonrpc.php` | anything | `https://example.i-doit.cloud/src/jsonrpc.php` |

If your i-doit instance uses a custom sub-path, include it in the base URL or adjust the JSON-RPC path accordingly.

### HTTP 401 / 403

Usually means one of these is wrong:

- HTTP Basic username/password
- i-doit user permission
- reverse proxy authentication
- API access policy in i-doit

### HTTP 404

Usually means the JSON-RPC path is wrong. Try `/src/jsonrpc.php` first.

### HTTP 200 with JSON-RPC error

The web server and endpoint are reachable, but i-doit rejected the JSON-RPC request. Read the displayed JSON-RPC error message; common causes are invalid API key, missing Basic Auth, disabled API, or insufficient user permissions.

### Timeout or network error

LanLens cannot reach i-doit from the container/host. Check:

- DNS resolution from the LanLens container
- firewall/proxy rules
- TLS interception/certificates
- whether the i-doit URL is reachable from the Docker host
- `idoit_timeout_seconds` if the instance is slow

## Notes about secrets

LanLens stores the i-doit API key and Basic Auth password as secret settings and does not return them in clear text to the frontend. Leave password/API-key fields empty to keep existing stored values.
