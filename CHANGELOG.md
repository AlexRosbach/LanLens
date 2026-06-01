# Changelog

All notable changes to this project should be documented in this file.

## v1.5.4 — Plugin discovery foundation

### New Features
- Added an optional plugin registry foundation for advanced LanLens modules.
- Added opt-in settings for plugin API visibility, passive discovery, mDNS analysis and SSDP/UPnP discovery.
- Added backend plugin status endpoints that report available plugin modules and enabled discovery protocols.
- Added passive multicast discovery storage for observed protocol metadata, including generic IPv4 multicast packets in addition to recognized OSPF/VRRP/HSRP control-plane traffic.
- Added visible passive-discovery capture and per-device mDNS/SSDP/multicast observations.
- Added passive-discovery device-class hints with confidence and reasons for common mDNS/SSDP/multicast advertisements.
- Added automatic passive-discovery device-class updates for linked observations when the inferred class is confident enough.
- Added a passive-discovery diagnostic capture that reports packets seen, parsed, stored, linked, device classes updated, duplicates skipped, active filter, enabled protocols and capture errors.
- Added passive-discovery device matching status and recent observation links in Settings so captured multicast packets can be traced directly to matching devices.
- Added clickable per-device multicast discovery rows with a detail dialog that shows parsed fields and the raw captured observation payload.
- Added direct device links for new-device notifications in the app UI and external notification payloads.
- Added mDNS, UPnP/SSDP and passive-discovery summaries to i-doit mapping sources and editable CSV exports.
- Added reachable device-detail SNMP switch-port topology mappings.
- Added SNMP switch, port and VLAN identity to device detail pages.
- Added a device-detail SNMP switch-port visualization for switches with interface plus MAC/VLAN table data, including active/inactive port state, hover endpoint context and click-through to learned devices.
- Expanded the default i-doit sync mapping so notes and descriptions write to the global description, operating-system text writes to the OS description, and serial numbers write to the model category.

### Fixes / Hardening
- Enforced feature switches in the backend as well as the UI, so disabled expert modules reject API access and background jobs instead of only disappearing from navigation.
- Bounded passive discovery service identifiers before persistence so long SSDP/UPnP locations cannot exceed database column limits.
- Fixed mDNS DNS-section parsing for Scapy packet-list sections so service names and service types are extracted correctly.
- Matched passive-discovery observations against current device IPs, MAC addresses and device IP history so captures still link when a device address has changed.
- Deduplicated repeated passive-discovery observations so recurring mDNS/UPnP/multicast packets update the latest seen time instead of flooding device detail lists and i-doit summaries.
- Tightened generic multicast deduplication so packets with the same source, multicast group and destination port update the latest seen time even when ephemeral source ports or MAC metadata vary between captures.
- Added Playwright coverage for the device multicast discovery table and detail dialog to prevent duplicate-looking multicast rows from returning.
- Added Playwright coverage for enabling CMDB/i-doit features so i-doit settings are not requested before the UI settings save has reached the backend.
- Added focused parser and capture-report coverage for mDNS packets, UPnP/SSDP M-SEARCH payloads, UPnP/SSDP response packets and generic IPv4 multicast packets.
- Fixed a Settings race where enabling CMDB/i-doit visibility could show “Failed to load i-doit settings” before the feature toggle was persisted.
- Moved build metadata into backend and frontend app constants, with Docker builds stamping the app files from build args instead of runtime environment variables.
- Bumped backend, frontend and image metadata to 1.5.4.

## v1.5.3 — Language persistence, TLS checks and ping history

### New Features
- Added lightweight reachability history samples for devices, captured during discovery and manual status checks.
- Added a compact ping-history view on device detail pages.
- Added per-service TLS certificate checks for HTTPS services, including status, expiration, issuer, SANs and errors.
- Added feature categories in Settings so new expert functions can stay opt-in unless promoted to the base experience.
- Exposed TLS certificate findings in i-doit/CMDB export and mapping data alongside the full LanLens inventory snapshot.

### Fixes / Hardening
- Hardened language persistence with a cookie fallback so the selected UI language survives refreshes even when browser local storage is unavailable.
- Gated TLS checks and ping history behind Feature settings.
- Bumped backend, frontend and image metadata to 1.5.3.

## v1.5.2 — Editable i-doit export, HTTPS, SNMP identity and build metadata

