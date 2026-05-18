# LanLens Knowledge Base

This page collects common setup issues and fixes for LanLens integrations.

## i-doit integration FAQ

### What does LanLens map by default?

LanLens uses conservative i-doit standard categories for the initial mapping:

| LanLens field | Default i-doit target |
| --- | --- |
| Hostname | `C__CATG__IP.hostname` |
| IP address | `C__CATG__IP.ipv4_address` |
| MAC address | `C__CATG__NETWORK_PORT.mac` |
| Vendor | `C__CATG__MODEL.manufacturer` |
| Asset tag / CMDB ID | `C__CATG__ACCOUNTING.inventory_no` |
| Purpose | `C__CATG__GLOBAL.purpose` |
| OS info | `C__CATG__OPERATING_SYSTEM.assigned_version` |
| CPU | `C__CATG__CPU.title` plus derived standard CPU fields when accepted |
| Model | `C__CATG__MODEL.title` |
| Memory | `C__CATG__MEMORY.title` plus derived standard memory fields when accepted |
| Disks | `C__CATG__DRIVE.title` plus derived standard drive fields when accepted |

Notes, services, containers, hypervisor data, licenses, relationships and the full LanLens inventory are intentionally empty in the default mapping. Choose a writable standard or custom i-doit field before mapping those values. This avoids writing large LanLens text dumps into generic i-doit descriptions.

### Sync logs show the device ID only

Recent LanLens versions return the display name for each i-doit sync log entry and link it to the device detail page. If you still see only IDs, refresh the UI after updating the backend and frontend assets.

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

This is a configuration or permission issue, not a LanLens mapping issue. Fix authentication first, then rerun **Test connection**.

### HTTP 404

Usually means the JSON-RPC path is wrong. Try `/src/jsonrpc.php` first.

### HTTP 200 with JSON-RPC error

The web server and endpoint are reachable, but i-doit rejected the JSON-RPC request. Read the displayed JSON-RPC error message; common causes are invalid API key, missing Basic Auth, disabled API, or insufficient user permissions.

### Object type, category or field not found

LanLens can validate whether the mapping JSON is structurally valid, but only i-doit can decide whether a category field exists and is writable for the selected object type.

Common causes:

- the object type does not support that category
- the field name differs between i-doit versions/modules
- the category exists but is not writable by the API user
- a custom field was renamed or not deployed in the target tenant

Fix the mapping target or route the device class to a more suitable object type in `objectTypeByDeviceClass`.

### Selected sync status field is not writable

`idoit_sync_status_field` is optional. Leave it empty unless you have a known writable custom/status/reference field. LanLens avoids using `C__CATG__GLOBAL.description` by default because it can overwrite or pollute human-maintained object descriptions.

### Duplicate or uncertain match

LanLens matches in this order:

1. existing linked i-doit object ID
2. configured external reference / `cmdb_id`
3. exact MAC address
4. hostname or IP only as warning-level candidates

If matches are ambiguous, set a stable `cmdb_id` or link the object explicitly before syncing again.

### Timeout or network error

LanLens cannot reach i-doit from the container/host. Check:

- DNS resolution from the LanLens container
- firewall/proxy rules
- TLS interception/certificates
- whether the i-doit URL is reachable from the Docker host
- `idoit_timeout_seconds` if the instance is slow

## Notes about secrets

LanLens stores the i-doit API key and Basic Auth password as secret settings and does not return them in clear text to the frontend. Leave password/API-key fields empty to keep existing stored values.
