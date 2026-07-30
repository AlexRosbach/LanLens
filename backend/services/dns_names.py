"""DNS name collection and read-only AXFR zone synchronization."""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import dns.exception
import dns.query
import dns.reversename
import dns.rdatatype
import dns.tsig
import dns.tsigkeyring
import dns.zone
from sqlalchemy.orm import Session

from ..models import Device, DeviceDnsName, Setting
from .crypto import decrypt_secret, encrypt_secret


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
class AxfrDnsConfig:
    dns_names_enabled: bool = False
    enabled: bool = False
    server: str = ""
    zones: list[str] | None = None
    port: int = 53
    timeout_seconds: int = 15
    tsig_key_name: str = ""
    tsig_secret: str | None = None
    tsig_algorithm: str = "hmac-sha256"
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


def get_axfr_dns_config(db: Session) -> AxfrDnsConfig:
    raw_zones = _setting(db, "axfr_dns_zones", "[]")
    try:
        zones = [str(item).strip() for item in json.loads(raw_zones) if str(item).strip()]
    except (TypeError, ValueError):
        zones = []
    raw_last_sync = _setting(db, "axfr_dns_last_sync_at", "")
    encrypted_tsig_secret = _setting(db, "axfr_dns_tsig_secret", "")
    try:
        tsig_secret = decrypt_secret(encrypted_tsig_secret) if encrypted_tsig_secret else None
    except ValueError:
        tsig_secret = None
    try:
        last_sync = datetime.fromisoformat(raw_last_sync) if raw_last_sync else None
    except ValueError:
        last_sync = None
    return AxfrDnsConfig(
        dns_names_enabled=_setting(db, "dns_names_enabled", "false") == "true",
        enabled=_setting(db, "axfr_dns_enabled", "false") == "true",
        server=_setting(db, "axfr_dns_server", ""),
        zones=zones,
        port=max(1, min(65535, int(_setting(db, "axfr_dns_port", "53") or 53))),
        timeout_seconds=max(3, min(120, int(_setting(db, "axfr_dns_timeout_seconds", "15") or 15))),
        tsig_key_name=_setting(db, "axfr_dns_tsig_key_name", ""),
        tsig_secret=tsig_secret,
        tsig_algorithm=_setting(db, "axfr_dns_tsig_algorithm", "hmac-sha256"),
        interval_minutes=max(5, int(_setting(db, "axfr_dns_interval_minutes", "60") or 60)),
        last_sync_at=last_sync,
        last_error=_setting(db, "axfr_dns_last_error", ""),
    )


def save_axfr_dns_config(db: Session, config: AxfrDnsConfig) -> None:
    _set_setting(db, "dns_names_enabled", "true" if config.dns_names_enabled else "false")
    _set_setting(db, "axfr_dns_enabled", "true" if config.enabled else "false")
    _set_setting(db, "axfr_dns_server", config.server.strip())
    _set_setting(db, "axfr_dns_zones", json.dumps(config.zones or []))
    _set_setting(db, "axfr_dns_port", str(max(1, min(65535, config.port))))
    _set_setting(db, "axfr_dns_timeout_seconds", str(max(3, min(120, config.timeout_seconds))))
    _set_setting(db, "axfr_dns_tsig_key_name", normalize_dns_name(config.tsig_key_name))
    _set_setting(db, "axfr_dns_tsig_secret", encrypt_secret(config.tsig_secret) if config.tsig_secret else "")
    _set_setting(db, "axfr_dns_tsig_algorithm", config.tsig_algorithm.strip() or "hmac-sha256")
    _set_setting(db, "axfr_dns_interval_minutes", str(max(5, config.interval_minutes)))


def _transfer_zone(config: AxfrDnsConfig, zone_name: str):
    keyring = None
    keyname = None
    if config.tsig_key_name or config.tsig_secret:
        if not config.tsig_key_name or not config.tsig_secret:
            raise ValueError("Both TSIG key name and secret are required")
        keyname = normalize_dns_name(config.tsig_key_name) + "."
        keyring = dns.tsigkeyring.from_text({keyname: config.tsig_secret})
    try:
        server_address = socket.getaddrinfo(
            config.server.strip(),
            config.port,
            type=socket.SOCK_STREAM,
        )[0][4][0]
    except socket.gaierror as exc:
        raise ValueError("AXFR DNS server could not be resolved") from exc
    transfer = dns.query.xfr(
        where=server_address,
        zone=normalize_dns_name(zone_name),
        port=config.port,
        timeout=config.timeout_seconds,
        lifetime=config.timeout_seconds,
        keyring=keyring,
        keyname=keyname,
        keyalgorithm=config.tsig_algorithm or dns.tsig.default_algorithm,
        relativize=False,
    )
    return dns.zone.from_xfr(transfer, relativize=False)


def fetch_axfr_dns_records(config: AxfrDnsConfig) -> list[dict[str, Any]]:
    if not config.server or not config.zones:
        raise ValueError("AXFR DNS server and at least one zone are required")
    records: list[dict[str, Any]] = []
    for configured_zone in config.zones:
        zone_name = normalize_dns_name(configured_zone)
        zone = _transfer_zone(config, zone_name)
        for owner, node in zone.nodes.items():
            fqdn = normalize_dns_name(owner.to_text())
            host_name = "@" if fqdn == zone_name else fqdn.removesuffix(f".{zone_name}")
            for rdataset in node.rdatasets:
                record_type = dns.rdatatype.to_text(rdataset.rdtype)
                if record_type not in {"A", "AAAA", "PTR", "CNAME"}:
                    continue
                for rdata in rdataset:
                    address = str(rdata.address) if record_type in {"A", "AAAA"} else None
                    canonical = (
                        normalize_dns_name(str(rdata.target))
                        if record_type in {"PTR", "CNAME"}
                        else None
                    )
                    observed_name = fqdn
                    if record_type == "PTR":
                        observed_name = canonical or fqdn
                        try:
                            address = dns.reversename.to_address(owner)
                        except dns.exception.DNSException:
                            address = None
                    records.append({
                        "zone": zone_name,
                        "host_name": host_name,
                        "name": observed_name,
                        "record_type": record_type,
                        "address": address,
                        "canonical_name": canonical,
                    })
    return records


def synchronize_axfr_dns(db: Session, config: AxfrDnsConfig) -> dict[str, int]:
    if not config.enabled:
        return {"records": 0, "names": 0, "devices": 0}
    records = fetch_axfr_dns_records(config)
    db.query(DeviceDnsName).filter(DeviceDnsName.source == "dns_axfr").update(
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
            name = normalize_dns_name(record.get("name")) or (zone if host in {"", "@"} else f"{host}.{zone}")
            address = str(record.get("address") or "").strip() or None
            canonical = normalize_dns_name(record.get("canonical_name")) or None
            device = by_address.get(address) or by_name.get(canonical) or by_name.get(name)
            if not device:
                remaining.append(record)
                continue
            status = "active" if not address or address == device.ip_address else "conflicting"
            record_dns_name(
                db, device, name, record_type, "dns_axfr",
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
    _set_setting(db, "axfr_dns_last_sync_at", now.isoformat())
    _set_setting(db, "axfr_dns_last_error", "")
    db.commit()
    return {"records": len(records), "names": names, "devices": len(touched)}