### New Features
- Added optional internal build metadata with build code, branch, commit and build time for Docker and frontend builds.
- Added a dedicated Settings → Features tab with switch-style controls for Advanced View, CMDB/i-doit visibility, optional navigation modules and build metadata.
- Added an editable i-doit CSV export preview in Settings → CMDB.
- Added backend endpoints for i-doit export preview and reviewed CSV download.
- Export rows include object type, title, network identifiers, hardware fields, inventory/CMDB IDs, location, responsible person, notes and LanLens ID.
- Added optional built-in HTTPS settings for host-network deployments, including certificate/key upload, nginx reload and optional HTTP-to-HTTPS redirect.
- Added an SNMP v1/v2c/v3 switch topology foundation with Cisco, Sophos, UniFi/Ubiquiti and generic SNMP vendor detection, profiles, switch polling, interface/MAC-table storage and i-doit export enrichment for switch, port and identity confidence.
- Added SNMP profile and switch-target deletion from Settings, including backend cleanup for assigned profile references and learned switch data.
- Added optional feature visibility settings that keep CMDB/i-doit, SNMP, Scan Nodes, Services, DHCP Monitor and detailed port-scan controls hidden from simpler home-network setups until explicitly enabled.

### Fixes / Hardening
- Added CSV export test coverage for excluding unchecked rows.
- SNMP poll failures now surface the backend error details in the Settings UI and keep the latest switch error visible in the SNMP table.
- SNMP polls now keep interface inventory when BRIDGE-MIB/Q-BRIDGE-MIB MAC tables are unavailable, which avoids generic poll failures on routers/firewalls that do not expose switch forwarding tables.
- Added SNMP parser and identity-resolution test coverage.
- Added certificate/key validation and restrictive private-key permissions for uploaded HTTPS material.
- Bumped backend, frontend and image metadata to 1.5.2.

## v1.5.0 — i-doit CMDB sync foundation

### New Features
- Added backend foundation for one-way LanLens → i-doit sync.
- Added configurable i-doit URL/API key settings, JSON-RPC path for Cloud/on-prem deployments, mapping JSON, sync status field, and auto-sync flag storage.
- Added i-doit connection test, local mapping validation, per-device dry-run preview, manual validation/state endpoint, and sync log API. Live i-doit writes remain intentionally disabled in this foundation slice.
- Added per-device i-doit sync state and audit log database tables.
- Added generic CMDB REST API foundation with authenticated inventory export, connector-neutral mapping/config endpoints, per-device dry-run/push endpoints, import preview, and audit logs for bidirectional CMDB workflows.
- Added generic webhook notifications for new devices, including Gotify-compatible JSON payloads and a test-send action in Settings → Notifications.
- Added Simplified Chinese UI language support.

### Documentation
- Added first setup notes for i-doit Cloud/on-prem JSON-RPC access, generic CMDB REST exchange, safe first-run workflow, mapping, status field selection, and troubleshooting.
- Hardened outbound integration URL handling: webhook/i-doit/CMDB URL validation now reports invalid ports cleanly, CMDB URLs are trimmed before storage, and docs clarify the SSRF guard boundaries. i-doit and generic CMDB REST requests now use the validated, pinned resolved address to avoid DNS rebinding between validation and connect.
- Changed DHCP Monitor probe execution from in-process Starlette background execution to a dedicated daemon thread after atomically reserving the capture slot, avoiding duplicate queued probes and blocking API workers during packet capture.
- Improved translation coverage for Device Detail documentation and danger-zone copy across English, German, Italian, and Simplified Chinese.

## v1.4.5 — Multi-subnet discovery

### New Features
- Added optional routed scan targets in Settings → Network Discovery. Additional IPv4 CIDRs/addresses are discovered with `nmap -sn`, enabling host discovery beyond the directly connected Layer-2 LAN.
- Added stable IP-only tracking for routed hosts where MAC/vendor data is unavailable. These devices are shown as IP-only discoveries instead of exposing synthetic identifiers in the UI.

### Documentation
- Documented local ARP discovery versus routed subnet discovery, including the expected MAC/vendor limitation for routed networks.
- Docker Hub images are published as `alexrosbach/lanlens:latest` and `alexrosbach/lanlens:1.4.5`.

## v1.4.4 — Network discovery stability improvements

### Bug Fixes
- Fixed false offline status changes caused by single missed ARP replies during scheduled discovery.
- Devices now remain online until they have been absent for a grace period derived from the configured scan interval, with a minimum of 15 minutes.

### New Features
- Added manual device status re-checks for offline devices from Device Detail.
- Added per-device IP history based on MAC address so previous addresses remain visible in Device Detail.
- Added optional Services navigation with a Services directory page for opening configured device services directly.
- Added Service segments so users can create/manage groupings, drag services into them, or use an explicit segment dropdown per service card for reliable mobile/touch assignment.
- Added custom service icon URLs; official brand logos are not bundled by default because individual logos may have brand/trademark restrictions despite Simple Icons being CC0 as a package.
- Split Settings into a tabbed sub-navigation for System, Database, Network Discovery and Notifications.
- Docker Hub images are published as `alexrosbach/lanlens:latest` and `alexrosbach/lanlens:1.4.4`.
- Dashboard device table now sorts by IP address by default.
- Added `Apple Workstation` as a device class and enabled custom device classes in registration/detail editing.
- Consolidated the dashboard `Unregistered` counter with `New` device semantics so both show the same user-visible state.

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
