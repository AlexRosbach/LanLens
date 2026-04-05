<div align="center">

<img src="frontend/public/logo.svg" alt="LanLens Logo" width="80" height="80" />

# LanLens

**Self-hosted network monitoring & documentation dashboard**

[![Version](https://img.shields.io/badge/version-1.1.0-6366f1)](https://github.com/AlexRosbach/LanLens/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Docker Hub](https://img.shields.io/docker/pulls/alexrosbach/lanlens?color=0ea5e9)](https://hub.docker.com/r/alexrosbach/lanlens)

LanLens continuously scans your local network, identifies every device by MAC address, and gives you a clean dark-themed web UI to manage, document, and connect to them — all in a single Docker container.

</div>

---

## Screenshots

> _Dashboard, Device Detail with documentation fields, and the service preset picker._

---

## Features

| Category | What LanLens does |
|---|---|
| **Network Scanning** | ARP broadcast scan at configurable intervals — finds every device on the LAN |
| **Device Identification** | Offline MAC vendor lookup (no cloud dependency) + heuristic device class detection |
| **DHCP Tagging** | Devices within the configured DHCP range are automatically tagged with a **DHCP** badge |
| **Segments** | Group devices into named segments (e.g. _Server_, _IoT_, _DMZ_) with a colour, IP range, and description |
| **Documentation** | Per-device fields: label, purpose, location, responsible, OS/firmware, asset tag, password location, notes |
| **Services** | Document all services running on a device (Grafana, Portainer, N8N …) with URL, credentials hint, and notes. 20 built-in presets. |
| **One-click Connect** | SSH link, RDP file download, or direct browser open — based on open port scan results |
| **Port Scanning** | nmap-based per-device scan with service detection |
| **Telegram Notifications** | Get alerted when a new, unknown device joins your network |
| **Auth** | JWT sessions, forced password change on first login, CLI password reset |
| **Dark / Light Mode** | Toggle between dark and light themes — preference is saved in the browser |
| **Language** | UI available in **English** and **German** — switch in the top navigation bar |
| **Mobile Optimised** | Responsive layout with a slide-in sidebar — fully usable on phones and tablets |
| **Update Check** | The sidebar automatically notifies you when a new version is available on GitHub |

---

## Quick Start

### Prerequisites

- Docker ≥ 20.10 with the **Compose plugin** (`docker compose`) or standalone Docker Compose v2
- A **Linux host** (raw ARP socket scanning requires `network_mode: host`)

### 1 — Get the compose file

**Option A — Pull from Docker Hub (recommended, no Git required)**

```bash
curl -O https://raw.githubusercontent.com/AlexRosbach/LanLens/main/docker-compose.yml
```

**Option B — Clone the repository (for local development / custom builds)**

```bash
git clone https://github.com/AlexRosbach/LanLens.git
cd LanLens
```

### 2 — Generate a secret key

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Open `docker-compose.yml` and replace `CHANGE_THIS_TO_A_LONG_RANDOM_STRING` with the output.

### 3 — Start

The compose file uses `image: alexrosbach/lanlens:latest` — Docker pulls the image automatically on first start.

```bash
# Modern Docker (plugin syntax — recommended)
docker compose up -d

# Legacy standalone docker-compose
docker-compose up -d
```

### 4 — Open the UI

Navigate to **`http://<your-host-ip>:7765`**

The exact URL is printed in the container logs on every start:
```
docker logs lanlens
```

Default credentials: **`admin` / `admin`**

You will be redirected to a forced password-change screen on first login.

---

## Configuration

### Environment variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `SECRET_KEY` | — | **Yes** | JWT signing key — must be ≥ 32 random characters. App refuses to start otherwise. |
| `DEFAULT_ADMIN_PASSWORD` | `admin` | No | Initial admin password (set before first run) |
| `DB_PATH` | `/data/lanlens.db` | No | SQLite database path inside the container |
| `TZ` | `UTC` | No | Container timezone, e.g. `Europe/Berlin` |

### Scan range

1. Open **Settings → Network**
2. Set **Start IP** and **End IP** to cover your DHCP range (e.g. `192.168.1.1` – `192.168.1.254`)
3. Adjust the **scan interval** (default: every 5 minutes)
4. Save — the scheduler reloads immediately

### Telegram notifications

1. Create a bot via [@BotFather](https://t.me/BotFather) — send `/newbot`, copy the token
2. Find your Chat ID:
   - _Personal:_ start a chat with the bot, open `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - _Group:_ add the bot, send a message, look for the negative chat ID in `getUpdates`
3. Open **Settings → Notifications**, paste both values, click **Send Test**
4. Enable notifications and save

---

## Password Reset

If you lose access, reset the admin password directly without going through the API:

```bash
# Interactive — prompts for a new password
docker exec -it lanlens reset-password

# Non-interactive
docker exec -it lanlens reset-password --password "MyNewPassword123"
```

The admin account will require a password change again on next login.

---

## Services Documentation

Each device in LanLens can have any number of **services** attached to it — handy for building a living network documentation:

- Choose from **20 built-in presets**: Grafana, Portainer, Proxmox, N8N, Nextcloud, Home Assistant, Vaultwarden, Pi-hole, Plex, Jellyfin, and more
- Store the **URL**, port, protocol, and version
- Add **login hints** and a **password location** reference (e.g. _"Vaultwarden → Servers"_)
- Free-text notes per service
- Click **Open** to jump directly to the service URL

---

## Connecting to Devices

After a port scan, LanLens displays one-click connection buttons based on open ports:

| Button | Protocol | Port | Action |
|---|---|---|---|
| SSH | SSH | 22 | Opens `ssh://ip` — launches your system SSH client |
| RDP | RDP | 3389 | Downloads a `.rdp` file — open with Remote Desktop |
| HTTPS | Web | 443 | Opens a new browser tab |
| HTTP | Web | 80 | Opens a new browser tab |
| :8443 / :8080 / … | Web | any | Opens a new browser tab |

If no port scan has been run yet, a **Scan Ports** button is shown instead.

---

## Update Notifications

LanLens checks the [GitHub Releases API](https://github.com/AlexRosbach/LanLens/releases) once on load and every 6 hours.
When a newer version is found, a **yellow banner** appears in the sidebar showing the version and a direct link to the release notes.
Click **Dismiss** to hide it until the next release.

To update:

```bash
# Docker Hub image — pull latest and restart (data volume is preserved)
docker compose pull
docker compose up -d

# Local build — rebuild and restart
docker compose up -d --build
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Docker Container  (network_mode: host)                  │
│                                                          │
│  ┌──────────┐    /         ┌──────────────────────────┐  │
│  │  nginx   │──────────── ▶│  React SPA  (dist/)      │  │
│  │  :80     │    /api  /ws │                          │  │
│  └──────────┘──────────── ▶│  FastAPI + uvicorn :8000 │  │
│                            │                          │  │
│                            │  Routers:                │  │
│                            │    auth · devices        │  │
│                            │    scan · services       │  │
│                            │    settings · connect    │  │
│                            │    notifications         │  │
│                            │    segments              │  │
│                            │                          │  │
│                            │  Services:               │  │
│                            │    ARP scanner (scapy)   │  │
│                            │    Port scanner (nmap)   │  │
│                            │    MAC vendor lookup     │  │
│                            │    Telegram notifier     │  │
│                            │    APScheduler           │  │
│                            └──────────┬───────────────┘  │
│                                       │                   │
│                            ┌──────────▼──────────┐        │
│                            │  SQLite  /data/      │        │
│                            └─────────────────────┘        │
└──────────────────────────────────────────────────────────┘
```

### Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy (SQLite) · incremental migrations |
| Network scanning | scapy (ARP) · python-nmap (port scan) |
| MAC lookup | manuf — offline IEEE OUI database |
| Auth | python-jose (JWT) · passlib/bcrypt |
| Scheduler | APScheduler |
| Notifications | httpx → Telegram Bot API |
| Frontend | React 18 · TypeScript · Tailwind CSS · Vite |
| State | Zustand |
| Serving | nginx + uvicorn (single container) |

---

## Device Classes

| Class | Description |
|---|---|
| Server | Physical or bare-metal servers |
| VM | Virtual machines |
| IoT | Raspberry Pi, smart home devices, sensors |
| Router | Routers and wireless access points |
| Switch | Network switches |
| Workstation | Desktops and laptops |
| NAS | Network-attached storage (Synology, QNAP, TrueNAS) |
| Printer | Network printers and MFDs |
| Unknown | Unidentified or uncategorised devices |

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
npm run dev    # Vite dev server on :5173 — proxies /api → localhost:8000
```

---

## Security Notes

- **`SECRET_KEY`** — the application exits at startup if the key is missing, set to a known placeholder, or shorter than 32 characters.
- **`NET_RAW` capability** — required for ARP scanning with scapy. Only grant this to trusted containers on trusted networks.
- **HTTPS** — LanLens speaks plain HTTP internally. For HTTPS, put it behind a reverse proxy (Traefik, Caddy, nginx).
  ```yaml
  # Remove network_mode: host and expose a port instead:
  ports:
    - "127.0.0.1:8080:80"
  ```
- **JWT tokens** — access tokens are stored in memory (Zustand), not `localStorage`. Logout blacklists the token server-side.

---

## Versioning

LanLens follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`

| Change | Version bump |
|---|---|
| Breaking change / major rework | MAJOR |
| New feature, backwards-compatible | MINOR |
| Bug fix, security patch | PATCH |

The current version is visible in the **sidebar** of the UI and at `GET /api/health`.
All releases are tagged on GitHub and listed on the [Releases page](https://github.com/AlexRosbach/LanLens/releases).
Docker Hub images are published at [`alexrosbach/lanlens`](https://hub.docker.com/r/alexrosbach/lanlens).

---

## Upgrading

LanLens applies schema migrations automatically on every container start — no manual SQL steps required.
The migration script (`backend/cli/migrate_db.py`) is idempotent and safe to run multiple times.

```bash
# Docker Hub (recommended)
docker compose pull && docker compose up -d

# Local build
docker compose up -d --build
```

Your data volume (`lanlens_data`) is preserved across upgrades.

---

## Changelog

### v1.1.0 — UI overhaul, Segments & DHCP tagging

#### New features
- **Dark / Light mode** — theme toggle in the top navigation bar; preference persisted in `localStorage`
- **Language switcher** — switch between English and German at any time from the top bar
- **Segments** — create named network segments (e.g. _Server_, _IoT_, _DMZ_) with a custom colour and optional IP range; assign devices to segments and filter the device list by segment
- **DHCP tagging** — devices within the configured DHCP range are automatically tagged with a coloured **DHCP** badge in the device list and on the detail page
- **Mobile optimisation** — responsive layout with a slide-in overlay sidebar and hamburger menu; device table collapses non-essential columns on small screens

#### Bug fixes
- **Add Services popup cut off** — modal now scrolls internally (`max-height: 90vh`) and no longer clips on small screens
- **Time displayed incorrectly** — UTC timestamps stored without a `Z` suffix are now parsed correctly, fixing wrong relative-time display in non-UTC locales
- **Known devices shown as “new device detected”** — registering a device now automatically marks its pending `new_device` notification as read
- **LanLens logo did not navigate home** — clicking the logo in the sidebar now always navigates to `/`
- **“New” badge persisted after viewing** — viewed device IDs are stored in `localStorage`; the badge disappears as soon as the detail page is opened
- **Notification counter not decrementing** — sidebar badge reads the real unread count from the API and updates correctly on mark-as-read and delete

#### Database migration
- `devices.segment_id` column is added automatically on container startup via `backend/cli/migrate_db.py` — safe for existing installations, no data loss

### v1.0.2 — Port & startup log

- Changed default port from `80` to **`7765`** to avoid conflicts with other services already bound to port 80 on the host
- Startup log now shows all host IP addresses, the direct access URL (`http://<ip>:7765`), and the default credentials

### v1.0.1 — Build fix

- Fixed Docker image build failure: `gcc` and `python3-dev` are now installed temporarily during `pip install` to compile the `netifaces` C extension, then removed to keep the image lean

### v1.0.0 — Initial Release

- Full network scanning (ARP + nmap) in a single Docker container
- Device management: label, classify, notes
- **Device documentation**: purpose, location, responsible, OS/firmware, asset tag, password location, description
- **Services sub-system**: document every service running on a device with 20 presets (Grafana, Portainer, Proxmox, N8N, …)
- One-click connect: SSH link, RDP file, web browser
- Telegram notifications for new devices
- JWT authentication with forced first-login password change
- CLI password reset (`docker exec lanlens reset-password`)
- Update notification in sidebar (checks GitHub Releases every 6 hours)
- Dark-themed React + Tailwind UI

---

## License

MIT License — see [LICENSE](LICENSE) for full text.

> **Dependency notice:** This project depends on [`scapy`](https://scapy.net/) and [`python-nmap`](https://pypi.org/project/python-nmap/), both licensed under **GPL-2.0**. When redistributing this software as a compiled or bundled artifact, you must comply with GPL-2.0 terms for those dependencies. The LanLens source code itself is MIT-licensed.
