# Changelog

All notable changes to this project should be documented in this file.

## Unreleased

### New Features
- Fresh installs now detect the primary host IPv4 subnet, persist it as the initial ARP scan range and start an immediate first-run network scan so the dashboard can populate without opening Settings first.
- Added custom SNMP OID/table polling for V 1.5.8: operators can define arbitrary OIDs, scope them to target tags/device classes such as switch, printer, UPS or `*`, store the latest values per SNMP target and run them during the existing SNMP poll cadence.
- Added Settings UI and API endpoints for custom SNMP queries and latest custom SNMP results so heterogeneous SNMP devices can expose useful data without hardcoding every vendor-specific MIB into LanLens.
- Added an opt-in **Network Topology** view under **Settings -> Features** that visualizes known device relationships, SNMP switch-port mappings and passive topology edges without changing the default LanLens navigation.
- Grouped the main sidebar into **Monitor**, **Analyze**, **Manage** and **Admin** sections so optional expert views such as Network Topology have a clearer home.
- Made the Network Topology map roomier and interactive with drag-to-pan, mouse-wheel zoom and inline zoom/reset controls, including multi-row device placement so dense device groups no longer stack on top of each other.

### Fixes / Hardening
- Ignored common Linux bridge interfaces such as `br0` and `bridge0` during first-run subnet detection so Docker hosts prefer the real LAN interface.
- Limited the Settings SNMP custom-result request to the visible result count and kept SNMP vendor detection coverage in the dedicated vendor test.
- Reused existing inventory topology, SNMP endpoint and network-change data for the topology visualization; no new packages or license obligations were added.

## v1.5.7 — i-doit matching, notifications and passive topology

### New Features
- Added a per-device i-doit SYSID lookup button that tests whether the configured SYSID resolves to a visible i-doit object before running a sync.
- Added an opt-in Settings Debug tab behind **Settings -> Features -> Debug tools** with topic, text and level filters for persistent CMDB/i-doit troubleshooting logs.
- Added granular network-change notification type switches for IP address changes, hostname changes, online/offline transitions, archive state changes, MAC drift warnings and unknown DHCP servers.
- Added STP/RSTP passive discovery parsing so bridge/root-bridge topology advertisements are stored, shown in multicast observations and can classify linked devices as switches.
- Expanded OSPF passive discovery metadata for hello packets, including router ID, area, DR/BDR and neighbor router IDs.
- Enriched the inventory topology API with passive control-plane edges for known OSPF neighbors, HA virtual IP peers and known LLDP/CDP/STP bridge relationships when both endpoints already exist as LanLens devices.

### Fixes / Hardening
- Expanded i-doit match-only diagnostics so skipped sync logs keep direct SYSID lookup attempts, candidate rejections and fallback page counts even when large payload details are truncated.
- Paginated the i-doit `match_only` fallback scan so manually entered SYSID values can match objects beyond the first i-doit object page.
- Advanced i-doit fallback pagination by the returned page size so tenants with smaller server-side page caps do not skip objects during SYSID matching.
- Allowed clearing device text fields such as Label, Asset Tag, CMDB ID and documentation notes from the device detail form instead of silently keeping the previous values.
- Extended `match_only` i-doit matching with a bounded category-verified object scan for MAC/IP/hostname/CMDB identity when direct i-doit object search does not return category-field matches.
- Matched manual i-doit SYSID values even when the tenant stores them in Accounting/Inventory fields together with CMDB IDs, added a bounded verified object-list fallback for tenants that do not support direct SYSID filters, and added identity-match diagnostics to skipped sync logs.
- Made the large CMDB/i-doit field mapping editor collapsible so Settings stays usable while still keeping advanced mapping controls available.
- Matched existing i-doit objects during `match_only` sync by stable LanLens identity fields such as CMDB ID, MAC address, IP address, hostname and object title instead of requiring a previously stored i-doit object ID.
- Changed the default i-doit sync mapping for open ports, services, TLS certificates and container/software findings to structured i-doit category entries instead of dumping those values into category description fields.
- Extended notification-rule channel controls to every granular network-change type, not just the two top-level notification rows.
- Reworked the notification rules UI for mobile viewports so notification settings are stacked and no longer clipped by the desktop matrix layout.
- Routed manual and retention-driven archive events through the granular archive notification subtype so archive rules suppress and deliver consistently.
- Reused the existing Scapy passive-discovery dependency for STP/RSTP and OSPF parsing; no new packages or license obligations were added.

## v1.5.6 — Network security awareness

