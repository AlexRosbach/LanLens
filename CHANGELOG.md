# Changelog

All notable changes to this project should be documented in this file.

## v1.4.4 — Network discovery stability improvements

### Bug Fixes
- Fixed false offline status changes caused by single missed ARP replies during scheduled discovery.
- Devices now remain online until they have been absent for a grace period derived from the configured scan interval, with a minimum of 15 minutes.

## v1.4.3 — Windows deep scan readability and audit cleanup

### Improvements
- Improved Windows deep scan rendering so services, hardware details and audit results are shown in readable summaries/tables instead of raw CIM/PowerShell dumps.
- Fixed Windows running-services summaries so JSON results are counted and previewed correctly.
- Filtered WinRM CLIXML/progress noise from saved findings to avoid useless SQL/audit output.

## v1.4.2 — Device delete fix and stability improvements

### Bug Fixes
- Fixed device deletion from Device Detail. Devices with related VM host/guest relationships can now be removed cleanly together with their dependent records instead of failing during delete.

## v1.4.1 — Deep Scan improvements, OS-specific device classes, VM-host linking, CMDB, MariaDB & more

### Bug Fixes
- **Fixed `TypeError: 'str' - int` in device list** — memory-total extraction inside the hardware summary batch query was shadowing the `total` device-count variable, causing the `/api/devices` endpoint to crash and the dashboard to show no devices.
- **Fixed Proxmox hypervisor scan returning only the first VM** — the previous approach launched one `qm config <VMID>` subprocess per VM via SSH. With more than a handful of VMs the 20-second `exec_command` timeout was exceeded and only partial output was received. The scan now reads config files directly from `/etc/pve/qemu-server/*.conf` and `/etc/pve/lxc/*.conf` (same format, no subprocess overhead). Snapshot sections (`[snap-name]`) are skipped to avoid duplicate MAC/name entries.
- Fixed Proxmox LXC container name parsing (`pct list` with empty Lock column).
- Fixed **last scan time** in Deep Scan panel: UTC timestamps from the backend are now correctly interpreted (appends `'Z'` suffix before parsing).
- Fixed timestamp rendering in Host/Guest panel (same UTC fix).

### New Features
- **CMDB IDs** — auto-generated unique identifier per device (format configurable, e.g. `DEV-0001`). Generated on first registration; regeneratable via Device Detail. Prefix and digit count adjustable in Settings → System → CMDB IDs.
- **MariaDB / external database support** — set `DATABASE_URL` environment variable to use an external MariaDB (or any SQLAlchemy-compatible DB) instead of the built-in SQLite file. All migrations are now dialect-aware (`sqlalchemy.inspect()` instead of SQLite-only PRAGMAs). See README for docker-compose example.
- **Export & Import** — Settings → System: export all settings as JSON, download the SQLite database file, or import settings from a previously exported JSON.
- **SSH Private Key authentication** — credentials now support `auth_method: password` (default) or `auth_method: key`. When using key auth, the PEM private key (RSA, Ed25519, ECDSA, DSS) is stored encrypted and used for SSH connections. The Credential Modal shows an auth-method selector and a textarea for pasting the key.
- **SMTP email notifications** — configure an SMTP server in Settings → Notifications to receive email alerts. Includes a test-send button.
- **Credential type separation in Auto-Scan Rules** — `linux_ssh` credentials can only be assigned to Linux-class device classes; `windows_winrm` credentials can only be assigned to Windows-class device classes. The rule modal filters available credentials and device classes accordingly.
- **Hardware summary in device list** — shows CPU model + RAM total (e.g. `Intel Core i3-7100U · 16 GB RAM`) derived from deep-scan findings beneath the device MAC address.
- **VM / hypervisor indicator in device list** — VM-class devices show their linked hypervisor host name directly in the dashboard table.
- **Port scan buttons removed from dashboard** — Connect buttons in the device table now hide scan/rescan and single-port fields; those remain available only in the Device Detail view.

### Settings Reorganisation
- Settings page split into sections: **System** (app info, export/import, CMDB), **Database** (connection info, MariaDB guide), **Network Discovery**, **Notifications** (Telegram + SMTP).
- Deep Scan credentials moved entirely out of main Settings into the **Deep Scan Settings** page.

### Deep Scan Improvements
- Added OS-specific device classes: `Linux Server`, `Windows Server`, `Linux VM`, `Windows VM`, `Linux Workstation`, `Windows Workstation` — coloured dot indicator (green = Linux, blue = Windows).
- Added Auto-Scan Rules with OS-based credential/class filtering.
- Improved findings display: compact mode shows one-line summary per key; full view collapsible per block.
- Added VM host assignment card in Device Detail for VM-class devices.
- Added manual host/guest relationship endpoints (`POST`/`DELETE`).
- Added suggestion panel in Host/Guest tab (apply detected VM name as device label).
- Added delete button per relationship row in Host/Guest tab.

### Documentation
- Added README section: **Using MariaDB / External Database** with docker-compose example, connection string table, and backup notes.
- Added README section: required Linux / Windows user permissions for deep scan.

### Database Schema
- Added `auto_scan_rules` table.
- Added `credentials.auth_method` column (`password` / `key`), default `password`.
- Added `devices.cmdb_id` column (VARCHAR 64, unique).
- All migrations are idempotent and run automatically on container start.

## v1.4.0 — Deep Scan

