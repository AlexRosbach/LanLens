"""DNS name collection and read-only Microsoft DNS synchronization."""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import winrm
from sqlalchemy.orm import Session

from ..models import Credential, Device, DeviceDnsName, Setting
from .crypto import decrypt_secret


def normalize_dns_name(value: str | None) -> str:
    return (value or "").strip().lower().rstrip(".")


def device_display_name(device: Device) -> str:
    if device.preferred_name_mode == "manual" and device.preferred_name:
        return device.preferred_name
    if device.preferred_name_mode == "discovered" and device.preferred_name:
        return device.preferred_name
    return device.label or device.hostname or device.ip_address or device.mac_address or f"Device #{device.id}"


def record_dns_name(
    db: Session,
    device: Device,
    name: str | None,
    record_type: str,
    source: str,
    *,
    canonical_name: str | None = None,
    address: str | None = None,
    status: str = "active",
) -> DeviceDnsName | None:
    normalized = normalize_dns_name(name)
    if not normalized:
        return None
    row = (
        db.query(DeviceDnsName)
        .filter(
            DeviceDnsName.device_id == device.id,
            DeviceDnsName.name == normalized,
            DeviceDnsName.record_type == record_type.upper(),
            DeviceDnsName.source == source,
        )
        .first()
    )
    now = datetime.utcnow()
    if row is None:
        row = DeviceDnsName(
            device_id=device.id,
            name=normalized,
            record_type=record_type.upper(),
            source=source,
            first_seen=now,
        )
        db.add(row)
    row.canonical_name = normalize_dns_name(canonical_name) or None
    row.address = address
    row.status = status
    row.last_seen = now
    return row


def collect_standard_dns_names(db: Session, device: Device) -> list[DeviceDnsName]:
    """Collect names available through ordinary forward/reverse DNS."""
    if device.hostname:
        record_dns_name(db, device, device.hostname, "HOSTNAME", "scanner", address=device.ip_address)
    if not device.ip_address:
        return list(device.dns_names)
    try:
        ipaddress.ip_address(device.ip_address)
        primary, aliases, addresses = socket.gethostbyaddr(device.ip_address)
        record_dns_name(db, device, primary, "PTR", "reverse_dns", address=device.ip_address)
        for alias in aliases:
            record_dns_name(db, device, alias, "PTR", "reverse_dns", address=device.ip_address)
        for address in addresses:
            if primary:
                record_dns_name(db, device, primary, "A", "forward_dns", address=address)
    except (OSError, ValueError):
        pass
    db.flush()
    return list(device.dns_names)


@dataclass
class MicrosoftDnsConfig:
    dns_names_enabled: bool = False
    enabled: bool = False
    server: str = ""
    zones: list[str] | None = None
    credential_id: int | None = None
    interval_minutes: int = 60
    last_sync_at: datetime | None = None
    last_error: str = ""


def _setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row and row.value is not None else default


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def get_microsoft_dns_config(db: Session) -> MicrosoftDnsConfig:
    raw_zones = _setting(db, "microsoft_dns_zones", "[]")
    try:
        zones = [str(item).strip() for item in json.loads(raw_zones) if str(item).strip()]
    except (TypeError, ValueError):
        zones = []
    raw_credential = _setting(db, "microsoft_dns_credential_id", "")
    raw_last_sync = _setting(db, "microsoft_dns_last_sync_at", "")
    try:
        last_sync = datetime.fromisoformat(raw_last_sync) if raw_last_sync else None
    except ValueError:
        last_sync = None
    return MicrosoftDnsConfig(
        dns_names_enabled=_setting(db, "dns_names_enabled", "false") == "true",
        enabled=_setting(db, "microsoft_dns_enabled", "false") == "true",
        server=_setting(db, "microsoft_dns_server", ""),
        zones=zones,
        credential_id=int(raw_credential) if raw_credential.isdigit() else None,
        interval_minutes=max(5, int(_setting(db, "microsoft_dns_interval_minutes", "60") or 60)),
        last_sync_at=last_sync,
        last_error=_setting(db, "microsoft_dns_last_error", ""),
    )


def save_microsoft_dns_config(db: Session, config: MicrosoftDnsConfig) -> None:
    _set_setting(db, "dns_names_enabled", "true" if config.dns_names_enabled else "false")
    _set_setting(db, "microsoft_dns_enabled", "true" if config.enabled else "false")
    _set_setting(db, "microsoft_dns_server", config.server.strip())
    _set_setting(db, "microsoft_dns_zones", json.dumps(config.zones or []))
    _set_setting(db, "microsoft_dns_credential_id", str(config.credential_id or ""))
    _set_setting(db, "microsoft_dns_interval_minutes", str(max(5, config.interval_minutes)))


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _session(db: Session, config: MicrosoftDnsConfig) -> winrm.Session:
    if not config.server or not config.credential_id:
        raise ValueError("Microsoft DNS server and WinRM credential are required")
    credential = db.query(Credential).filter(Credential.id == config.credential_id).first()
    if not credential or credential.credential_type != "windows_winrm":
        raise ValueError("Selected credential must be a Windows WinRM credential")
    endpoint = config.server
    if not endpoint.startswith(("http://", "https://")):
        endpoint = f"http://{endpoint}:5985/wsman"
    return winrm.Session(
        endpoint,
        auth=(credential.username, decrypt_secret(credential.encrypted_secret)),
        transport="ntlm",
        server_cert_validation="validate" if endpoint.startswith("https://") else "ignore",
    )


