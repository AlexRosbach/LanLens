# Deep Scan Roadmap

Issue: [#24](https://github.com/AlexRosbach/LanLens/issues/24)

## Goal

LanLens should gain an optional, credential-based deep scan mode for managed devices. The focus is on secure enrichment of device inventory data, Linux and Windows service discovery, hypervisor visibility, VM-to-host mapping, and Windows audit-relevant metadata such as server roles and licensing state where technically retrievable.

## Principles

- Deep scan is **opt-in** and disabled by default.
- Credentials are used only when explicitly assigned.
- Secrets must be encrypted at rest.
- Deep scan results must be auditable.
- Automatic deep scans must be configurable and restrictive.
- The existing lightweight network scan remains separate.

## Primary use cases

### Linux deep scan
- identify OS, kernel, CPU, RAM, disks, vendor/model where available
- discover running services and selected installed components
- detect Docker / Podman / K3s / container workloads where available
- detect common database and middleware services
- detect virtualization host characteristics (Proxmox, libvirt/KVM, VMware tooling, etc.)

### Windows deep scan
- identify edition, version, hardware details, activation / licensing state where available
- discover installed server roles / features
- detect IIS, Hyper-V, AD DS, DNS, DHCP, RDS / Terminal Services, SQL Server, and similar platform roles
- discover running services and audit-relevant product footprint
- collect data helpful for Microsoft-style audit preparation

### Hypervisor and VM mapping
If a hypervisor is detected and can enumerate guest systems:
- collect VM names, MAC addresses, IP addresses, and virtualization identifiers where available
- match those guests against LanLens devices by MAC address first, then IP address
- tag the matched LanLens device with its current host system
- keep VM-to-host relationships refreshable because workloads can migrate between hosts

## Functional building blocks

### 1. Credential vault
- encrypted secret storage
- credential types: Linux SSH, Windows WinRM/PowerShell, hypervisor-specific if needed later
- optional per-device and reusable credential assignment
- masked UI and strict permission boundaries

### 2. Deep scan configuration
- global enable/disable
- per-device deep scan toggle
- optional auto deep scan policy
- scan profiles such as:
  - Hardware only
  - OS + services
  - Linux container host
  - Windows audit
  - Hypervisor inventory
  - Full deep scan

### 3. Result model
Store structured deep scan findings such as:
- hardware inventory
- OS inventory
- discovered services / roles / products
- container inventory
- database inventory
- hypervisor / guest relationships
- audit notes / evidence timestamps

### 4. Scheduling and refresh
- manual deep scan trigger per device
- scheduled refresh for devices with deep scan enabled
- shorter rescan policy for virtualization hosts and known VMs
- relationship reconciliation so host changes are reflected over time

## Proposed data model additions

### Credentials
- `credentials`
  - id
  - name
  - credential_type
  - username
  - encrypted_secret
  - scope
  - metadata
  - created_at / updated_at

### Device deep scan config
- `device_deep_scan_config`
  - device_id
  - enabled
  - credential_id
  - scan_profile
  - auto_scan_enabled
  - interval_minutes
  - last_scan_at

### Deep scan runs
- `deep_scan_runs`
  - id
  - device_id
  - credential_id
  - profile
  - status
  - started_at / finished_at
  - summary
  - error_message

### Deep scan findings
- `deep_scan_findings`
  - device_id
  - finding_type
  - key
  - value_json
  - source
  - observed_at

### Virtualization relationships
- `device_host_relationships`
  - child_device_id
  - host_device_id
  - relationship_type (`vm_on_host`)
  - match_source (`mac`, `ip`, `hypervisor-id`)
  - observed_at
  - last_confirmed_at

## Discovery logic outline

### Linux
Preferred path:
- SSH
- run a controlled command bundle
- parse structured output where possible

Possible probes:
- `/etc/os-release`
- `uname -a`
- `lscpu`, `free`, `lsblk`
- `systemctl list-units --type=service`
- `docker ps --format`, `docker info`
- `podman ps`, `virsh list`, `qm list`, etc. where available

### Windows
Preferred path:
- WinRM / PowerShell remoting

Possible probes:
- CIM / WMI for hardware and OS
- PowerShell for roles/features
- service inventory via `Get-Service`
- IIS / Hyper-V / AD / DHCP / DNS / RDS feature checks
- licensing and activation data via supported Windows commands / WMI classes where available

### Hypervisor guest matching
Order of confidence:
1. MAC address match
2. IP address match
3. hypervisor-specific guest identifier stored as supporting evidence

## UI proposal

### Settings
- Deep Scan enable/disable
- Credentials
- Scan profiles
- Auto deep scan defaults
- Encryption / security notes

### Device detail
- assigned credential
- deep scan profile
- run deep scan now
- last deep scan status
- hardware / OS / services / containers / audit details
- current host system if VM relationship exists

### Host device detail
- guest inventory
- relationship confidence
- last guest reconciliation timestamp

## Security and compliance notes

- never store credentials in plaintext
- separate app secret / encryption key from database storage
- log who configured and triggered deep scans
- expose only the minimum necessary findings in the UI
- treat licensing/audit data as sensitive inventory information

## Delivery phases

### Phase 1: secure foundation
- credential vault
- deep scan settings model
- manual Linux SSH deep scan
- hardware / OS / services findings

### Phase 2: Windows audit mode
- WinRM / PowerShell deep scan
- Windows roles / features / services
- licensing / activation visibility where possible
- audit-oriented result panels

### Phase 3: hypervisor intelligence
- detect Proxmox / VMware / Hyper-V hosts
- enumerate guests
- map VMs to known LanLens devices
- periodic relationship reconciliation

### Phase 4: automation and refinement
- auto deep scan policies
- scheduling by profile
- richer service fingerprinting
- optional evidence export for audit workflows

## Non-goals for the first implementation

- unrestricted remote execution on arbitrary hosts
- default deep scanning of every discovered device
- cross-subnet credential crawling without explicit setup
- full agent-based management platform behavior
