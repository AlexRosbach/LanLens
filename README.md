<div align="center">

<img src="frontend/public/logo.svg" alt="LanLens Logo" width="80" height="80" />

# LanLens

**Self-hosted network monitoring and documentation dashboard**

[![Version](https://img.shields.io/badge/version-1.4.1-6366f1)](https://github.com/AlexRosbach/LanLens)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Docker Hub](https://img.shields.io/docker/pulls/alexrosbach/lanlens?color=0ea5e9)](https://hub.docker.com/r/alexrosbach/lanlens)

LanLens scans your local network, identifies devices by MAC/IP, and gives you a clean web UI to document, classify, and connect to them.

</div>

> [!IMPORTANT]
> ## 🎉 LanLens 1.4.1 is here, and this release is a big one
> The new version brings major improvements across deep scan, hypervisor visibility, translations, UI polish, and settings behavior.
>
> ### Please read before updating
> This release includes **database-related changes**. A backup before updating is **strongly recommended** and should be treated as mandatory for productive setups.
>
> **Recommended update flow:**
> 1. Create a full backup of your LanLens database before pulling the new image.
> 2. Only then update to `1.4.1`.
> 3. Verify login, devices, segments, credentials, and deep-scan settings after startup.
>
> If you are running SQLite, back up the `.db` file first. If you are running MariaDB/MySQL, create a dump before the update.


---

## Features


- Automatic LAN discovery via ARP scan
- Device classification and offline MAC vendor lookup
- DHCP badge detection
- Segments with colour, range, and IP usage
- Per-device documentation fields
- Service inventory per device
- One-click connect actions (SSH, RDP, HTTP, HTTPS)
- Port scanning via nmap
- **Deep scan** via SSH (Linux) and WinRM (Windows) — hardware, OS, services, containers, hypervisor inventory
- **Encrypted credential vault** for SSH and WinRM access (Fernet, key derived from `SECRET_KEY`)
- **Hypervisor intelligence** — detects Proxmox, KVM, and Hyper-V hosts; enumerates guests; maps VMs to known devices
- **Auto deep scan** — per-device scheduled scanning with configurable interval
- Telegram notifications for new devices and updates
- English, German, and Italian UI
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
- **Scan range**: used for the active ARP network scan
- **Scan interval**: controls the schedule

Notes:
- LanLens auto-detects the host subnet as the default scan range when no explicit scan range was saved yet.
- The configured `scan start` and `scan end` define the actual IPv4 scan range, so larger ranges inside the directly reachable local network are supported.
- ARP scanning works directly only on the locally reachable Layer-2 network. A routed remote subnet is not automatically reachable just by entering another IP range.

### Telegram

Configure Telegram in **Settings → Notifications**:
- bot token
- chat ID
- optional test message

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
    image: ghcr.io/alexrosbach/lanlens:latest
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

- Docker images are published at [`alexrosbach/lanlens`](https://hub.docker.com/r/alexrosbach/lanlens)
- GitHub releases should be maintained for release-based update checks and Telegram update notifications
- Detailed project history lives in [CHANGELOG.md](CHANGELOG.md)

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
