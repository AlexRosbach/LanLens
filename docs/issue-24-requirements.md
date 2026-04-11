# Issue #24 — Deep Scan: Anforderungen (Zusammenfassung)

Datum: 2026-04-11
Autor: Isaac (implementation summary)

Kurz: Sammlung aller Anforderungen, Entscheidungen und offenen Punkte für Issue #24 (Deep Scan).

## Ziel
LanLens erhält einen optionalen, credential-basierten Deep-Scan-Modus für verwaltete Geräte (Linux, Windows, Hypervisor). Fokus: sichere Inventarisierung, Services, Hypervisor/VM-Mapping, Windows-audit-relevante Daten.

## Grundprinzipien
- Deep Scan ist opt-in (global und pro Gerät).
- Credentials werden nur verwendet, wenn explizit zugewiesen.
- Secrets werden verschlüsselt (Fernet, abgeleitet von SECRET_KEY).
- Scans sind auditierbar; Aktionen und Konfiguration müssen nachvollziehbar sein.
- Initial: Planung/Command-Plan erzeugen; keine automatische Remote-Execution ("planning-only").

## Unterstützte Transports / Auth
- SSH (Linux) - initial: password; key-based optional
- WinRM / PowerShell (Windows)
- Später: hypervisor-spezifische APIs (Proxmox, VMware) falls erforderlich

## Scan-Profile (Beispiele)
- basic: Hardware + OS
- services: Service-/Process-Discovery
- hypervisor: VM-Inventory + mapping
- audit: Windows roles/licensing
- (erweiterbar via Settings / ALLOWED_PROFILES)

## Wichtige Prüf-/Probe-Kommandos (Auszug)
- Linux: cat /etc/os-release, uname -a, lscpu, free -b, lsblk -J, systemctl list-units, docker/podman probes, qm/virsh
- Windows (PowerShell/WinRM): Get-ComputerInfo, Get-CimInstance Win32_*, Get-Service, Get-WindowsFeature, slmgr.vbs, Get-VM (Hyper-V)
- Hypervisor: Proxmox qm, libvirt virsh, VMware via PowerCLI/API

## Datenmodell (auszugsweise)
- deep_scan_credentials
  - id, name, transport, username, port, auth_type, secret_encrypted, notes, use_sudo, verify_tls, timestamps
- devices: neue Felder
  - deep_scan_enabled, deep_scan_profile, deep_scan_credential_id, deep_scan_last_status, deep_scan_last_at, deep_scan_last_error, deep_scan_last_summary
- deep_scan_runs
  - id, device_id, credential_id, trigger_mode, transport, status, started_at, finished_at, command_plan, result_json, error_message
- optional: deep_scan_findings, device_host_relationships

## API (Backend) — Endpunkte
- GET /api/deep-scan/credentials
- POST /api/deep-scan/credentials
- PUT /api/deep-scan/credentials/{id}
- DELETE /api/deep-scan/credentials/{id}
- POST /api/deep-scan/devices/{device_id}/run  (plan/run — initial: queue plan)
- GET /api/deep-scan/devices/{device_id}/runs
- PUT /api/settings/deep-scan  (global enable, default profile)

## UI (Frontend)
- Settings: global enable/disable, default profile, credential management UI
- Device Detail: per-device enable, profile select, credential assign, "Deep Scan planen" Button, run history, command plan preview, result summary
- Secrets masked in UI; limited findings displayed

## Sicherheit & Betrieb
- SECRET_KEY muss gesetzt sein; wird zur Erzeugung des Fernet-Keys verwendet.
- secret_encrypted in DB ist nicht reversibel ohne SECRET_KEY.
- Audit-Logs: wer hat Credentials angelegt/wer hat Scans getriggert.
- Netzwerk-/Firewall-Prüfungen: Ziel muss vom LanLens-Container aus erreichbar sein.
- Docker: host network + cap_add NET_ADMIN/NET_RAW für ARP (dokumentiert)

## Tests / Deliverables
- DB-Migration zur Erstellung/Änderung der Tabellen (deep_scan_credentials, deep_scan_runs, device-Felder)
- Smoke-Tests (Backend):
  - GET /api/deep-scan/credentials
  - POST /api/deep-scan/credentials
  - POST /api/deep-scan/devices/{device_id}/run
  - GET /api/deep-scan/devices/{device_id}/runs
- Verifizieren, dass decrypt_secret() Werte liefert wenn SECRET_KEY korrekt ist und dass secret_encrypted ohne SECRET_KEY nicht lesbar ist
- Unit/Integrationstests für Profile-/Transport-Sanitizer, credential lifecycle
- Frontend Build + quick E2E smoke (optional)

## Offene Entscheidungen / TODO
1. Remote-Execution: paramiko + pypsrp (Python libs) vs system ssh/winrm clients. Empfehlung: paramiko + pypsrp für contained deps; wir passen Dockerfile/requirements.txt an falls zugestimmt.
2. Migrationen im Repo verankern & CI ausführen.
3. ALLOWED_TRANSPORTS, ALLOWED_AUTH_TYPES, ALLOWED_PROFILES final festlegen.
4. SSH key-based secrets erlauben oder initial nur password-based?
5. Execution-Modus: nur Planung (safe) oder optionales Ausführen pro-run (operator-triggered)?
6. Tests: Add test matrix + CI job.

## Änderungen (Arbeitskopie)
Liste der lokal geänderten Dateien (Arbeitskopie in /tmp/lanlens-work):
- backend/models.py
- backend/services/deep_scan.py
- backend/routers/deep_scan.py
- backend/routers/settings.py
- backend/schemas.py
- backend/cli/migrate_db.py
- frontend/src/api/deepScan.ts
- frontend/src/pages/Settings.tsx
- frontend/src/pages/DeviceDetail.tsx
- docs/deep-scan-prerequisites.md
- docs/deep-scan-roadmap.md

---

Wenn du willst, committe und pushe ich diese Datei in PR #25 (branch: dev/issue-24-deep-scan-plan). Soll ich das jetzt machen? Hinweis: Für Commit/Push brauche ich eine kurze Approval (einmalig) — dann erledige ich Commit+Push und update PR #25 mit der neuen Datei.