- Added encrypted credential vault (Fernet, key derived from `SECRET_KEY`) for storing SSH and WinRM credentials. Secrets are never returned in plaintext via the API.
- Added deep scan feature: per-device SSH (Linux) and WinRM (Windows) scans with configurable profiles: `hardware_only`, `os_services`, `linux_container_host`, `windows_audit`, `hypervisor_inventory`, `full`.
- Added structured finding storage per scan run: hardware, OS, services, containers, hypervisor, VM guest, and audit findings.
- Added hypervisor intelligence: detects Proxmox, KVM/libvirt, and Hyper-V hosts; enumerates guests; maps VMs to known LanLens devices by MAC address first, then IP address.
- Added VM-to-host relationship tracking with periodic reconciliation.
- Added auto deep scan policies: per-device scheduled deep scans with configurable interval (minimum 5 minutes), polled every 60 seconds.
- Added credential manager in Settings with masked display, per-type badge, and live connection test.
- Added Deep Scan panel in Device Detail with tabbed findings view (Hardware, OS, Services, Containers, Audit, Host/Guest).
- Added `paramiko` (SSH) and `pywinrm` (WinRM) as new backend dependencies.
- Database schema bumped to v1.4.0 — five new tables: `credentials`, `device_deep_scan_config`, `deep_scan_runs`, `deep_scan_findings`, `device_host_relationships`. Migration is idempotent and runs automatically on container start.
- Added global configurable port scan range in Settings (supports `top:N`, `1-65535`, `22,80,443`, `1-1024,8080,8443`). Default remains `top:1000`.
- Added single-port scan in Device Detail — scan one specific port number and merge result into the existing port scan record without overwriting other findings.

## v1.3.1 — Separate scan range from DHCP tagging

- Added dedicated `scan_start` and `scan_end` settings so scan targeting is no longer coupled to the DHCP range.
- Restored DHCP settings to their intended role for DHCP tagging only.
- Settings UI now exposes separate sections for DHCP tagging and ARP scan range.
- Clarified in the UI and docs that ARP scanning works directly only on the locally reachable Layer-2 network, not automatically across routed subnets.
- Keeps auto-detected host subnet defaults for the scan range when no explicit scan range is saved.

## v1.3.0 — Flexible scan ranges and smarter subnet defaults

- Added automatic host network detection via `netifaces` so LanLens no longer defaults to `192.168.1.0/24` when deployed on a different subnet.
- The configured `dhcp_start` and `dhcp_end` values now define the real IPv4 scan range instead of forcing a `/24` derived only from `dhcp_start`.
- Added support for extended scan ranges by summarizing the configured start/end range into one or more scan targets.
- Settings now show the detected host subnet range by default when no explicit scan range has been saved yet.
- Added validation so `dhcp_start` cannot be greater than `dhcp_end`.
- Improved logging to show whether the active scan range came from configuration, host auto-detection, or fallback defaults.
- Fixes #17 and addresses the requested flexibility from #5 and #6.

## v1.2.6 — Configurable host-mode port and release docs

- Added configurable `LANLENS_PORT` support so LanLens can listen on a custom HTTP port even when running in `network_mode: host`.
- Added `BACKEND_PORT` environment override for the internal nginx → FastAPI hop.
- Updated entrypoint startup output to show the configured host-mode URL instead of assuming port 7765.
- Updated Docker Compose and image healthchecks to use the configured external port.
- Clarified README release documentation so GitHub Releases are explicitly documented as required for release-based update checks and Telegram update notifications.

## v1.2.5 — Update detection & notification hardening

- Added backend `/api/settings/update/check` endpoint so update detection no longer depends only on a direct frontend GitHub call.
- Frontend update hook now consumes backend update-check results instead of hitting GitHub directly.
- Update notification endpoint now skips cleanly when no newer release exists.
- Existing server-side dedupe for already-notified versions remains in place.

## v1.2.4 — Server-side sessions & NEW badge state

- Removed browser `localStorage` / `sessionStorage` persistence from the LanLens app flow.
- Switched authentication to HTTP-only cookie-based session handling instead of browser-stored bearer tokens.
- Added server-side per-user device view tracking via `device_views`.
- NEW badge state is now computed on the backend and stays consistent across direct access and reverse-proxy access.
- Added `/api/devices/{id}/mark-viewed` for server-side viewed-state updates.
- Hardened migration logic so the `device_views` unique index is created even when the table already exists.

## v1.2.3 — Reverse-proxy path fix

- Fixed frontend base-path handling for reverse-proxy / subpath deployments.
- BrowserRouter now respects the deployed Vite base path instead of assuming `/`.
- Login redirect on 401 now resolves through the frontend base path.
- Logo asset paths and RDP download URLs now work correctly behind proxied subpaths.
- Added `frontend/src/vite-env.d.ts` so `import.meta.env.BASE_URL` builds cleanly in TypeScript.

## v1.2.2 — Bug fix: TopBar new-device counter

- Fixed the TopBar new-device counter to stay consistent with the Dashboard logic.

## v1.2.1 — Bug fixes & segment enhancements

- Fixed unregistered counter behavior for viewed devices.
- Improved segment filtering and IP usage display.

## v1.2.0 — Server URL, Telegram update notifications, sortable table & more device classes

- Added server URL setting for reverse-proxy deployments.
- Added Telegram update notifications.
- Added sortable device table and more device classes.
