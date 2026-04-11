import base64
import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DeepScanCredential, DeepScanRun, Device, DeepScanFinding

ALLOWED_TRANSPORTS = {"ssh", "winrm"}
ALLOWED_AUTH_TYPES = {"password"}
ALLOWED_PROFILES = {"basic", "services", "hypervisor", "audit"}


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def sanitize_transport(transport: str) -> str:
    transport = (transport or "ssh").strip().lower()
    if transport not in ALLOWED_TRANSPORTS:
        raise ValueError("Unsupported transport")
    return transport


def sanitize_auth_type(auth_type: str) -> str:
    auth_type = (auth_type or "password").strip().lower()
    if auth_type not in ALLOWED_AUTH_TYPES:
        raise ValueError("Unsupported auth type")
    return auth_type


def sanitize_profile(profile: Optional[str]) -> str:
    profile = (profile or "basic").strip().lower()
    if profile not in ALLOWED_PROFILES:
        raise ValueError("Unsupported deep scan profile")
    return profile


def credential_to_response(credential: DeepScanCredential) -> dict[str, Any]:
    return {
        "id": credential.id,
        "name": credential.name,
        "transport": credential.transport,
        "username": credential.username,
        "port": credential.port,
        "auth_type": credential.auth_type,
        "notes": credential.notes,
        "use_sudo": credential.use_sudo,
        "verify_tls": credential.verify_tls,
        "created_at": credential.created_at,
        "updated_at": credential.updated_at,
    }


def _linux_command_plan(profile: str, use_sudo: bool) -> list[dict[str, Any]]:
    sudo_prefix = "sudo " if use_sudo else ""
    commands: list[dict[str, Any]] = [
        {"key": "os_release", "label": "OS metadata", "command": "cat /etc/os-release"},
        {"key": "kernel", "label": "Kernel and architecture", "command": "uname -a"},
        {"key": "cpu", "label": "CPU inventory", "command": "lscpu"},
        {"key": "memory", "label": "Memory totals", "command": "free -b"},
        {"key": "storage", "label": "Block devices", "command": "lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL,SERIAL"},
        {"key": "services_running", "label": "Running services", "command": "systemctl list-units --type=service --state=running --no-pager --no-legend"},
        {"key": "services_enabled", "label": "Enabled services", "command": "systemctl list-unit-files --type=service --state=enabled --no-pager --no-legend"},
    ]
    if profile in {"services", "hypervisor", "audit"}:
        commands.extend([
            {"key": "docker_info", "label": "Docker engine metadata", "command": "docker info --format '{{json .}}'"},
            {"key": "docker_ps", "label": "Running Docker containers", "command": "docker ps --format '{{json .}}'"},
            {"key": "podman_ps", "label": "Running Podman containers", "command": "podman ps --format json"},
        ])
    if profile in {"hypervisor", "audit"}:
        commands.extend([
            {"key": "qm_list", "label": "Proxmox guests", "command": "qm list"},
            {"key": "virsh_list", "label": "libvirt guests", "command": "virsh list --all"},
        ])
    if profile == "audit":
        commands.append({"key": "dmidecode_system", "label": "System DMI", "command": f"{sudo_prefix}dmidecode -t system".strip()})
    return commands


