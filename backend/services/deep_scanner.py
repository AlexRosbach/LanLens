"""
Deep scan orchestrator — SSH (Linux) and WinRM (Windows).

Coordinates credential decryption, remote command execution, result parsing,
finding storage, and hypervisor VM-to-host reconciliation.

Linux probes use Paramiko SSH.
Windows probes use pywinrm (WinRM / PowerShell remoting).

Both libraries are imported lazily so that missing optional packages
produce a clear runtime error only when a scan is actually attempted,
not at application startup.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import (
    Credential,
    Device,
    DeviceDeepScanConfig,
    DeviceHostRelationship,
    DeepScanFinding,
    DeepScanRun,
)
from .crypto import decrypt_secret

logger = logging.getLogger(__name__)

# ── Scan profile command bundles ──────────────────────────────────────────────
# Each entry is a tuple: (finding_type, key, shell_command)
# Commands must be safe, non-destructive, and produce line-based or JSON output.

_LINUX_HARDWARE = [
    ("hardware", "vendor",      "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true"),
    ("hardware", "model",       "cat /sys/class/dmi/id/product_name 2>/dev/null || true"),
    ("hardware", "serial",      "cat /sys/class/dmi/id/product_serial 2>/dev/null || true"),
    ("hardware", "cpu",         "lscpu 2>/dev/null || true"),
    ("hardware", "memory",      "free -h 2>/dev/null || true"),
    ("hardware", "disks",       "lsblk -d -o NAME,SIZE,TYPE,MODEL 2>/dev/null || true"),
]

_LINUX_OS = [
    ("os", "release",   "cat /etc/os-release 2>/dev/null || true"),
    ("os", "kernel",    "uname -a 2>/dev/null || true"),
    ("os", "hostname",  "hostname -f 2>/dev/null || true"),
    ("os", "uptime",    "uptime 2>/dev/null || true"),
]

_LINUX_SERVICES = [
    ("service", "systemd_units",
     "systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null || true"),
]

_LINUX_CONTAINERS = [
    ("container", "docker_containers",
     "docker ps --format '{{json .}}' 2>/dev/null || true"),
    ("container", "docker_info",
     "docker info --format '{{json .}}' 2>/dev/null || true"),
    ("container", "podman_containers",
     "podman ps --format '{{json .}}' 2>/dev/null || true"),
    ("container", "k3s_pods",
     "k3s kubectl get pods -A -o json 2>/dev/null || true"),
]

_LINUX_HYPERVISOR = [
    ("hypervisor", "kvm_vms",        "virsh list --all 2>/dev/null || true"),
    ("hypervisor", "proxmox_qemu",   "qm list 2>/dev/null || true"),
    ("hypervisor", "proxmox_ct",     "pct list 2>/dev/null || true"),
    ("hypervisor", "libvirt_nets",   "virsh net-list --all 2>/dev/null || true"),
    # Proxmox: fetch individual VM/CT configs to extract MAC addresses
    ("hypervisor", "proxmox_qemu_configs",
     "for vmid in $(qm list 2>/dev/null | tail -n +2 | awk '{print $1}'); do"
     " printf 'VMID:%s\\n' \"$vmid\"; qm config \"$vmid\" 2>/dev/null; printf '---\\n'; done"),
    ("hypervisor", "proxmox_ct_configs",
     "for ctid in $(pct list 2>/dev/null | tail -n +2 | awk '{print $1}'); do"
     " printf 'CTID:%s\\n' \"$ctid\"; pct config \"$ctid\" 2>/dev/null; printf '---\\n'; done"),
]

LINUX_PROFILE_COMMANDS: Dict[str, List[Tuple[str, str, str]]] = {
    "hardware_only":        _LINUX_HARDWARE + _LINUX_OS[:2],
    "os_services":          _LINUX_HARDWARE + _LINUX_OS + _LINUX_SERVICES,
    "linux_container_host": _LINUX_HARDWARE + _LINUX_OS + _LINUX_SERVICES + _LINUX_CONTAINERS,
    "hypervisor_inventory": _LINUX_HARDWARE + _LINUX_OS + _LINUX_SERVICES + _LINUX_HYPERVISOR,
    "full":                 _LINUX_HARDWARE + _LINUX_OS + _LINUX_SERVICES
                            + _LINUX_CONTAINERS + _LINUX_HYPERVISOR,
}
LINUX_PROFILE_COMMANDS["windows_audit"] = []  # not applicable for Linux

# ── Windows PowerShell command bundles ───────────────────────────────────────

_WIN_HARDWARE = [
    ("hardware", "computer_system",
     "Get-CimInstance -ClassName Win32_ComputerSystem | ConvertTo-Json -Compress"),
    ("hardware", "bios",
     "Get-CimInstance -ClassName Win32_BIOS | ConvertTo-Json -Compress"),
    ("hardware", "processor",
     "Get-CimInstance -ClassName Win32_Processor | Select-Object Name,NumberOfCores,MaxClockSpeed | ConvertTo-Json -Compress"),
    ("hardware", "physical_memory",
     "Get-CimInstance -ClassName Win32_PhysicalMemory | Select-Object Capacity,Speed | ConvertTo-Json -Compress"),
    ("hardware", "disk_drives",
     "Get-CimInstance -ClassName Win32_DiskDrive | Select-Object Model,Size,MediaType | ConvertTo-Json -Compress"),
]

_WIN_OS = [
    ("os", "operating_system",
     "Get-CimInstance -ClassName Win32_OperatingSystem | ConvertTo-Json -Compress"),
]

_WIN_SERVICES = [
    ("service", "running_services",
     "Get-Service | Where-Object {$_.Status -eq 'Running'} | Select-Object Name,DisplayName | ConvertTo-Json -Compress"),
]

_WIN_AUDIT = [
    ("audit", "windows_features",
     "Get-WindowsFeature | Where-Object {$_.InstallState -eq 'Installed'} | Select-Object Name,DisplayName | ConvertTo-Json -Compress"),
    ("audit", "licensing",
     "(Get-WmiObject -Query \"SELECT Name,LicenseStatus,PartialProductKey FROM SoftwareLicensingProduct WHERE PartialProductKey IS NOT NULL AND Name LIKE 'Windows%'\") | Select-Object Name,LicenseStatus | ConvertTo-Json -Compress"),
    ("audit", "iis_sites",
     "if (Get-Module -ListAvailable WebAdministration) { Import-Module WebAdministration; Get-Website | Select-Object Name,State,PhysicalPath | ConvertTo-Json -Compress } else { Write-Output 'IIS_NOT_INSTALLED' }"),
    ("audit", "hyper_v_vms",
     "if (Get-Module -ListAvailable Hyper-V) { Get-VM | Select-Object Name,State,Generation | ConvertTo-Json -Compress } else { Write-Output 'HYPERV_NOT_INSTALLED' }"),
    ("audit", "sql_instances",
     "Get-Service | Where-Object {$_.Name -like 'MSSQL*'} | Select-Object Name,DisplayName,Status | ConvertTo-Json -Compress"),
    ("audit", "ad_domain",
     "try { (Get-ADDomain).DNSRoot } catch { Write-Output 'AD_NOT_INSTALLED' }"),
    ("audit", "dhcp_scopes",
     "try { Get-DhcpServerv4Scope | Select-Object ScopeId,Name,State | ConvertTo-Json -Compress } catch { Write-Output 'DHCP_NOT_INSTALLED' }"),
]

WIN_PROFILE_COMMANDS: Dict[str, List[Tuple[str, str, str]]] = {
    "hardware_only":  _WIN_HARDWARE + _WIN_OS,
    "os_services":    _WIN_HARDWARE + _WIN_OS + _WIN_SERVICES,
    "windows_audit":  _WIN_HARDWARE + _WIN_OS + _WIN_SERVICES + _WIN_AUDIT,
    "full":           _WIN_HARDWARE + _WIN_OS + _WIN_SERVICES + _WIN_AUDIT,
}
WIN_PROFILE_COMMANDS["linux_container_host"] = []
WIN_PROFILE_COMMANDS["hypervisor_inventory"] = _WIN_HARDWARE + _WIN_OS + _WIN_AUDIT[3:4]  # Hyper-V


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_deep_scan(device_id: int, triggered_by: str = "manual") -> None:
    """Run a deep scan for *device_id* in a background thread.

    Creates a DeepScanRun record immediately (status=running), then
    dispatches to the appropriate scan branch, and finalises the run record.
    """
    db: Session = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            logger.warning("deep_scan: device %s not found", device_id)
            return

        config = db.query(DeviceDeepScanConfig).filter(
            DeviceDeepScanConfig.device_id == device_id
        ).first()
        if not config or not config.credential_id:
            logger.warning("deep_scan: no credential configured for device %s", device_id)
            return

        credential = db.query(Credential).filter(Credential.id == config.credential_id).first()
        if not credential:
            logger.warning("deep_scan: credential %s not found", config.credential_id)
            return

        run = DeepScanRun(
            device_id=device_id,
            credential_id=credential.id,
            profile=config.scan_profile,
            status="running",
            triggered_by=triggered_by,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        try:
            secret = decrypt_secret(credential.encrypted_secret)
        except ValueError as exc:
            run.status = "error"
            run.error_message = str(exc)
            run.finished_at = datetime.utcnow()
            db.commit()
            return

        try:
            if credential.credential_type == "linux_ssh":
                await asyncio.get_event_loop().run_in_executor(
                    None, _run_linux_scan, db, device, run, credential, secret
                )
            elif credential.credential_type == "windows_winrm":
                await asyncio.get_event_loop().run_in_executor(
                    None, _run_windows_scan, db, device, run, credential, secret
                )
            else:
                run.status = "error"
                run.error_message = f"Unknown credential type: {credential.credential_type}"
                run.finished_at = datetime.utcnow()
                db.commit()
                return

            # Update last_scan_at on config
            config.last_scan_at = datetime.utcnow()
            db.commit()

        except Exception as exc:
            logger.exception("deep_scan: scan failed for device %s", device_id)
            run.status = "error"
            run.error_message = str(exc)
            run.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


# ── Linux SSH scan ────────────────────────────────────────────────────────────

def _run_linux_scan(
    db: Session,
    device: Device,
    run: DeepScanRun,
    credential: Credential,
    secret: str,
) -> None:
    try:
        import paramiko  # type: ignore
    except ImportError:
        run.status = "error"
        run.error_message = "paramiko is not installed. Add 'paramiko>=3.4.0' to requirements.txt."
        run.finished_at = datetime.utcnow()
        db.commit()
        return

    ip = device.ip_address
    if not ip:
        run.status = "error"
        run.error_message = "Device has no IP address."
        run.finished_at = datetime.utcnow()
        db.commit()
        return

    profile = run.profile
    commands = LINUX_PROFILE_COMMANDS.get(profile, LINUX_PROFILE_COMMANDS["os_services"])

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=ip,
            username=credential.username,
            password=secret,
            timeout=15,
            allow_agent=False,
            look_for_keys=False,
        )

        finding_count = 0
        guest_list: List[Dict[str, Any]] = []

        for finding_type, key, cmd in commands:
            try:
                _, stdout, stderr = client.exec_command(cmd, timeout=20)
                output = stdout.read().decode(errors="replace").strip()
                if not output:
                    output = stderr.read().decode(errors="replace").strip()
                if output:
                    _save_finding(db, device.id, run.id, finding_type, key, output, source=cmd.split()[0])
                    finding_count += 1

                    # Parse hypervisor output for VM guest reconciliation
                    if finding_type == "hypervisor":
                        guests = _parse_hypervisor_guests(key, output, client)
                        guest_list.extend(guests)

            except Exception as exc:
                logger.debug("deep_scan: command '%s' failed: %s", cmd[:60], exc)

        # Reconcile VM guests discovered via hypervisor commands
        if guest_list:
            _reconcile_vm_guests(db, device.id, run.id, guest_list)

        run.status = "done"
        run.finished_at = datetime.utcnow()
        run.summary_json = json.dumps({"findings": finding_count, "guests": len(guest_list)})
        db.commit()

    except Exception as exc:
        run.status = "error"
        run.error_message = str(exc)
        run.finished_at = datetime.utcnow()
        db.commit()
        raise
    finally:
        client.close()


def _parse_hypervisor_guests(
    key: str,
    output: str,
    client: Any,
) -> List[Dict[str, Any]]:
    """Extract VM guest info (name, mac, ip) from hypervisor command output."""
    guests: List[Dict[str, Any]] = []

    if key == "kvm_vms":
        # virsh list --all output: Id  Name  State
        for line in output.splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 2:
                vm_name = parts[1]
                mac_addrs = _virsh_domiflist(client, vm_name)
                for mac in mac_addrs:
                    guests.append({"name": vm_name, "mac": mac, "ip": None, "source": "virsh"})

    elif key == "proxmox_qemu":
        # qm list output: VMID  Name  Status  Mem  BootDisk  PID
        # Only collect names here; MACs come from proxmox_qemu_configs
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                vm_name = parts[1]
                guests.append({"name": vm_name, "mac": None, "ip": None, "source": "qm_list"})

    elif key == "proxmox_ct":
        # pct list output: VMID  Status  [Lock]  Name
        # When Lock column is empty, split() produces 3 parts instead of 4
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                # Name is always the last token; VMID is always first
                ct_name = parts[-1]
                guests.append({"name": ct_name, "mac": None, "ip": None, "source": "pct_list"})

    elif key == "proxmox_qemu_configs":
        # Each block: "VMID:101\nnet0: virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,...\n---"
        # net interface types: virtio, e1000, e1000e, vmxnet3, rtl8139
        _NET_TYPES = ("virtio=", "e1000=", "e1000e=", "vmxnet3=", "rtl8139=")
        for block in output.split("---"):
            block = block.strip()
            if not block:
                continue
            vmid = None
            name = None
            macs: List[str] = []
            for line in block.splitlines():
                line = line.strip()
                if line.startswith("VMID:"):
                    vmid = line[5:].strip()
                elif line.startswith("name:"):
                    name = line[5:].strip()
                elif line.startswith("net") and ":" in line:
                    config_part = line.split(":", 1)[1].strip()
                    for part in config_part.split(","):
                        part = part.strip()
                        for prefix in _NET_TYPES:
                            if part.startswith(prefix):
                                mac = part[len(prefix):]
                                if len(mac) == 17 and mac.count(":") == 5:
                                    macs.append(mac.upper())
                                break
            label = name or (f"VM-{vmid}" if vmid else None)
            if label:
                if macs:
                    for mac in macs:
                        guests.append({"name": label, "mac": mac, "ip": None, "source": "qm_config"})
                else:
                    guests.append({"name": label, "mac": None, "ip": None, "source": "qm_config"})

    elif key == "proxmox_ct_configs":
        # Each block: "CTID:200\nnet0: name=eth0,bridge=vmbr0,hwaddr=BC:24:11:AA:BB:CC,...\n---"
        for block in output.split("---"):
            block = block.strip()
            if not block:
                continue
            ctid = None
            hostname = None
            macs: List[str] = []
            for line in block.splitlines():
                line = line.strip()
                if line.startswith("CTID:"):
                    ctid = line[5:].strip()
                elif line.startswith("hostname:"):
                    hostname = line[9:].strip()
                elif line.startswith("net") and "hwaddr=" in line:
                    for part in line.split(","):
                        part = part.strip()
                        if part.startswith("hwaddr="):
                            mac = part[7:]
                            if len(mac) == 17 and mac.count(":") == 5:
                                macs.append(mac.upper())
            label = hostname or (f"CT-{ctid}" if ctid else None)
            if label:
                if macs:
                    for mac in macs:
                        guests.append({"name": label, "mac": mac, "ip": None, "source": "pct_config"})
                else:
                    guests.append({"name": label, "mac": None, "ip": None, "source": "pct_config"})

    return guests


def _virsh_domiflist(client: Any, vm_name: str) -> List[str]:
    """Return list of MAC addresses for a libvirt domain."""
    macs: List[str] = []
    try:
        _, stdout, _ = client.exec_command(
            f"virsh domiflist '{vm_name}' 2>/dev/null || true", timeout=10
        )
        for line in stdout.read().decode(errors="replace").splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 5:
                mac = parts[4].upper()
                if len(mac) == 17:
                    macs.append(mac)
    except Exception:
        pass
    return macs


# ── Windows WinRM scan ────────────────────────────────────────────────────────

def _run_windows_scan(
    db: Session,
    device: Device,
    run: DeepScanRun,
    credential: Credential,
    secret: str,
) -> None:
    try:
        import winrm  # type: ignore
    except ImportError:
        run.status = "error"
        run.error_message = "pywinrm is not installed. Add 'pywinrm>=0.4.3' to requirements.txt."
        run.finished_at = datetime.utcnow()
        db.commit()
        return

    ip = device.ip_address
    if not ip:
        run.status = "error"
        run.error_message = "Device has no IP address."
        run.finished_at = datetime.utcnow()
        db.commit()
        return

    profile = run.profile
    commands = WIN_PROFILE_COMMANDS.get(profile, WIN_PROFILE_COMMANDS["os_services"])

    try:
        session = winrm.Session(
            f"http://{ip}:5985/wsman",
            auth=(credential.username, secret),
            transport="ntlm",
            server_cert_validation="ignore",
            read_timeout_sec=30,
            operation_timeout_sec=25,
        )

        finding_count = 0
        guest_list: List[Dict[str, Any]] = []

        for finding_type, key, ps_cmd in commands:
            try:
                result = session.run_ps(ps_cmd)
                output = result.std_out.decode(errors="replace").strip()
                if not output and result.std_err:
                    output = result.std_err.decode(errors="replace").strip()
                if output and output not in ("IIS_NOT_INSTALLED", "HYPERV_NOT_INSTALLED",
                                             "AD_NOT_INSTALLED", "DHCP_NOT_INSTALLED"):
                    _save_finding(db, device.id, run.id, finding_type, key, output, source="winrm/ps")
                    finding_count += 1

                    # Collect Hyper-V VMs for reconciliation
                    if key == "hyper_v_vms" and output:
                        try:
                            vms = json.loads(output)
                            if isinstance(vms, dict):
                                vms = [vms]
                            for vm in vms:
                                guests.append({
                                    "name": vm.get("Name", ""),
                                    "mac": None,
                                    "ip": None,
                                    "source": "hyper-v",
                                })
                        except (json.JSONDecodeError, TypeError):
                            pass

            except Exception as exc:
                logger.debug("deep_scan (winrm): command '%s' failed: %s", ps_cmd[:60], exc)

        if guest_list:
            _reconcile_vm_guests(db, device.id, run.id, guest_list)

        run.status = "done"
        run.finished_at = datetime.utcnow()
        run.summary_json = json.dumps({"findings": finding_count, "guests": len(guest_list)})
        db.commit()

    except Exception as exc:
        run.status = "error"
        run.error_message = str(exc)
        run.finished_at = datetime.utcnow()
        db.commit()
        raise


# ── Shared helpers ────────────────────────────────────────────────────────────

def _save_finding(
    db: Session,
    device_id: int,
    run_id: int,
    finding_type: str,
    key: str,
    value: Any,
    source: Optional[str] = None,
) -> None:
    """Persist a single finding; value is JSON-encoded."""
    if isinstance(value, str):
        value_json = json.dumps(value)
    else:
        value_json = json.dumps(value)

    finding = DeepScanFinding(
        device_id=device_id,
        run_id=run_id,
        finding_type=finding_type,
        key=key,
        value_json=value_json,
        source=source,
        observed_at=datetime.utcnow(),
    )
    db.add(finding)
    db.flush()


def _reconcile_vm_guests(
    db: Session,
    host_device_id: int,
    run_id: int,
    guest_list: List[Dict[str, Any]],
) -> None:
    """Match discovered hypervisor guests against known LanLens devices.

    Matching order: MAC address (preferred) → IP address → unmatched (stored as finding only).
    Upserts DeviceHostRelationship rows for confirmed matches.

    De-duplicates guest_list so that qm_config / pct_config entries (with MACs) take
    precedence over the corresponding qm_list / pct_list entries (without MACs).
    """
    from ..models import Device as DeviceModel

    # De-duplicate: prefer entries with a MAC over entries without for the same name.
    # Build a dict keyed by (name, source_category) → keep MAC-bearing entry.
    deduped: Dict[str, Dict[str, Any]] = {}
    for g in guest_list:
        key = (g.get("name") or "").lower()
        existing = deduped.get(key)
        if existing is None or (g.get("mac") and not existing.get("mac")):
            deduped[key] = g
    guest_list = list(deduped.values())

    all_devices = db.query(DeviceModel).filter(DeviceModel.id != host_device_id).all()
    mac_index = {d.mac_address.upper(): d for d in all_devices if d.mac_address}
    ip_index  = {d.ip_address: d for d in all_devices if d.ip_address}

    for guest in guest_list:
        matched_device: Optional[Device] = None
        match_source: Optional[str] = None

        guest_mac = (guest.get("mac") or "").upper().strip()
        guest_ip  = (guest.get("ip") or "").strip()

        if guest_mac and guest_mac in mac_index:
            matched_device = mac_index[guest_mac]
            match_source = "mac"
        elif guest_ip and guest_ip in ip_index:
            matched_device = ip_index[guest_ip]
            match_source = "ip"

        if matched_device:
            existing = db.query(DeviceHostRelationship).filter(
                DeviceHostRelationship.child_device_id == matched_device.id,
                DeviceHostRelationship.host_device_id == host_device_id,
            ).first()

            now = datetime.utcnow()
            if existing:
                existing.last_confirmed_at = now
                existing.match_source = match_source
                existing.vm_identifier = guest.get("name")
            else:
                rel = DeviceHostRelationship(
                    child_device_id=matched_device.id,
                    host_device_id=host_device_id,
                    relationship_type="vm_on_host",
                    match_source=match_source,
                    vm_identifier=guest.get("name"),
                    observed_at=now,
                    last_confirmed_at=now,
                )
                db.add(rel)

    db.flush()


# ── Auto-scan poll (called by scheduler) ─────────────────────────────────────

async def poll_auto_scans() -> None:
    """Check which devices are due for an automatic deep scan and run them.

    Two sources of auto-scan triggers are checked:
    1. Per-device configs with auto_scan_enabled=True
    2. Global AutoScanRule rows that match devices by device_class
    """
    from ..models import AutoScanRule as AutoScanRuleModel

    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()

        # ── 1. Per-device auto-scan configs ──────────────────────────────────
        configs = db.query(DeviceDeepScanConfig).filter(
            DeviceDeepScanConfig.enabled == True,
            DeviceDeepScanConfig.auto_scan_enabled == True,
            DeviceDeepScanConfig.credential_id.isnot(None),
        ).all()

        triggered_device_ids: set = set()

        for config in configs:
            running = db.query(DeepScanRun).filter(
                DeepScanRun.device_id == config.device_id,
                DeepScanRun.status == "running",
            ).first()
            if running:
                continue

            if config.last_scan_at:
                elapsed = (now - config.last_scan_at).total_seconds() / 60
                if elapsed < config.interval_minutes:
                    continue

            logger.info("deep_scan: per-device auto-scan triggered for device %s", config.device_id)
            asyncio.create_task(run_deep_scan(config.device_id, triggered_by="scheduled"))
            triggered_device_ids.add(config.device_id)

        # ── 2. Global auto-scan rules ─────────────────────────────────────────
        rules = db.query(AutoScanRuleModel).filter(AutoScanRuleModel.enabled == True).all()
        if rules:
            from ..models import Device as DeviceModel

            all_devices = db.query(DeviceModel).all()
            for rule in rules:
                matching = [
                    d for d in all_devices
                    if rule.device_class is None or d.device_class == rule.device_class
                ]
                for device in matching:
                    if device.id in triggered_device_ids:
                        continue  # already scheduled via per-device config

                    running = db.query(DeepScanRun).filter(
                        DeepScanRun.device_id == device.id,
                        DeepScanRun.status == "running",
                    ).first()
                    if running:
                        continue

                    # Find the last completed scan for this device
                    last_run = db.query(DeepScanRun).filter(
                        DeepScanRun.device_id == device.id,
                        DeepScanRun.status == "done",
                    ).order_by(DeepScanRun.started_at.desc()).first()

                    if last_run:
                        elapsed = (now - last_run.started_at).total_seconds() / 60
                        if elapsed < rule.interval_minutes:
                            continue

                    # Temporarily override device config for this rule-triggered scan
                    config = db.query(DeviceDeepScanConfig).filter(
                        DeviceDeepScanConfig.device_id == device.id
                    ).first()
                    if config is None:
                        config = DeviceDeepScanConfig(
                            device_id=device.id,
                            enabled=True,
                            credential_id=rule.credential_id,
                            scan_profile=rule.scan_profile,
                            auto_scan_enabled=False,
                            interval_minutes=rule.interval_minutes,
                        )
                        db.add(config)
                        db.flush()
                    elif not config.credential_id:
                        config.credential_id = rule.credential_id
                        config.scan_profile = rule.scan_profile
                        config.enabled = True
                        db.flush()

                    logger.info(
                        "deep_scan: rule '%s' triggered auto-scan for device %s",
                        rule.name, device.id
                    )
                    asyncio.create_task(run_deep_scan(device.id, triggered_by="rule"))
                    triggered_device_ids.add(device.id)

        db.commit()

    except Exception:
        logger.exception("deep_scan: auto-scan poll failed")
    finally:
        db.close()
