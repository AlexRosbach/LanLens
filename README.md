<div align="center">

<img src="frontend/public/logo.svg" alt="LanLens Logo" width="80" height="80" />

# LanLens

**Self-hosted network monitoring and documentation dashboard**

[![Version](https://img.shields.io/badge/version-1.5.0-6366f1)](https://github.com/AlexRosbach/LanLens)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Docker Hub](https://img.shields.io/docker/pulls/alexrosbach/lanlens?color=0ea5e9)](https://hub.docker.com/r/alexrosbach/lanlens)

LanLens scans your local network, identifies devices by MAC/IP, and gives you a clean web UI to document, classify, and connect to them.

> [!IMPORTANT]
> LanLens is intended exclusively for use in your own network or in networks where you have explicit permission to scan and monitor devices.
> Features such as network discovery and port scanning can be misused against third-party systems. You are responsible for complying with applicable laws, policies, and authorization requirements. The project maintainer cannot be held liable for misuse or unauthorized scanning performed with this tool.

### Contributors

Thanks to everyone helping shape LanLens, including community contributions that improved translations, UX consistency, and release polish.

</div>

---

## Features


- Automatic LAN discovery via ARP scan
- Device classification, custom device classes, and offline MAC vendor lookup
- DHCP badge detection
- Segments with colour, range, and IP usage
- Per-device documentation fields, IP history, and manual offline-device status re-checks
- Service inventory per device, plus optional Services directory page with user-managed segments, drag-and-drop grouping, explicit segment dropdown assignment, and custom icon URLs
- Optional DHCP Monitor page that probes visible DHCP servers and shows announced DHCP options
- One-click connect actions (SSH, RDP, HTTP, HTTPS)
- Port scanning via nmap
- **Deep scan** via SSH (Linux) and WinRM (Windows) — hardware, OS, services, containers, hypervisor inventory
- **Encrypted credential vault** for SSH and WinRM access (Fernet, key derived from `SECRET_KEY`)
- **Hypervisor intelligence** — detects Proxmox, KVM, and Hyper-V hosts; enumerates guests; maps VMs to known devices
- **Auto deep scan** — per-device scheduled scanning with configurable interval
- **Inventory tools in Settings** — per-device change timeline, maintenance/mute controls, ignore rules, duplicate merge preview/action, sanitized documentation reports, backup and restore helpers
- Telegram notifications for new devices and updates
- English, German, Italian, and Simplified Chinese UI
- Responsive dashboard for desktop and mobile

---

## Screenshots

> IP and MAC addresses in the screenshots were anonymized for privacy.

| Dashboard | Device detail |
|---|---|
| ![Dashboard](docs/screenshots/lanlens_04_dashboard.png) | ![Device Detail](docs/screenshots/lanlens_03_unifi.png) |

| Segments | Device documentation |
|---|---|
| ![Segments](docs/screenshots/lanlens_02_segments.png) | ![Device Detail 2](docs/screenshots/lanlens_01_homeassistant.png) |

---

## Documentation

- [Knowledge Base / FAQ](docs/knowledgebase.md)
- [Extended documentation](docs/documentation.md)

---

## Quick Start

### Requirements

- Docker 20.10+ with `docker compose`
- Linux host recommended for raw ARP scanning (`network_mode: host`)

### 1. Get the compose file

```bash
curl -O https://raw.githubusercontent.com/AlexRosbach/LanLens/main/docker-compose.yml
```

### 2. Generate a secret key

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Replace `CHANGE_THIS_TO_A_LONG_RANDOM_STRING` in `docker-compose.yml` with the generated value.

### 3. Optional: choose the HTTP port

In `docker-compose.yml` you can change:

```yaml
- LANLENS_PORT=7765
```

Examples:
- `LANLENS_PORT=80` for direct port 80 in host mode
- `LANLENS_PORT=8080` for port 8080

### 4. Start LanLens

```bash
docker compose up -d
```

### 5. Open the UI

Open:

```text
http://<your-host-ip>:<LANLENS_PORT>
```

Default credentials:

```text
admin / admin
```

You will be forced to change the password on first login.

---

## Configuration

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | — | Required, at least 32 random characters |
| `DEFAULT_ADMIN_PASSWORD` | `admin` | Initial admin password |
| `LANLENS_PORT` | `7765` | HTTP port exposed by nginx, also usable in host mode |
| `BACKEND_PORT` | `17765` | Internal FastAPI port behind nginx |
| `DB_PATH` | `/data/lanlens.db` | SQLite database path |
| `TZ` | `UTC` | Container timezone |

### DHCP tagging and scan range

In **Settings → Network** LanLens now keeps these concerns separate:

- **DHCP range**: used for DHCP tagging / classification only
- **Scan range**: used for the active ARP network scan on the directly reachable Layer-2 network
- **Additional routed scan targets**: optional IPv4 CIDRs/addresses scanned with `nmap -sn` for other routed subnets
- **Scan interval**: controls the schedule

Notes:
- LanLens auto-detects the host subnet as the default scan range when no explicit scan range was saved yet.
- The configured `scan start` and `scan end` define the actual IPv4 scan range, so larger ranges inside the directly reachable local network are supported.
- ARP scanning works directly only on the locally reachable Layer-2 network. Use **Additional routed scan targets** for other subnets, for example `192.168.10.0/24`.
- Routed subnet discovery uses nmap ping scan. Across routed networks, MAC addresses and vendor information are often unavailable; LanLens tracks those hosts as IP-only discoveries.

### Optional navigation pages

In **Settings → System → UI Settings**, optional sidebar entries can be enabled or hidden:

- **Services**: shows the global Services directory.
- **DHCP Monitor**: shows a DHCP server/options monitor. It is not a full DHCP process timeline; it actively sends a DHCP Discover probe from the LanLens host/container and displays which DHCP server answers with which options.

The DHCP Monitor requires host networking and raw packet permissions so LanLens can send a DHCP Discover and receive DHCP replies. Renewing a lease on another workstation may not be visible on a normal switched network because DHCP renewal ACKs are often unicast directly to that client.

### Telegram

Configure Telegram in **Settings → Notifications**:
- bot token
- chat ID
- optional test message

### Webhook / Gotify

LanLens can also send new-device notifications to a generic JSON webhook, including Gotify.

Configure this in **Settings → Notifications → Webhook / Gotify**:
- enable webhook notifications
- enter the full webhook URL
- send a test webhook

For Gotify, use the complete message endpoint including the app token, for example:

```text
https://gotify.example.com/message?token=YOUR_APP_TOKEN
```

LanLens sends JSON with `title`, `message`, `priority`, `event_type`, `device_id`, and `source` fields.

Security notes:
- the stored webhook URL is treated as a secret in the settings API because Gotify-style URLs often contain tokens
- outbound webhook, i-doit and generic CMDB REST URLs are validated server-side before use
- private LAN targets are allowed for self-hosted deployments, while loopback, link-local, multicast, reserved, unspecified and cloud metadata addresses are rejected
- outbound webhook, i-doit JSON-RPC and generic CMDB REST requests connect to the validated resolved address while preserving the original Host/SNI to reduce DNS-rebinding risk
- redirects are not followed for generic CMDB REST calls

---

## Using MariaDB / External Database

By default LanLens uses **SQLite** stored in `/data/lanlens.db`. For production environments or when you need shared database access, you can switch to **MariaDB** or **MySQL**.

### Requirements

Install the `PyMySQL` driver in the container:

```dockerfile
RUN pip install PyMySQL
```

Or add to `requirements.txt`:
```
PyMySQL>=1.1.0
```

### docker-compose Configuration

```yaml
services:
  lanlens:
    image: alexrosbach/lanlens:latest
    environment:
      DATABASE_URL: mysql+pymysql://lanlens:yourpassword@mariadb:3306/lanlens
      SECRET_KEY: your-secret-key-here
    depends_on:
      - mariadb

  mariadb:
    image: mariadb:11
    environment:
      MYSQL_ROOT_PASSWORD: rootpassword
      MYSQL_DATABASE: lanlens
      MYSQL_USER: lanlens
      MYSQL_PASSWORD: yourpassword
    volumes:
      - mariadb_data:/var/lib/mysql

volumes:
  mariadb_data:
```

### Connection String Formats

| Database   | Format |
|------------|--------|
| MariaDB/MySQL | `mysql+pymysql://user:pass@host:3306/dbname` |
| PostgreSQL | `postgresql+psycopg2://user:pass@host:5432/dbname` |
| SQLite (default) | set via `DB_PATH` env var, not `DATABASE_URL` |

### Backup

When using MariaDB, use `mysqldump` for backups:

```bash
mysqldump -u lanlens -p lanlens > lanlens-backup.sql
```

Restore:
```bash
mysql -u lanlens -p lanlens < lanlens-backup.sql
```

> **Note:** The SQLite database export button in Settings is not available when using MariaDB. Use your database's native backup tools instead.

---

## Deep Scan — Required Permissions

The deep scan connects to devices via SSH (Linux) or WinRM (Windows) and runs read-only commands.
No data is written to the target system.

### Linux SSH

A **dedicated, non-root user** is recommended. The user needs read access to the relevant system files and commands:

```bash
# Create a dedicated scan user on the target Linux system
sudo useradd -m -s /bin/bash lanlens-scan
sudo passwd lanlens-scan

# Grant read-only sudo access to the required commands (add to /etc/sudoers.d/lanlens)
cat <<'EOF' | sudo tee /etc/sudoers.d/lanlens
lanlens-scan ALL=(ALL) NOPASSWD: /usr/bin/lscpu, /usr/bin/free, /usr/bin/lsblk, \
  /usr/bin/systemctl, /usr/bin/docker, /usr/bin/podman, \
  /usr/sbin/virsh, /usr/sbin/qm, /usr/sbin/pct, /usr/bin/k3s
EOF
```

> Most commands work without `sudo` on typical server installations. If you use root access, set username to `root` and store the password in the credential vault.

**Minimum requirements per profile:**

| Profile | Minimum required |
|---|---|
| `hardware_only` | Read access to `/sys/class/dmi/id/` and `/proc` |
| `os_services` | + `systemctl` read access |
| `linux_container_host` | + `docker ps` / `podman ps` |
| `hypervisor_inventory` | + `virsh list`, `qm list`, `pct list`, `qm config`, `pct config` |
| `full` | All of the above |

For **Proxmox** hosts, the scan user must be a member of the `kvm` group (or root):

```bash
sudo usermod -aG kvm lanlens-scan
```

### Windows WinRM

WinRM (Windows Remote Management) must be enabled on the target:

```powershell
# Run as Administrator on the target Windows system
Enable-PSRemoting -Force
# Allow connection from the LanLens host (replace with your LanLens server IP)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "YOUR_LANLENS_IP" -Force
```

**Recommended account:** A member of the local **Administrators** group or **Remote Management Users** group.
For domain environments, a domain account with local admin rights on the target is sufficient.

```powershell
# Add user to Remote Management Users (less privileged than full Admin)
Add-LocalGroupMember -Group "Remote Management Users" -Member "lanlens-scan"
# Some WMI queries (licensing, features) require local Admin
Add-LocalGroupMember -Group "Administrators" -Member "lanlens-scan"
```

> For the `windows_audit` profile (Windows Features, licensing, AD, DHCP), the account needs local Administrator rights on the target.

---

## Updating

> **⚠ Upgrading to v1.4.0**
>
> This release adds new database tables (credential vault, deep scan runs, findings, host/guest relationships).
> The migration runs automatically on container start and is non-destructive — existing data is preserved.
> **A database backup before updating is strongly recommended:**
>
> ```bash
> docker cp lanlens:/data/lanlens.db ./lanlens_backup_$(date +%Y%m%d).db
> ```

```bash
docker compose pull
docker compose up -d
```

For local builds:

```bash
docker compose up -d --build
```

Database migrations run automatically on container start.

## Releases

- Docker images are published on Docker Hub at [`alexrosbach/lanlens`](https://hub.docker.com/r/alexrosbach/lanlens)
- Pull `alexrosbach/lanlens:latest` for the newest build, or pin `alexrosbach/lanlens:1.5.0` for this release.
- GitHub releases should be maintained for release-based update checks and Telegram update notifications
- Detailed project history lives in [CHANGELOG.md](CHANGELOG.md)

---

## i-doit / CMDB Sync (v1.5.0 dev)

LanLens 1.5.0 starts the one-way i-doit integration foundation. LanLens is intended to be the source of truth and i-doit the target, but this first slice is deliberately limited to configuration, connection checks, local mapping validation, payload preview, sync-state tracking and audit logs. It does **not** perform live i-doit object/category writes yet.

1. Configure the i-doit base URL, JSON-RPC path, portal URL and API key in the `/api/idoit/config` API.
2. Choose the writable i-doit field used for LanLens sync/reference/status metadata (`idoit_sync_status_field`).
3. Import or edit the mapping JSON. `objectType` is only the fallback; `objectTypeByDeviceClass` can route routers, switches, printers, firewalls, etc. into non-server i-doit object types.
4. Run `POST /api/idoit/test-connection`.
5. Run `POST /api/idoit/test-mapping` for local JSON structure validation. This does not verify remote i-doit object types/categories/fields yet.
6. Run `POST /api/idoit/devices/{device_id}/dry-run` to inspect the generated payload before any future live sync implementation.
7. Use `POST /api/idoit/devices/{device_id}/sync` only as a LanLens-side validation/state marker in this release; it records no upstream i-doit write.

The i-doit API access model is the same for i-doit Cloud and on-prem installations for this use case: LanLens talks to the i-doit JSON-RPC API using a configurable URL, JSON-RPC path and API key. On-prem deployments can keep the default `/src/jsonrpc.php` path or set a custom reverse-proxy path; Cloud installations may differ in URL, enabled modules, token creation flow, and user permissions. The portal URL is stored separately so device detail pages can link directly to matched i-doit objects (`?objID=...`) without assuming that the JSON-RPC endpoint is also the browser entry point.

Recommended i-doit permissions: create/update only the object types and categories you want LanLens to manage. Avoid administrator-wide tokens for routine sync.

Matching strategy for environments where i-doit already contains objects:

1. Use an existing i-doit object ID when a LanLens device is already linked.
2. Prefer a stable LanLens/CMDB external reference field (`cmdb_id` / configured `externalIdField`).
3. Fall back to exact MAC address matches.
4. Fall back to hostname/IP only as warning-level candidates, not automatic writes.
5. Create a new object only when no confident match exists.

This keeps the scan enrichment one-way and predictable: LanLens colors/enriches discovered devices locally, prepares the mapped i-doit payload, links to existing objects when confidently matched, and only creates new i-doit objects once the live write path is enabled and the match result is unambiguous.

Troubleshooting checklist:

- Authentication failed: verify API key/token and JSON-RPC endpoint URL.
- Object type/category/field not found: adjust the mapping JSON to your i-doit schema.
- Selected sync status field is not writable: choose another writable custom/status/reference field.
- Duplicate or uncertain match: prefer LanLens `cmdb_id` as the primary external reference, then MAC, then hostname/IP only with warning.

### Generic CMDB REST API (v1.5.0 dev)

LanLens also exposes a connector-neutral CMDB REST foundation for tools that are not i-doit. This is meant for bidirectional CMDB workflows where LanLens can be queried as a discovery/inventory source and can explicitly push mapped device payloads to another REST-capable CMDB.

Jira Service Management Assets and ServiceNow CMDB are planned connector targets for this generic foundation, but they are **not tested or supported as native integrations yet**. Existing market tools such as Atlassian Assets Discovery, ServiceNow Discovery, Lansweeper, Device42 and similar ITAM/CMDB discovery products already cover broad enterprise discovery scenarios. LanLens' intended niche is smaller self-hosted and homelab-style environments where lightweight network discovery, local documentation, and explicit CMDB export/sync are more useful than a full enterprise discovery suite.

Available endpoints:

- `GET /api/cmdb/devices` — authenticated, paginated device inventory export with filters for `changed_since`, `segment_id`, `online`, `registered`, and `device_class`.
- `GET /api/cmdb/config` / `PUT /api/cmdb/config` — generic REST connector configuration. Secrets are stored in settings but only reported as configured/not configured.
- `POST /api/cmdb/test-connection` — validates the configured REST endpoint reachability.
- `POST /api/cmdb/test-mapping` — validates the local LanLens-field to CMDB-field mapping JSON.
- `POST /api/cmdb/devices/{device_id}/dry-run` — previews the outbound payload without writing externally.
- `POST /api/cmdb/devices/{device_id}/push` — explicitly sends one mapped device payload to the configured CMDB REST target.
- `POST /api/cmdb/import/preview` — fetches external CMDB data and returns a sample only; no LanLens write is performed in this foundation slice.
- `GET /api/cmdb/logs` — audit log for generic CMDB REST actions.

Supported outbound auth modes are `none`, bearer token, basic auth, and a custom header token. Supported write methods are `POST`, `PUT`, and `PATCH`. Import conflict strategies are stored as configuration (`fill_empty`, `cmdb_wins`, `lanlens_wins`, `manual_review`) so later live import/write behavior can use the same settings safely.

Security notes:

- CMDB REST URLs are server-side validated with the same SSRF guard used for webhook/i-doit URLs.
- Secrets are never returned by config endpoints, logs, dry-runs, or exports.
- Pull/export endpoints require the normal LanLens API authentication.
- Import currently has preview-only behavior; it does not mutate LanLens devices.

### Inventory operations (v1.5.0 dev)

LanLens 1.5.0 also starts the inventory-operations foundation requested in issues #60–#65:

- **Network map**: `/network-map` and `GET /api/inventory/topology` expose a read-only segment-grouped topology with host/guest relationships where known.
- **Change timeline**: device edits, status refreshes, IP/hostname/online-state changes and merge actions are written to `device_change_events` and shown on the device detail page.
- **Maintenance/noise control**: devices can be ignored, muted, or placed in maintenance until a timestamp; Telegram/webhook notifications skip muted/ignored/active-maintenance devices.
- **Ignore rules**: `/inventory-tools` and `/api/ignore-rules` provide the first rule-management surface for noisy devices/patterns. Discovery-side enforcement is intentionally conservative in this first slice.
- **Duplicate handling**: `/inventory-tools` can preview and run a manual device merge using a safe fill-empty strategy while moving related child records where possible.
- **Reports**: `GET /api/inventory/report?format=markdown|csv|json` exports sanitized network documentation without secrets.
- **Selective backup**: `GET /api/backups/selective` exports settings/documentation/segments/services/ignore rules without secrets. Import is preview-only via `POST /api/backups/selective/import-preview` in this slice.

These features are included in the 1.5.0 PR as practical MVP foundations. Some advanced behavior, such as graphical drag-layout persistence, full discovery-side ignore enforcement, encrypted secret export, and automatic merge suggestions, is intentionally left for later hardening.

---

## Password Reset

```bash
docker exec -it lanlens reset-password
```

Or non-interactive:

```bash
docker exec -it lanlens reset-password --password "MyNewPassword123"
```

---

## Development

### Backend

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

export SECRET_KEY=dev-secret-key-at-least-32-chars-long
export DB_PATH=./data/lanlens.db
mkdir -p data

python backend/cli/init_db.py
python backend/cli/init_admin.py
uvicorn backend.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## Architecture

- **Backend:** FastAPI, SQLAlchemy, SQLite, APScheduler
- **Frontend:** React, TypeScript, Tailwind, Vite
- **Scanning:** scapy and nmap
- **Notifications:** Telegram Bot API
- **Serving:** nginx + uvicorn in one container

---

## Versioning and Changelog

LanLens follows **Semantic Versioning**.

- Current app version is shown in the UI and via `GET /api/health`
- Project history is maintained in [CHANGELOG.md](CHANGELOG.md)
- Release-based update checks and Telegram update notifications rely on populated GitHub Releases

---

## Security Notes

- `SECRET_KEY` must be strong and unique
- `NET_RAW` is required for ARP scan support
- For HTTPS, place LanLens behind a reverse proxy
- Session handling is server-side via HTTP-only cookie flow, not browser storage

---

## License

MIT License, see [LICENSE](LICENSE).

> Dependency note: this project uses `scapy` and `python-nmap`. Check their licenses when redistributing bundled builds.