def _windows_command_plan(profile: str) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = [
        {"key": "computer_info", "label": "Windows edition and version", "command": "Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsArchitecture"},
        {"key": "computer_system", "label": "Hardware model", "command": "Get-CimInstance Win32_ComputerSystem"},
        {"key": "bios", "label": "BIOS and serial", "command": "Get-CimInstance Win32_BIOS"},
        {"key": "processor", "label": "CPU inventory", "command": "Get-CimInstance Win32_Processor"},
        {"key": "memory", "label": "Memory modules", "command": "Get-CimInstance Win32_PhysicalMemory"},
        {"key": "disks", "label": "Disk inventory", "command": "Get-CimInstance Win32_DiskDrive; Get-Volume"},
        {"key": "network", "label": "Active NICs", "command": "Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object {$_.IPEnabled}"},
        {"key": "services", "label": "Running services", "command": "Get-Service | Where-Object {$_.Status -eq 'Running'}"},
    ]
    if profile in {"services", "hypervisor", "audit"}:
        commands.extend([
            {"key": "windows_features", "label": "Installed server roles", "command": "Get-WindowsFeature"},
            {"key": "iis", "label": "IIS footprint", "command": "Get-WindowsFeature Web-Server; Get-Service W3SVC"},
            {"key": "sql", "label": "SQL Server services", "command": "Get-Service | Where-Object {$_.Name -like 'MSSQL*' -or $_.DisplayName -like '*SQL Server*'}"},
        ])
    if profile in {"hypervisor", "audit"}:
        commands.extend([
            {"key": "hyperv_guests", "label": "Hyper-V guests", "command": "Get-VM | Select-Object Name, State, Id"},
            {"key": "hyperv_nics", "label": "Hyper-V guest NICs", "command": "Get-VM | ForEach-Object { Get-VMNetworkAdapter -VMName $_.Name }"},
        ])
    if profile == "audit":
        commands.extend([
            {"key": "licensing", "label": "Licensing detail", "command": "cscript.exe //NoLogo C:\\Windows\\System32\\slmgr.vbs /dlv"},
            {"key": "licensing_cim", "label": "Structured licensing records", "command": "Get-CimInstance SoftwareLicensingProduct | Where-Object {$_.PartialProductKey}"},
        ])
    return commands


def build_command_plan(device: Device, credential: DeepScanCredential) -> list[dict[str, Any]]:
    profile = sanitize_profile(device.deep_scan_profile)
    if credential.transport == "ssh":
        return _linux_command_plan(profile, credential.use_sudo)
    return _windows_command_plan(profile)


def build_connection_hint(device: Device, credential: DeepScanCredential) -> str:
    host = device.ip_address or device.hostname or "<target-host>"
    port = credential.port or (22 if credential.transport == "ssh" else 5985)
    if credential.transport == "ssh":
        return f"ssh -p {port} {credential.username}@{host}"
    return (
        "Enter-PSSession "
        f"-ComputerName {host} -Port {port} -Authentication Default -Credential {credential.username}"
    )


def queue_deep_scan(db: Session, device: Device) -> DeepScanRun:
    credential = device.deep_scan_credential
    if credential is None:
        raise ValueError("No deep scan credential assigned")

    plan = build_command_plan(device, credential)
    run = DeepScanRun(
        device_id=device.id,
        credential_id=credential.id,
        trigger_mode="manual",
        transport=credential.transport,
        status="planned",
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        command_plan=json.dumps(plan),
        result_json=json.dumps(
            {
                "profile": sanitize_profile(device.deep_scan_profile),
                "connection_hint": build_connection_hint(device, credential),
                "execution_mode": "planning-only",
                "secret_configured": bool(decrypt_secret(credential.secret_encrypted)),
                "commands_planned": len(plan),
            }
        ),
    )
    db.add(run)

    # Persist summary findings for the planning run so UI can display immediate feedback.
    summary_finding = DeepScanFinding(
        run_id=run.id,
        key="summary",
        value=json.dumps({
            "profile": sanitize_profile(device.deep_scan_profile),
            "transport": credential.transport,
            "commands_planned": len(plan),
            "execution_mode": "planning-only",
            "secret_configured": bool(decrypt_secret(credential.secret_encrypted)),
            "connection_hint": build_connection_hint(device, credential),
        }),
    )
    db.add(summary_finding)

    # Add per-command placeholders (planning only)
    for cmd in plan:
        f = DeepScanFinding(run_id=run.id, key=f"cmd:{cmd.get('key')}", value=cmd.get('command'))
        db.add(f)

    device.deep_scan_last_status = "planned"
    device.deep_scan_last_at = datetime.utcnow()
    device.deep_scan_last_error = None
    device.deep_scan_last_summary = json.dumps(
        {
            "profile": sanitize_profile(device.deep_scan_profile),
            "transport": credential.transport,
            "commands_planned": len(plan),
            "execution_mode": "planning-only",
        }
    )
    return run


def parse_json(value: Optional[str]) -> Optional[dict[str, Any]]:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def parse_plan(value: Optional[str]) -> Optional[list[dict[str, Any]]]:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None
