# LanLens

**LanLens** is a self-hosted network monitoring dashboard running as a single Docker container. It continuously scans your local network, identifies devices by MAC address, and provides a modern dark-themed web UI to manage and connect to your devices.

![LanLens Dashboard](docs/screenshot-placeholder.png)

---

## Features

- **Automatic Network Scanning** — ARP broadcast scan at configurable intervals
- **MAC Vendor Lookup** — Identifies device vendors offline (no cloud dependency)
- **Smart Device Classification** — Heuristic detection: Server, VM, IoT, Router, Switch, Workstation, NAS, Printer
- **One-Click Connect** — SSH link, RDP file download, or direct web browser open — based on port scan results
- **Port Scanning** — nmap-based per-device port scan with service detection
- **Device Management** — Label, classify, and add notes to devices
- **DHCP Range Configuration** — Define your network scan range in the UI
- **Telegram Notifications** — Get notified when new devices join your network
- **Secure Auth** — Forced password change on first login, JWT sessions
- **CLI Password Reset** — `docker exec lanlens reset-password`
- **Dark UI** — Modern React + Tailwind interface

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Linux host (required for ARP scanning with `network_mode: host`)

### 1. Clone and configure

```bash
git clone https://github.com/AlexRosbach/Network-docu.git
cd Network-docu
```

Edit `docker-compose.yml` and set a strong `SECRET_KEY`:

```bash
# Generate a secure key
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Replace `CHANGE_THIS_TO_A_LONG_RANDOM_STRING` in `docker-compose.yml` with the generated value.

### 2. Start LanLens

```bash
docker-compose up -d
```

### 3. Open the web interface

Navigate to `http://<your-host-ip>` (port 80).

**Default credentials:** `admin` / `admin`

You will be prompted to change the password on first login.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(required)* | JWT signing key — must be set to a long random string |
| `DEFAULT_ADMIN_PASSWORD` | `admin` | Initial admin password |
| `DB_PATH` | `/data/lanlens.db` | SQLite database path (inside container) |
| `TZ` | `UTC` | Container timezone (e.g. `Europe/Berlin`) |

### First Login

1. Open `http://<host-ip>` in your browser
2. Login with `admin` / `admin` (or your custom `DEFAULT_ADMIN_PASSWORD`)
3. You will be redirected to a **forced password change** screen
4. Set a new password (minimum 8 characters)
5. You're in!

### Setting Up Telegram Notifications

1. Open **Settings → Notifications** in LanLens
2. Create a Telegram bot via [@BotFather](https://t.me/BotFather) — send `/newbot`
3. Copy the bot token (format: `1234567890:ABCdefGHIjkl...`)
4. Find your Chat ID:
   - Personal: Start a chat with your bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Group: Add your bot to a group, send a message, check `getUpdates` for the negative chat ID
5. Paste the token and chat ID into LanLens Settings
6. Click **Send Test** to verify
7. Enable the toggle and save

### Configuring the Scan Range

1. Open **Settings → Network**
2. Set **Start IP** and **End IP** to match your DHCP range (e.g. `192.168.1.1` – `192.168.1.254`)
3. Set the **scan interval** (default: every 5 minutes)
4. Save — the scheduler updates immediately

### Manual Scan

Click **Scan Now** in the top bar at any time to trigger an immediate scan.

---

## Password Reset

If you lose access, reset the admin password directly via the Docker CLI:

```bash
# Interactive (prompts for new password)
docker exec -it lanlens reset-password

# Non-interactive (provide password directly)
docker exec -it lanlens reset-password --password "MyNewPassword123"
```

This bypasses the API entirely and works even if the app is misconfigured. The admin will be required to change the password again on next login.

---

## Device Classes

| Class | Icon | Description |
|-------|------|-------------|
| Server | Rack server | Physical or bare-metal servers |
| VM | Stacked layers | Virtual machines |
| IoT | Circuit board | Raspberry Pi, smart home devices, sensors |
| Router | WiFi waves | Routers and access points |
| Switch | Network arrows | Network switches |
| Workstation | Monitor | Desktops and laptops |
| NAS | Database | Network-attached storage (Synology, QNAP) |
| Printer | Printer | Network printers |
| Unknown | Question mark | Unidentified devices |

---

## Connecting to Devices

After a port scan, LanLens shows connection buttons based on open ports:

| Button | Protocol | Port | Opens |
|--------|----------|------|-------|
| SSH | SSH | 22 | System SSH client (`ssh://ip`) |
| RDP | RDP | 3389 | Downloads `.rdp` file → Remote Desktop |
| HTTPS / HTTP | Web | 443 / 80 | Browser new tab |
| :8443 / :8080 | Web | 8443 / 8080 | Browser new tab |

If no port scan has been run, a **Scan Ports** button is shown instead.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Docker Container                                   │
│                                                     │
│  ┌─────────┐     ┌──────────────────────────────┐  │
│  │  nginx  │────▶│  FastAPI (uvicorn :8000)     │  │
│  │  :80    │     │                              │  │
│  └────┬────┘     │  Routers: auth, devices,    │  │
│       │          │  scan, settings, notifs,    │  │
│  ┌────▼────┐     │  connect                    │  │
│  │ React   │     │                              │  │
│  │ (dist/) │     │  Services: scanner, nmap,   │  │
│  └─────────┘     │  mac_vendor, telegram,      │  │
│                  │  scheduler (APScheduler)     │  │
│                  └──────────┬───────────────────┘  │
│                             │                       │
│                  ┌──────────▼──────────┐            │
│                  │  SQLite (/data/)    │            │
│                  └─────────────────────┘            │
│                                                     │
│  Host network (ARP scanning requires NET_RAW)       │
└─────────────────────────────────────────────────────┘
```

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12 + FastAPI |
| Database | SQLite (SQLAlchemy ORM) |
| Network scan | scapy (ARP) + python-nmap |
| MAC lookup | manuf (offline IEEE OUI database) |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Scheduler | APScheduler |
| Notifications | httpx → Telegram Bot API |
| Frontend | React 18 + TypeScript + Tailwind CSS |
| State management | Zustand |
| Build | Vite + Node 20 |
| Server | nginx + uvicorn |

---

## Development

### Backend

```bash
cd Network-docu
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

export SECRET_KEY=dev-secret-key
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
# Vite dev server on :5173, proxies /api to localhost:8000
```

---

## Security Notes

- **`SECRET_KEY`**: Must be set to a long random string. The app refuses to start with the default value.
- **`NET_RAW` capability**: Required for ARP scanning with scapy. Only grant this to trusted containers.
- **HTTPS**: LanLens itself serves HTTP. For HTTPS, place it behind a reverse proxy (Traefik, Caddy, nginx).
  ```yaml
  # Example: remove network_mode: host and use bridge + proxy
  ports:
    - "127.0.0.1:8080:80"
  ```
- **JWT tokens**: Stored in localStorage for persistence across page refreshes. Logout invalidates the session client-side.

---

## License

MIT License — see [LICENSE](LICENSE) for full text.

**Note:** This project depends on `scapy` and `python-nmap`, which are licensed under GPL-2.0. When redistributing this software, you must also comply with the GPL-2.0 terms for those dependencies.