### New Features
- Added an authorized DHCP server allowlist with API and UI management for expected server IP/MAC identities.
- Marked DHCP observations as authorized or unknown so unexpected DHCP servers stand out immediately in the DHCP Monitor.
- Added network-change notifications for unknown DHCP server observations.
- Added ARP/MAC drift detection for local scans and scan-node ingests when a known IP appears with a different real MAC address.
- Added passive VRRP/HSRP group awareness that summarizes recent high-availability peers from multicast discovery.
- Added visible multicast capture cadence controls in **Settings -> Network Discovery -> Multicast protocols** and reused the configured capture duration for manual captures.
- Added client-side UI error logging so visible browser/API/runtime failures are also written to the LanLens container logs.
- Added configurable background port-scan scheduling in **Settings -> Network Discovery**, including enablement, interval and the existing port range/list.
- Added inline editing for existing SNMP switch topology targets in **Settings -> Network Discovery**.
- Added configurable background SNMP switch polling in **Settings -> Network Discovery**, including enablement and interval.
- Added detailed SNMP poll troubleshooting output with attempted OIDs, per-step result counts and sanitized target/profile context.
- Added an SNMP diagnostics details dialog so successful polls and failed polls can show full troubleshooting steps without filling the target table.
- Added SNMP real-port statistics for device detail and switch-port hover context, including speed, cast packet counters, discards, CRC/FCS errors, collisions and fragment counters where the target exposes IF-MIB/EtherLike-MIB data.
- Generalized SNMP vendor and class detection for common SNMP network devices beyond Cisco, including Juniper, MikroTik, Fortinet, Aruba/HPE, Netgear, TP-Link, D-Link, Zyxel, pfSense, OPNsense, Sophos, UniFi/Ubiquiti and Cisco Meraki identities.
- Expanded SNMP real-port detection for common interface names such as Ethernet, ge/xe/et, ether, port, SFP/QSFP, WLAN/radio, WAN/LAN, PPP and serial interfaces.
- Filtered common virtual SNMP interfaces such as loopback, VLAN/SVI, tunnel, bridge, management, stack, LAG/bond/team and port-channel rows from the switch-port visualization so it focuses on real ports.
- Relaxed SNMP polling so routers, firewalls, printers and other non-switch SNMP targets can be scanned for identity/interface data even when IF-MIB details or bridge MAC tables are unavailable.
- Linked SNMP targets now appear on matching device detail pages and CMDB export fields even when the target has no switch MAC table, using explicit device assignment or host/IP matching.
- Added SNMP interface-only port visualization for linked switches when IF-MIB is available but BRIDGE-MIB/Q-BRIDGE-MIB MAC tables are not.
- Added LLDP/CDP passive discovery parsing so linked devices can be classified from advertised switch, router, access-point, telephone and station capabilities.
- Added a bulk delete action on the Notifications page to clear all in-app notifications after confirmation.
- Added a general notification rule matrix in **Settings -> Notifications** with global event rules and per-channel Telegram, webhook/Gotify and email rules for new-device and network-change events.

### Fixes / Hardening
- Made first-run Docker setup one-command friendly by generating and persisting `SECRET_KEY` in the data volume when it is not supplied.
- Mapped additional LanLens service, open-port, TLS certificate and container/software summaries to i-doit standard category description fields by default where i-doit exposes reliable text targets.
- Deduplicated repeated DHCP unknown-server and MAC-drift security notifications to avoid noisy repeat alerts.
- Enforced global notification rules as master switches for channel delivery so queued events stay silent when the global event is disabled.
- Made unknown-DHCP-server notifications honor the global network-change notification rule.
- Validated authorized DHCP server IP and MAC entries on create/update to reject typoed allowlist identities.
- Added best-effort per-IP throttling to unauthenticated client-error logging to reduce container log spam.
- Made client-error throttling use the nginx-forwarded browser IP when available so one noisy proxied client does not silence error logs for everyone.
- Hardened client-error logging to redact bearer authorization headers, protect the shared rate-limit state from concurrent requests and prune stale client buckets.
- Deduplicated passive DHCP server replies during fallback capture so repeated offer/ack packets do not inflate DHCP Monitor counters.
- Limited notification delivery lookups to event rules for channels that are actually configured, avoiding repeated reprocessing of unsendable queued notifications.
- Prevented MAC-drift notifications for routed scan-node/IP-only device identifiers.
- Kept the Notifications bulk-delete UI unchanged when the backend delete request fails.
- Replaced the SNMP target edit row's raw enabled checkbox with a compact inline toggle that fits the Settings table action layout.
- Avoided duplicated MAC addresses in SNMP switch-port hover details when a learned endpoint has no matched device label.
- Treated missing BRIDGE-MIB/Q-BRIDGE-MIB MAC tables as optional SNMP diagnostics instead of marking otherwise successful interface polls as latest errors.
- Classified unknown IP-scan-discovered switch, router, firewall and AP devices from linked SNMP target identity and interface inventory.
- Reused the existing DHCP Monitor, passive discovery and network-change infrastructure; no new packages or license obligations were added.
- Bumped backend, frontend and image metadata to 1.5.6.

