# LanLens — Technical Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Database Schema](#database-schema)
4. [API Reference](#api-reference)
5. [Scanning Logic](#scanning-logic)
6. [Authentication](#authentication)
7. [Telegram Integration](#telegram-integration)
8. [Connection Launch](#connection-launch)
9. [Docker Details](#docker-details)
10. [CLI Tools](#cli-tools)
11. [Frontend Structure](#frontend-structure)
12. [Configuration Reference](#configuration-reference)
13. [Deep Scan](#deep-scan)
14. [Troubleshooting](#troubleshooting)

---

## Overview

LanLens is a single-container Docker application that:

- Periodically scans the local network via ARP broadcast
- Identifies device vendors from MAC addresses using the offline IEEE OUI database
- Classifies devices heuristically (Server, VM, IoT, Router, etc.)
- Performs per-device port scans using nmap
- Provides a React-based dark-themed web UI for management
- Sends Telegram notifications for newly discovered devices
- Supports SSH link, RDP file download, and web browser connection

---

## Architecture

```
Dockerfile (multi-stage build):
  Stage 1 — Node 20 Alpine: npm ci && npm run build → /app/frontend/dist/
  Stage 2 — Python 3.12 Slim:
    - nginx (reverse proxy + static files)
    - uvicorn (FastAPI application server on 127.0.0.1:8000)
    - SQLite database at /data/lanlens.db (Docker volume)

Request flow:
  Browser → nginx:80 → /api/* → uvicorn:8000 → FastAPI
                     → /ws/*  → uvicorn:8000 → WebSocket
                     → /*     → /app/frontend/dist/ (static)
```

### Directory Structure

```
backend/
  main.py           FastAPI application, lifespan, WebSocket endpoint
  config.py         Pydantic settings from environment variables
  database.py       SQLAlchemy engine + SessionLocal factory
  models.py         ORM models (User, Device, PortScan, ScanRun, Setting, Notification, TokenBlacklist)
  schemas.py        Pydantic request/response models
  auth/
    jwt_handler.py  create_access_token, decode_token
    password.py     hash_password, verify_password (bcrypt)
    dependencies.py get_current_user FastAPI dependency
  routers/
    auth.py         /api/auth/* — login, logout, me, change-password
    devices.py      /api/devices/* — CRUD, port scan trigger
    scan.py         /api/scan/* — start, status, history
    settings.py     /api/settings/* — dhcp, telegram, schedule
    notifications.py /api/notifications/* — list, read-all, delete
    connect.py      /api/connect/* — RDP file download
  services/
    scanner.py      ARP scan with scapy, device upsert logic
    port_scanner.py nmap port scan, returns open ports + protocol flags
    mac_vendor.py   OUI lookup via manuf library
    device_classifier.py  Vendor/hostname/port heuristics → device class
    notification.py Telegram message sending via httpx
    scheduler.py    APScheduler background scan loop
  cli/
    init_db.py      Create SQLite tables (idempotent)
    init_admin.py   Create default admin user if none exists
    reset_password.py  CLI tool for password reset

frontend/
  src/
    api/            Axios-based typed API clients per domain
    store/          Zustand state stores (auth, devices)
    components/
      ui/           Button, Input, Modal, Badge, Card, Spinner
      layout/       Sidebar, TopBar, Layout
      devices/      DeviceTable, ConnectButtons, DeviceClassIcon, RegisterDeviceModal
    pages/          Login, ForcePasswordChange, Dashboard, DeviceDetail, Settings, Notifications
    utils/          formatters, connectionUtils
    assets/         logo.svg (original SVG design)
```

---

## Database Schema

### `users`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| username | TEXT UNIQUE | Login username |
| password_hash | TEXT | bcrypt hash (cost 12) |
| force_password_change | BOOLEAN | True on first login |
| created_at | DATETIME | UTC |
| last_login | DATETIME | UTC, nullable |

### `devices`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| mac_address | TEXT UNIQUE | Uppercase colon-separated (XX:XX:XX:XX:XX:XX) |
| ip_address | TEXT | Last seen IPv4 address |
| hostname | TEXT | PTR DNS reverse lookup |
| label | TEXT | User-assigned name |
| device_class | TEXT | Server / VM / IoT / Router / Switch / Workstation / NAS / Printer / Unknown |
| vendor | TEXT | From OUI database |
| notes | TEXT | Free text |
| is_registered | BOOLEAN | User has explicitly labeled this device |
| is_online | BOOLEAN | Seen in last ARP scan |
| first_seen | DATETIME | UTC |
| last_seen | DATETIME | UTC |

### `port_scans`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | |
| device_id | INTEGER FK | → devices.id (CASCADE DELETE) |
| scanned_at | DATETIME | UTC |
| open_ports | TEXT | JSON array of `{port, protocol, service, state}` |
| ssh_available | BOOLEAN | Port 22 open |
| rdp_available | BOOLEAN | Port 3389 open |
| http_available | BOOLEAN | Port 80 open |
| https_available | BOOLEAN | Port 443 open |

### `scan_runs`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | |
| started_at | DATETIME | |
| finished_at | DATETIME | Nullable |
| scan_type | TEXT | `arp` / `full` / `scheduled` / `manual` |
| devices_found | INTEGER | Total hosts in this scan |
| devices_new | INTEGER | New MACs discovered |
| devices_offline | INTEGER | Previously online, now absent |
| status | TEXT | `running` / `done` / `error` |
| error_message | TEXT | Nullable |

### `settings`

| Column | Type | Description |
|--------|------|-------------|
| key | TEXT PK | Setting name |
| value | TEXT | String value |
| updated_at | DATETIME | |

**Known keys:**
- `dhcp_start` — Network scan start IP
- `dhcp_end` — Network scan end IP
- `scan_interval_minutes` — Scheduler interval
- `telegram_bot_token` — Telegram bot API token
- `telegram_chat_id` — Target chat/group ID
- `telegram_enabled` — `"true"` / `"false"`
- `notify_on_device_online` — `"true"` / `"false"`
- `notify_on_device_offline` — `"true"` / `"false"`

### `notifications`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | |
| device_id | INTEGER FK | → devices.id (SET NULL on delete) |
| event_type | TEXT | `new_device` / `device_online` / `device_offline` |
| message | TEXT | Human-readable description |
| is_read | BOOLEAN | UI read status |
| telegram_sent | BOOLEAN | Whether Telegram delivery succeeded |
| created_at | DATETIME | |

### `token_blacklist`

| Column | Type | Description |
|--------|------|-------------|
| jti | TEXT UNIQUE | JWT ID claim |
| expires_at | DATETIME | For cleanup |

---

## API Reference

### Authentication — `/api/auth`

#### `POST /api/auth/login`

```json
// Request
{ "username": "admin", "password": "secret" }

// Response 200
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "force_password_change": false
}
```

#### `GET /api/auth/me`

Returns current user. Requires `Authorization: Bearer <token>`.

#### `POST /api/auth/change-password`

```json
{ "current_password": "old", "new_password": "newpass123" }
```

---

### Devices — `/api/devices`

#### `GET /api/devices`

Query params: `online_only`, `unregistered_only`, `device_class`, `search`

Returns `DeviceListResponse` with `items`, `total`, `online`, `offline`, `unregistered`.

#### `PUT /api/devices/{id}`

```json
{
  "label": "My NAS",
  "device_class": "NAS",
  "notes": "Synology DS920+",
  "is_registered": true
}
```

#### `POST /api/devices/{id}/scan-ports`

Triggers background nmap port scan. Returns immediately with `202`-like response.

#### `GET /api/devices/{id}/ports`

Returns last 5 port scan results.

---

### Scan — `/api/scan`

#### `POST /api/scan/start`

Triggers immediate ARP scan in background.

#### `GET /api/scan/status`

```json
{
  "is_running": false,
  "last_scan": {
    "id": 42,
    "started_at": "2026-04-04T12:00:00",
    "finished_at": "2026-04-04T12:00:03",
    "devices_found": 14,
    "devices_new": 0,
    "devices_offline": 1,
    "status": "done"
  }
}
```

---

### Settings — `/api/settings`

#### `GET /api/settings` — Returns all settings as `AllSettings`

#### `PUT /api/settings/dhcp`
```json
{ "dhcp_start": "192.168.1.1", "dhcp_end": "192.168.1.254" }
```

#### `PUT /api/settings/scan-schedule`
```json
{ "scan_interval_minutes": 5 }
```

#### `PUT /api/settings/telegram`
```json
{
  "telegram_bot_token": "1234567890:ABCdef...",
  "telegram_chat_id": "-1001234567890",
  "telegram_enabled": true
}
```

#### `POST /api/settings/telegram/test` — Sends a test Telegram message

---

### Connect — `/api/connect`

#### `GET /api/connect/{id}/rdp`

Returns a `.rdp` file download with the device's IP pre-configured.

---

## Scanning Logic

### ARP Scan Flow

```
1. APScheduler triggers run_scan() every N minutes
2. scanner.py reads dhcp_start/dhcp_end from DB settings
3. Derives /24 network from dhcp_start (e.g., 192.168.1.0/24)
4. scapy: Ether(dst="ff:ff:ff:ff:ff:ff")/ARP(pdst=network)
   srp() with timeout=3s
5. For each (ip, mac) in responses:
   a. Normalize MAC to XX:XX:XX:XX:XX:XX
   b. mac_vendor.py: manuf.MacParser().get_manuf(mac) → vendor string
   c. DB upsert:
      - If MAC exists: update ip, last_seen, is_online=True
      - If new MAC: insert with is_registered=False, create Notification
   d. Reverse DNS lookup (socket.gethostbyaddr) in thread pool
6. MACs not in current scan: is_online = False
7. Write ScanRun summary to DB
8. Send pending Telegram notifications
```

### Port Scan Flow

```
1. Triggered by: POST /api/devices/{id}/scan-ports OR manual
2. port_scanner.py: nmap.PortScanner()
3. Arguments: "-sS -T4 --top-ports 1000" (SYN scan, fast)
   Fallback: "-sT -T4 --top-ports 1000" (TCP connect, no root needed)
4. Parse results: extract open ports, service names
5. Set flags: ssh_available, rdp_available, http_available, https_available
6. Write PortScan row to DB
```

---

## Authentication

### JWT Flow

1. Client sends `POST /api/auth/login` with credentials
2. Server verifies bcrypt hash, creates access token (8h expiry) with `jti` claim
3. Client stores token in localStorage
4. Every request includes `Authorization: Bearer <token>`
5. FastAPI's `get_current_user` dependency decodes + validates token
6. Logout: token is not explicitly blacklisted (stateless) — frontend clears it from localStorage

### Force Password Change

- New users have `force_password_change = True` in the DB
- `/api/auth/me` returns this flag
- Frontend route guard: if `force_password_change`, redirect all routes to `/change-password`
- After changing password: flag set to `False`, guard removed

---

## Telegram Integration

### Setup

1. Create bot: message `@BotFather` on Telegram, send `/newbot`
2. Get Chat ID:
   - Personal: `https://api.telegram.org/bot<TOKEN>/getUpdates` after sending a message to the bot
   - Group: Add bot to group, send message, check `getUpdates` for negative chat ID (e.g., `-1001234567890`)
3. Configure in LanLens Settings → Notifications

### Message Format

```
LanLens — New Device Detected

IP: 192.168.1.42
MAC: AA:BB:CC:DD:EE:FF
Vendor: Raspberry Pi Foundation
Class: IoT
Hostname: raspberrypi.local

Open LanLens to register this device.
```

### Failure Handling

- Failed Telegram sends are logged
- `telegram_sent = False` visible in the Notifications page
- No automatic retry (manual retry: save settings again and trigger a new scan)

---

## Connection Launch

### SSH

Frontend renders an `<a href="ssh://ip">` link. Clicking opens the system's default SSH client:
- macOS: Terminal
- Linux: depends on xdg-open configuration
- Windows: requires SSH URI handler (e.g., PuTTY configured as default)

### RDP

Frontend calls `GET /api/connect/{id}/rdp` which returns a `.rdp` file with:
```
full address:s:<ip>
authentication level:i:2
prompt for credentials:i:1
```
The browser downloads the file. Double-clicking opens:
- Windows: built-in Remote Desktop Connection (mstsc.exe)
- macOS: Microsoft Remote Desktop (if installed)
- Linux: Remmina or similar

### Web

Opens `http://ip` or `https://ip` in a new browser tab based on which ports are open.

---

## Docker Details

### Why `network_mode: host`

ARP scanning requires sending raw Ethernet frames to the broadcast address. This requires:
1. A raw socket (`AF_PACKET`)
2. Access to the host's physical network interface

`network_mode: host` makes the container share the host's network stack, giving it direct access to the physical NIC. This is the simplest and most reliable approach for ARP scanning.

**Alternative (bridge mode)**: Remove `network_mode: host` and add `ports: ["8080:80"]`. ARP scanning will not work from a bridge network. You would need to replace scapy ARP with nmap ping sweep (`-sn`) which uses ICMP and works without raw sockets.

### Capabilities

- `NET_ADMIN`: Required for interface configuration
- `NET_RAW`: Required for raw socket creation (ARP)

### Volume

`/data` is a Docker named volume containing:
- `lanlens.db` — SQLite database (all persistent state)

**Backup:** `docker run --rm -v lanlens_data:/data -v $(pwd):/backup alpine tar czf /backup/lanlens-backup.tar.gz /data`

---

## CLI Tools

### `reset-password`

Located at `/usr/local/bin/reset-password` inside the container.

```bash
# Interactive
docker exec -it lanlens reset-password

# Non-interactive
docker exec lanlens reset-password --password "MyNewPass123"
```

Implementation: directly connects to SQLite with `sqlite3` module, updates `password_hash` and sets `force_password_change=1`. Does not depend on FastAPI or any other running service.

### `init_db.py`

Creates all database tables if they don't exist. Safe to run repeatedly.

### `init_admin.py`

Creates the `admin` user with the default password if no users exist in the database. Safe to run repeatedly.

---

## Frontend Structure

### State Management (Zustand)

| Store | Contents |
|-------|---------|
| `authStore` | JWT token, user object, login/logout/refresh actions |
| `deviceStore` | Device list, stats (total/online/offline/unregistered), fetchDevices |

### Route Guards

```
/login          → AuthRoute: redirects to / if already logged in
/change-password → PasswordChangeRoute: requires token, no other guard
/*              → ProtectedRoute: requires token, force_password_change=false
```

### Real-time Updates

The `TopBar` polls `GET /api/scan/status` every 2 seconds while a scan is running to detect completion. A future enhancement would use the WebSocket endpoint (`/ws/scan-updates`) for push-based updates.

---

## Configuration Reference

### docker-compose.yml Environment Variables

```yaml
environment:
  SECRET_KEY: "your-64-char-random-string"   # Required
  DEFAULT_ADMIN_PASSWORD: "admin"             # First-run only
  TZ: "Europe/Berlin"                         # Container timezone
  DB_PATH: "/data/lanlens.db"                 # SQLite file path
```

### Supported Timezones

Any standard TZ database name: `UTC`, `Europe/Berlin`, `America/New_York`, `Asia/Tokyo`, etc.

---

## Troubleshooting

### ARP scan returns no devices

1. Verify `network_mode: host` is set in docker-compose.yml
2. Verify `cap_add: [NET_ADMIN, NET_RAW]` is set
3. Check that `dhcp_start` and `dhcp_end` match your actual network range
4. Run `docker exec lanlens ip route` — should show your host's routing table
5. Run `docker exec lanlens arp -a` — should show ARP cache

### "SECRET_KEY environment variable is not set"

Set a proper `SECRET_KEY` in `docker-compose.yml`. Generate one with:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Telegram test fails

1. Verify bot token format: `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`
2. Verify you have sent at least one message to the bot (for private chats)
3. For groups: ensure the bot is a member and the chat ID starts with `-100`
4. Check container logs: `docker logs lanlens`

### Port scan returns no results

nmap requires the SYN scan to run as root (which it does inside the container). If it still fails:
- Check target device firewall rules
- Try from the host: `nmap -sS -T4 --top-ports 100 <device-ip>`

### Database corruption

```bash
# Restore from backup
docker-compose down
docker run --rm -v lanlens_data:/data -v $(pwd):/backup alpine tar xzf /backup/lanlens-backup.tar.gz -C /
docker-compose up -d
```

### Reset everything (fresh start)

```bash
docker-compose down -v   # WARNING: deletes all data
docker-compose up -d
```

---

## Deep Scan

Deep scan is an **opt-in, credential-based** enrichment mode that collects detailed hardware, OS, service, container, and audit data from managed devices over SSH (Linux) or WinRM (Windows).

### Prerequisites

**Linux targets:**
- SSH service running and accessible from the LanLens host
- A user account with at least read access to `/etc/os-release`, `lscpu`, `free`, `lsblk`, and `systemctl`
- For hypervisor inventory: `virsh`, `qm`, or `pct` installed and accessible to the scan user

**Windows targets:**
- WinRM (Windows Remote Management) enabled: `Enable-PSRemoting -Force`
- NTLM authentication allowed (default)
- Port 5985 (HTTP) reachable from LanLens host
- For server roles/features: PowerShell with `Get-WindowsFeature` available (Windows Server)

### Credential vault

Credentials are managed in **Settings → Deep Scan Credentials**.

| Field | Description |
|-------|-------------|
| Name | Descriptive name for this credential set |
| Type | `Linux SSH` or `Windows WinRM` |
| Username | Login username on the target device |
| Password/Key | Encrypted at rest using Fernet (key derived from `SECRET_KEY`) |
| Description | Optional notes |

Credentials are **never returned in plaintext** by any API endpoint. The `encrypted_secret` column in the database contains a Fernet token and cannot be decrypted without the original `SECRET_KEY`.

> **Note:** If you rotate `SECRET_KEY`, existing credentials become unreadable and must be re-entered.

### Scan profiles

| Profile | Collects |
|---------|---------|
| `hardware_only` | CPU, RAM, disks, vendor/model from DMI |
| `os_services` | OS release, kernel, hostname, uptime, running systemd services |
| `linux_container_host` | OS + services + Docker/Podman containers, K3s pods |
| `windows_audit` | Windows OS, hardware, installed server roles/features, running services, licensing state, IIS sites, Hyper-V VMs, SQL Server, AD domain, DHCP scopes |
| `hypervisor_inventory` | OS + services + virsh/KVM VM list, Proxmox QEMU and container lists |
| `full` | All of the above |

### Per-device configuration

In the Device Detail page, expand the **Deep Scan** card:

1. Click **Configure**
2. Select a credential from the dropdown
3. Choose a scan profile
4. Optionally enable automatic scans and set an interval (minimum 5 minutes)
5. Click **Save Configuration**
6. Click **Run Deep Scan** to trigger an immediate scan

### Finding types

Findings are stored as key/value pairs grouped by `finding_type`:

| Type | Content |
|------|---------|
| `hardware` | CPU, RAM, disks, vendor, model, serial number |
| `os` | OS release, kernel version, hostname, uptime |
| `service` | Running systemd services (Linux) or Windows services |
| `container` | Docker/Podman containers, K3s pods |
| `hypervisor` | VM list from virsh/qm/pct |
| `vm_guest` | Enumerated VMs with MAC/IP where available |
| `audit` | Windows features, licensing, IIS, AD, DHCP, SQL Server |

### Hypervisor guest matching

When a hypervisor scan completes, LanLens attempts to match each discovered guest VM against known devices:

1. **MAC address match** (preferred) — compares guest MAC addresses from `virsh domiflist` against device MAC addresses in LanLens
2. **IP address match** (fallback) — compares guest IP addresses against device IP addresses in LanLens

Matched relationships are stored in `device_host_relationships` and displayed in the **Host / Guest** tab of both the host device and the guest device. Relationships are updated on each hypervisor scan (`last_confirmed_at` timestamp).

### Auto-scan scheduling

When `auto_scan_enabled` is set on a device, the deep scan scheduler (which polls every 60 seconds) will trigger a scan when `interval_minutes` has elapsed since `last_scan_at`. The scheduler ensures only one scan runs per device at a time.

### Security notes

- Credentials are encrypted using Fernet symmetric encryption. The key is derived from `SECRET_KEY` via SHA-256 and URL-safe base64 encoding.
- The `encrypted_secret` column is never returned by any API endpoint.
- All API endpoints require a valid session (HTTP-only cookie or Bearer token).
- SSH connections use `AutoAddPolicy` for host key acceptance — suitable for internal networks. If strict host key checking is required, configure the scan user with a pre-approved `known_hosts` file.
- WinRM connections use NTLM authentication over HTTP (port 5985). For production use, consider enabling HTTPS (port 5986) on Windows targets and updating the session URL accordingly.

### New database tables (v1.4.0)

| Table | Purpose |
|-------|---------|
| `credentials` | Encrypted credential store |
| `device_deep_scan_config` | Per-device scan settings (one row per device) |
| `deep_scan_runs` | Audit trail of every scan execution |
| `deep_scan_findings` | Structured findings (hardware, OS, services, etc.) |
| `device_host_relationships` | VM-to-host relationships |

All tables are created automatically by the migration script on container start and are cascade-deleted when the parent device is removed.

### New columns (v1.4.1)

| Table | Column | Type | Description |
|-------|--------|------|-------------|
| `credentials` | `auth_method` | `VARCHAR(16)` | `password` (default) or `key` (SSH private key) |
| `devices` | `cmdb_id` | `VARCHAR(64)` | Unique CMDB identifier (e.g. `DEV-0001`), nullable |

### New tables (v1.4.1)

| Table | Purpose |
|-------|---------|
| `auto_scan_rules` | Global rules for automatic deep scans by device class |

---

## CMDB IDs

Each registered device can receive an automatically generated CMDB identifier. The format is `{PREFIX}-{NNNN}` where prefix and digit count are configurable in **Settings → System → CMDB IDs**.

- IDs are generated on first device registration and can be regenerated from Device Detail.
- Uniqueness is enforced by a database unique index; the generator retries up to 3 times on concurrent collision before returning HTTP 409.
- Prefix defaults to `DEV`, digit count defaults to `4` (e.g. `DEV-0001`).

---

## External Database (MariaDB / PostgreSQL)

Set the `DATABASE_URL` environment variable to use an external database instead of the built-in SQLite file:

```yaml
environment:
  DATABASE_URL: "mysql+pymysql://user:password@host:3306/lanlens"
```

When `DATABASE_URL` is set:
- SQLite-specific migrations are skipped; `Base.metadata.create_all()` generates dialect-correct DDL.
- The database export endpoint returns HTTP 400 (SQLite-only feature).
- All incremental `ALTER TABLE` migrations are dialect-compatible and run on both SQLite and MariaDB.

See README for a full docker-compose example and connection string reference.

---

## SSH Key Authentication

Credentials of type `linux_ssh` support two authentication methods:

| `auth_method` | Secret content | Notes |
|---|---|---|
| `password` (default) | SSH password | Standard password-based SSH login |
| `key` | PEM private key (RSA, Ed25519, ECDSA, DSS) | Key stored Fernet-encrypted; supports all paramiko key types |

Select the auth method in the Credential Modal. The private key is stored encrypted and never returned by the API.

---

## UI Languages

The frontend supports three languages, switchable via the TopBar toggle (EN → DE → IT → EN) or the Settings page:

| Code | Language |
|------|----------|
| `en` | English |
| `de` | Deutsch |
| `it` | Italiano |

---

## Export & Import

**Settings → System → Export & Import** provides:

| Action | Endpoint | Description |
|--------|----------|-------------|
| Export Settings | `GET /api/admin/export/settings` | Downloads all settings as a JSON file |
| Export Database | `GET /api/admin/export/database` | Downloads the SQLite `.db` file (SQLite only) |
| Import Settings | `POST /api/admin/import/settings` | Uploads a previously exported settings JSON |

All admin endpoints require a fully set-up account (`force_password_change = false`).
