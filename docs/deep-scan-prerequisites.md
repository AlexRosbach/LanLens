# Deep Scan Prerequisites

This document describes what must be in place for LanLens deep scan to work reliably once implemented.

## General prerequisites

- Deep scan must be explicitly enabled in LanLens.
- Valid credentials must be stored securely and assigned intentionally.
- The target host must be reachable from the LanLens container/host.
- Firewalls, routing, name resolution, and required management ports must allow access.
- The scan account should be a dedicated technical account with the minimum permissions needed.

## Linux targets

### Recommended access method
- SSH

### Requirements
- SSH reachable from LanLens
- a technical user account for inventory/deep scan tasks
- sufficient rights to read system/service/container metadata
- optional sudo permissions for selected read-only commands where needed

### Useful capabilities
- read `/etc/os-release`
- run `uname`, `lscpu`, `free`, `lsblk`
- inspect `systemctl`
- inspect Docker / Podman if container detection is wanted
- inspect hypervisor tooling (`qm`, `virsh`, etc.) if virtualization inventory is wanted

### Good practice
- create a dedicated read-focused account
- restrict commands where possible
- document which probes require elevated rights

## Windows targets

### Recommended access method
- WinRM / PowerShell remoting

### Requirements
- WinRM enabled and reachable
- firewall rules allow the chosen management transport
- a technical administrative or sufficiently delegated account
- PowerShell / CIM / WMI access to inventory data

### Useful capabilities
- query OS edition/version and hardware data
- query installed roles and features
- query running services
- query Hyper-V / IIS / AD / DHCP / DNS / RDS / SQL Server footprint where present
- retrieve licensing / activation data where Windows exposes it

### Good practice
- use a dedicated audit/inventory account
- limit interactive use of the account
- document exactly which permissions are required for each scan profile

## Hypervisor targets

### Proxmox
Expected capabilities may include:
- VM inventory
- MAC/IP/guest metadata where exposed
- host identification

### VMware
Expected capabilities may include:
- ESXi/vCenter guest inventory
- MAC/IP/guest metadata where exposed
- host association

### Hyper-V
Expected capabilities may include:
- VM inventory
- MAC/IP/guest metadata where exposed
- host association

## Networking considerations

- Deep scan is separate from ARP discovery.
- ARP discovery still depends on the locally reachable Layer-2 network.
- Deep scan management access may work across routed networks if the management protocol is reachable and permitted.
- Guest-to-host mapping depends on reliable MAC/IP visibility from the target platform.

## Security expectations

- credentials encrypted at rest
- audit trail for configuration and execution
- opt-in execution only
- clear warning when automatic deep scan is enabled
- mask secrets in UI and logs

## Operational recommendation

Start small:
1. manual deep scan on a few known Linux hosts
2. add Windows audit profile
3. enable hypervisor guest mapping
4. enable scheduled scans only after confidence is high