## v1.5.5 — Network change log

### New Features
- Added a global Network Changes view that shows recent device and infrastructure changes across the inventory.
- Added filters for change type, time range and search so changes can be narrowed by device, field, source or event type.
- Added an authenticated `/api/inventory/changes` endpoint with device labels, IPs, MAC addresses and classes for each change event.
- Added a filtered audit export for Network Changes so the visible change history can be downloaded as CSV or JSON for compliance review.
- Added before/after columns to Network Changes so field-level diffs are visible without opening device detail.
- Added opt-in network change notifications that reuse the existing in-app, Telegram and webhook delivery flow.
- Linked change rows directly to the affected device detail page while preserving the existing per-device timeline.

### Fixes / Hardening
- Cached the opt-in network-change notification setting per scanner database session so scans do not repeat the same settings lookup for every recorded change.
- Escaped dynamic Telegram HTML for network-change notifications, including device labels, change messages and device links.
- Made passive device type assignment more conservative so generic IPP/mDNS printer sharing from Macs or workstations does not classify the device as a printer.
- Tightened device type assignment across all classes: generic RTSP, SMB, SSH, AirPlay, MQTT and broad hostname fragments now stay as weak hints instead of automatically assigning Camera, NAS, TV, IoT or other classes.
- Reorganized Settings with clearer categories: Network Discovery now keeps scan ranges, manual multicast diagnostics, scan nodes, SNMP topology and port-scan configuration; Automation now contains recurring scan, ping and passive-discovery background jobs; device retention moved into the new **Lifecycle** category.
- Reused the existing `device_change_events` table and current frontend/backend dependencies; no new packages or license obligations were added.
- Bumped backend, frontend and image metadata to 1.5.5.

## v1.5.4 — Plugin discovery foundation

### New Features
- Added an optional plugin registry foundation for advanced LanLens modules.
- Added opt-in settings for plugin API visibility, passive discovery, mDNS analysis and SSDP/UPnP discovery.
- Added backend plugin status endpoints that report available plugin modules and enabled discovery protocols.
- Added passive multicast discovery storage for observed protocol metadata, including generic IPv4 multicast packets in addition to recognized OSPF/VRRP/HSRP control-plane traffic.
- Added visible passive-discovery capture and per-device mDNS/SSDP/multicast observations.
- Added passive-discovery device-class hints with confidence and reasons for common mDNS/SSDP/multicast advertisements.
- Added automatic passive-discovery device-class updates for linked observations when the inferred class is confident enough.
- Added automatic mDNS hostname fill-in for linked devices when normal discovery did not produce a usable hostname.
- Added device retention settings to automatically archive inactive discovered devices and optionally delete archived devices after a separate retention period.
- Added a manual device archive action in the device detail danger zone so individual discoveries can be moved to the archived view immediately.
- Added a passive-discovery diagnostic capture that reports packets seen, parsed, stored, linked, device classes updated, hostnames updated, duplicates skipped, active filter, enabled protocols and capture errors.
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
- Constrained automatic device retention archive and purge steps to unregistered discovered devices so registered inventory documentation is never purged by retention.
- Aligned frontend plugin feature gates with backend dependencies so passive discovery cannot render without Plugin API enabled.
- Included device IP history in per-device passive discovery lookups so observations remain visible after an address change.
- Avoided per-device SNMP identity lookups on dashboard lists by using the existing bulk identity resolver.
- Excluded archived devices from the background ping monitor so archived discoveries stay out of active reachability updates.
- Updated async ping helpers to use the running event loop explicitly for modern asyncio runtimes.
- Bounded passive discovery service identifiers before persistence so long SSDP/UPnP locations cannot exceed database column limits.
- Fixed mDNS DNS-section parsing for Scapy packet-list sections so service names and service types are extracted correctly.
- Matched passive-discovery observations against current device IPs, MAC addresses and device IP history so captures still link when a device address has changed.
- Deduplicated repeated passive-discovery observations so recurring mDNS/UPnP/multicast packets update the latest seen time instead of flooding device detail lists and i-doit summaries.
- Tightened mDNS deduplication so repeated packets for the same source and advertised service or `.local` host do not appear as duplicate-looking multicast rows when question/answer summaries vary.
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
