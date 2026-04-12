# Changelog

All notable changes to this project should be documented in this file.

## v1.4.1 — Deep Scan improvements, OS-specific device classes & VM-host linking

- Fixed Proxmox VM/CT detection: deep scanner now fetches individual VM configs via `qm config <VMID>` and `pct config <CTID>` to extract MAC addresses, enabling reliable VM-to-device matching.
- Fixed Proxmox LXC container name parsing (`pct list` with empty Lock column).
- Added de-duplication of hypervisor guest list so `qm_config` (with MAC) takes precedence over `qm_list` (name only).
- Added **OS-specific device classes**: `Linux Server`, `Windows Server`, `Linux VM`, `Windows VM`, `Linux Workstation`, `Windows Workstation` — displayed with coloured dot indicator (green = Linux, blue = Windows) so auto-scan rules can target OS types precisely.
- Added **Auto-Scan Rules** page (new nav item "Deep Scan"): define global rules to auto-scan all devices of a given class with a specific credential and profile on a configurable interval.
- Added **Deep Scan Settings** as a dedicated navigation page with: Credential Vault, Scan Profile descriptions, and Auto-Scan Rules management.
- Improved **Deep Scan findings display**: compact mode by default showing only essential info (OS name, CPU model, disk summary, container count); "Show full details" toggle expands to full structured view. Key-value blocks (lscpu, os-release) rendered as grids; column-aligned tables (lsblk, virsh list) rendered as HTML tables; long outputs collapsible.
- Fixed **last scan time** in Deep Scan panel: UTC timestamps from the backend are now correctly interpreted (appends 'Z' suffix before parsing), matching the fix already applied to the dashboard.
- Added **hardware model summary** in device list: shows the scanned hardware model below the MAC address for devices where a deep scan has been performed.
- Added **VM host assignment**: Device Detail for VM-class devices shows a "Runs on Host" card with the linked hypervisor. Users can manually link or unlink a host from a dropdown of server/hypervisor-class devices.
- Added **manual host/guest relationship endpoints**: `POST` and `DELETE /api/devices/{id}/deep-scan/relationships` allow creating and removing VM-to-host links via the UI or API.
- Added **suggestion panel** in Host/Guest tab: when a VM guest has no label but a VM name was detected by the hypervisor scan, a suggestion to apply the VM name as the device label is shown with a one-click "Apply" button.
- Added delete button per host/guest relationship entry in the Host/Guest tab.
- Fixed timestamp rendering in Host/Guest panel (same UTC fix as above).
- Added **README section** documenting required Linux and Windows user permissions for deep scan.
- Database schema bumped to v1.4.1 — added `auto_scan_rules` table. Migration is idempotent and runs automatically on container start.

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