def fetch_microsoft_dns_records(db: Session, config: MicrosoftDnsConfig) -> list[dict[str, Any]]:
    session = _session(db, config)
    zones = config.zones or []
    if not zones:
        command = "Get-DnsServerZone | Where-Object {$_.IsReverseLookupZone -eq $false} | Select-Object -ExpandProperty ZoneName"
        result = session.run_ps(command)
        if result.status_code != 0:
            raise RuntimeError("Unable to list Microsoft DNS zones")
        zones = [line.strip() for line in result.std_out.decode("utf-8", "replace").splitlines() if line.strip()]
    records: list[dict[str, Any]] = []
    for zone in zones:
        script = (
            f"$zone={_powershell_literal(zone)};"
            "Get-DnsServerResourceRecord -ZoneName $zone | "
            "Where-Object {$_.RecordType -in @('A','AAAA','PTR','CNAME')} | "
            "ForEach-Object {"
            "$data=$_.RecordData;"
            "[pscustomobject]@{"
            "zone=$zone;host_name=$_.HostName;record_type=$_.RecordType;"
            "address=$(if($_.RecordType -eq 'A'){$data.IPv4Address.IPAddressToString}"
            "elseif($_.RecordType -eq 'AAAA'){$data.IPv6Address.IPAddressToString}else{$null});"
            "canonical_name=$(if($_.RecordType -eq 'CNAME'){$data.HostNameAlias}"
            "elseif($_.RecordType -eq 'PTR'){$data.PtrDomainName}else{$null})"
            "}} | ConvertTo-Json -Depth 4 -Compress"
        )
        result = session.run_ps(script)
        if result.status_code != 0:
            raise RuntimeError(f"Unable to read Microsoft DNS zone {zone}")
        payload = result.std_out.decode("utf-8", "replace").strip()
        if payload:
            decoded = json.loads(payload)
            records.extend(decoded if isinstance(decoded, list) else [decoded])
    return records


def synchronize_microsoft_dns(db: Session, config: MicrosoftDnsConfig) -> dict[str, int]:
    if not config.enabled:
        return {"records": 0, "names": 0, "devices": 0}
    records = fetch_microsoft_dns_records(db, config)
    db.query(DeviceDnsName).filter(DeviceDnsName.source == "microsoft_dns").update(
        {"status": "stale"},
        synchronize_session=False,
    )
    by_address = {device.ip_address: device for device in db.query(Device).filter(Device.ip_address.isnot(None)).all()}
    by_name: dict[str, Device] = {}
    for device in db.query(Device).all():
        for value in (device.hostname, device.preferred_name, device.label):
            if normalize_dns_name(value):
                by_name[normalize_dns_name(value)] = device
        for row in device.dns_names:
            by_name[normalize_dns_name(row.name)] = device
    touched: set[int] = set()
    names = 0
    pending = sorted(records, key=lambda row: str(row.get("record_type") or "").upper() == "CNAME")
    for _depth in range(8):
        remaining: list[dict[str, Any]] = []
        progress = False
        for record in pending:
            record_type = str(record.get("record_type") or "").upper()
            zone = normalize_dns_name(record.get("zone"))
            host = normalize_dns_name(record.get("host_name"))
            name = zone if host in {"", "@"} else f"{host}.{zone}"
            address = str(record.get("address") or "").strip() or None
            canonical = normalize_dns_name(record.get("canonical_name")) or None
            device = by_address.get(address) or by_name.get(canonical) or by_name.get(name)
            if not device:
                remaining.append(record)
                continue
            status = "active" if not address or address == device.ip_address else "conflicting"
            record_dns_name(
                db, device, name, record_type, "microsoft_dns",
                canonical_name=canonical, address=address, status=status,
            )
            by_name[name] = device
            touched.add(device.id)
            names += 1
            progress = True
        pending = remaining
        if not pending or not progress:
            break
    now = datetime.utcnow()
    _set_setting(db, "microsoft_dns_last_sync_at", now.isoformat())
    _set_setting(db, "microsoft_dns_last_error", "")
    db.commit()
    return {"records": len(records), "names": names, "devices": len(touched)}
