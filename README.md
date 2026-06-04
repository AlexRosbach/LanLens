<div align="center">

<img src="frontend/public/logo.svg" alt="LanLens Logo" width="80" height="80" />

# LanLens

**Self-hosted network inventory, local network scanner, and documentation dashboard**

[![Version](https://img.shields.io/badge/version-1.5.6-6366f1)](https://github.com/AlexRosbach/LanLens)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Docker Hub](https://img.shields.io/docker/pulls/alexrosbach/lanlens?color=0ea5e9)](https://hub.docker.com/r/alexrosbach/lanlens)
[![Follow on X](https://img.shields.io/badge/X-@itneedtoknow-000000)](https://x.com/itneedtoknow)

LanLens turns a Docker host into a local network scanner that discovers MAC/IP devices, builds a device inventory, and gives home lab or small IT operators a clean web UI for documentation, security awareness, and CMDB/i-doit export workflows.

[Documentation](docs/documentation.md) · [Knowledge Base](docs/knowledgebase.md) · [Changelog](CHANGELOG.md) · [Docker Hub](https://hub.docker.com/r/alexrosbach/lanlens)

</div>

---

## What You Get

After the first scan, LanLens shows which devices are on your network, where they sit in your inventory, which services are reachable, and which changes deserve attention. It is built for self-hosted network inventory, home lab network monitoring, lightweight asset documentation, and quick troubleshooting without rolling out a full enterprise discovery suite.

In the first two minutes you can usually see:

- A device inventory with MAC/IP device discovery, vendor hints, online/offline state, DHCP range membership, and connection shortcuts
- Device detail pages for labels, owner/team, location, purpose, OS/version, asset tag, notes, CMDB ID, IP history, services, ports, and timeline
- Segments that keep routers, switches, servers, IoT, cameras, and client devices readable
- Network awareness signals for unknown DHCP servers, ARP/MAC drift, VRRP/HSRP peers, and scan-detected changes
- Optional SNMP target polling for common IF-MIB network devices, switch-port visibility, interface statistics, diagnostics, and device-class enrichment
- Optional mDNS, SSDP/UPnP, LLDP/CDP, and multicast observations that can improve hostnames and device classes
- Reviewed CMDB/i-doit CSV export plus integration foundations for inventory sync workflows

Why it is useful:

- **Fast local visibility:** run a Docker network scanner on a host in the LAN and get a practical device list quickly.
- **Documentation without friction:** turn discovered devices into a maintained inventory instead of a spreadsheet that drifts.
- **Security awareness for small networks:** surface suspicious DHCP, identity, and topology changes without sending the inventory to a cloud service.
- **Operator-friendly exports:** prepare device inventory and CMDB/i-doit export data before it leaves LanLens.
- **Optional expert modules:** enable Services, DHCP Monitor, SNMP, passive discovery, CMDB/i-doit, TLS checks, and other advanced views only when needed.

Trust and privacy notes:

- LanLens runs self-hosted and stores its inventory in your configured database volume.
- No cloud account is required to use the product.
- There is no product telemetry pipeline in the application. Optional outbound traffic happens only for features you configure or trigger, such as update checks, Telegram/email/webhook notifications, CMDB/i-doit connections, or external database/integration targets.
- Secrets such as notification tokens, SNMP credentials, and integration credentials are masked in API responses; protect the database volume and backups because configured credentials live there.

> [!IMPORTANT]
> Use LanLens only in networks you own or where you have explicit permission to scan and monitor devices. Network discovery and port scanning can be misused against third-party systems.

---

## Product Screenshots

The screenshots below use sanitized demo data with documentation IP ranges and example names.

| Dashboard | Device detail |
|---|---|
| ![LanLens dashboard](docs/screenshots/lanlens-dashboard.png) | ![LanLens device detail](docs/screenshots/lanlens-device-detail.png) |

| Segments | DHCP security awareness |
|---|---|
| ![LanLens segments](docs/screenshots/lanlens-segments.png) | ![LanLens DHCP security awareness monitor](docs/screenshots/lanlens-v1.5.6-dhcp-security.png) |

| LLDP/CDP class hints | SNMP targets |
|---|---|
| ![LanLens passive LLDP device class hint](docs/screenshots/lanlens-passive-lldp-classification.png) | ![LanLens SNMP target settings and learned network device inventory](docs/screenshots/lanlens-snmp-targets-settings.png) |

| SNMP poll diagnostics | Device linked to SNMP identity |
|---|---|
| ![LanLens SNMP poll diagnostics without exposing credentials](docs/screenshots/lanlens-snmp-poll-diagnostics.png) | ![LanLens device detail linked to SNMP target identity](docs/screenshots/lanlens-device-snmp-target-link.png) |

| CMDB / i-doit settings | Reviewed i-doit CSV export |
|---|---|
| ![LanLens CMDB and i-doit settings](docs/screenshots/lanlens-idoit-settings.png) | ![LanLens editable i-doit CSV export](docs/screenshots/lanlens-idoit-export.png) |

---

## Quick Start

### Requirements

- Docker 20.10+
- Docker Compose v2
- Linux host recommended for direct ARP scanning

### 1. Download the compose file

```bash
curl -O https://raw.githubusercontent.com/AlexRosbach/LanLens/main/docker-compose.yml
```

### 2. Generate a secret key

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Replace `CHANGE_THIS_TO_A_LONG_RANDOM_STRING` in `docker-compose.yml` with the generated value, then start LanLens:

```bash
docker compose up -d
```

Open:

```text
http://<your-host-ip>:7765
```

Default first-run credentials:

```text
admin / admin
```

LanLens forces a password change after the first login. For full MAC/vendor discovery, run it on a Linux host with host networking as shown in the compose file.

---

## Deployment Notes

LanLens uses `network_mode: host` by default because local ARP discovery needs raw network access on the host interface. Bridge mode can serve the UI, but direct ARP/MAC discovery will not work the same way.

Core runtime settings:

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | required | Encryption/signing key; set a strong random value |
| `DEFAULT_ADMIN_PASSWORD` | `admin` | Initial admin password when no user exists |
| `LANLENS_PORT` | `7765` | HTTP port exposed by nginx |
| `BACKEND_PORT` | `17765` | Internal FastAPI port behind nginx |
| `DB_PATH` | `/data/lanlens.db` | SQLite database path |
| `TZ` | `UTC` | Container timezone |

For HTTPS, external databases, Scan Nodes, deep scan permissions, CMDB/i-doit, SNMP, backups, and troubleshooting, use the [technical documentation](docs/documentation.md).

---

## Documentation Map

- [Technical documentation](docs/documentation.md): architecture, deployment, configuration, API, scanning behavior, deep scan, CMDB/i-doit, SNMP, external databases, and development notes
- [Knowledge Base / FAQ](docs/knowledgebase.md): common setup errors, scanning behavior, i-doit/CMDB troubleshooting, and Scan Node notes
- [Changelog](CHANGELOG.md): release history and migration notes
- [Security Policy](SECURITY.md): vulnerability reporting and supported versions

---

## Docker Images

Docker images are published at [`alexrosbach/lanlens`](https://hub.docker.com/r/alexrosbach/lanlens). Use the compose file in this repository for the expected host-network deployment model and required environment variables.

Project updates and occasional build notes are posted on [X / @itneedtoknow](https://x.com/itneedtoknow).

---

## Support

LanLens is free and open source. If it helps you or saves you time, you can support ongoing development voluntarily. Support does not buy support priority, features, or access.

<a href="https://www.buymeacoffee.com/alexrosbaci" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-blue.png" alt="Buy Me a Coffee" style="height: 36px !important;width: 130px !important;" ></a>

---

## Development

Backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

export SECRET_KEY=dev-secret-key-at-least-32-chars-long
export DB_PATH=./data/lanlens.db
mkdir -p data

python backend/cli/init_db.py
python backend/cli/init_admin.py
uvicorn backend.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

---

## License

MIT License, see [LICENSE](LICENSE).

Dependency note: LanLens uses GPL/LGPL and dual-licensed libraries for network discovery and remote connectivity features. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing bundled builds or Docker images.
