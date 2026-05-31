"""Optional passive discovery helpers for multicast/service protocols."""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Device, DeviceIpHistory, PassiveDiscoveryObservation
from .mac_vendor import normalize_mac

logger = logging.getLogger(__name__)

_capture_running = False
_capture_lock = threading.Lock()


def is_capture_running() -> bool:
    with _capture_lock:
        return _capture_running


def try_begin_capture() -> bool:
    global _capture_running
    with _capture_lock:
        if _capture_running:
            return False
        _capture_running = True
        return True


def _end_capture() -> None:
    global _capture_running
    with _capture_lock:
        _capture_running = False


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def _bounded_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    return str(value)[:max_length]


def _packet_addrs(packet: Any) -> tuple[str | None, str | None, str | None]:
    source_ip = destination_ip = source_mac = None
    try:
        from scapy.layers.inet import IP
        from scapy.layers.l2 import Ether

        if packet.haslayer(IP):
            source_ip = str(packet[IP].src)
            destination_ip = str(packet[IP].dst)
        if packet.haslayer(Ether):
            source_mac = normalize_mac(str(packet[Ether].src))
    except Exception:
        return source_ip, source_mac, destination_ip
    return source_ip, source_mac, destination_ip


def _summary_from_metadata(protocol: str, metadata: dict[str, Any]) -> str:
    if protocol == "mdns":
        questions = metadata.get("questions") or []
        answers = metadata.get("answers") or []
        names = [item.get("name") for item in questions + answers if isinstance(item, dict) and item.get("name")]
        return ", ".join(names[:3]) if names else "mDNS packet observed"
    if protocol == "ssdp":
        method = metadata.get("method") or metadata.get("status") or "SSDP"
        target = metadata.get("st") or metadata.get("nt") or metadata.get("usn") or ""
        return f"{method} {target}".strip()
    return metadata.get("packet_type") or f"{protocol.upper()} packet observed"


def _iter_dns_section(first_item: Any, expected_type: type, max_count: int) -> list[Any]:
    items: list[Any] = []
    if isinstance(first_item, (list, tuple)):
        return [item for item in first_item[:max(0, max_count)] if isinstance(item, expected_type)]
    current = first_item
    for _ in range(max(0, max_count)):
        if not current or not isinstance(current, expected_type):
            break
        items.append(current)
        current = getattr(current, "payload", None)
    return items


def _mdns_service_type(name: str | None) -> str | None:
    if not name:
        return None
    labels = name.rstrip(".").split(".")
    for index, label in enumerate(labels):
        if label in {"_tcp", "_udp"} and index > 0:
            return ".".join(labels[index - 1:index + 1])
    return None


def parse_mdns_packet(packet: Any) -> PassiveDiscoveryObservation | None:
    try:
        from scapy.layers.dns import DNS, DNSQR, DNSRR
    except Exception:
        return None
    if not packet.haslayer(DNS):
        return None
    dns = packet[DNS]
    source_ip, source_mac, destination_ip = _packet_addrs(packet)
    questions = []
    answers = []
    for item in _iter_dns_section(dns.qd, DNSQR, int(getattr(dns, "qdcount", 0) or 0)):
        questions.append({"name": _json_safe(item.qname).rstrip("."), "type": int(item.qtype)})
    for item in _iter_dns_section(dns.an, DNSRR, int(getattr(dns, "ancount", 0) or 0)):
        answers.append({
            "name": _json_safe(item.rrname).rstrip("."),
            "type": int(item.type),
            "ttl": int(item.ttl),
            "data": _json_safe(item.rdata),
        })
    metadata = {"questions": questions, "answers": answers}
    service_name = next((item["name"] for item in answers + questions if item.get("name")), None)
    service_type = next(
        (parsed for parsed in (_mdns_service_type(item.get("name")) for item in answers + questions) if parsed),
        None,
    )
    return PassiveDiscoveryObservation(
        protocol="mdns",
        source_ip=source_ip,
        source_mac=source_mac,
        destination_ip=destination_ip,
        service_name=_bounded_text(service_name, 255),
        service_type=_bounded_text(service_type, 128),
        summary=_summary_from_metadata("mdns", metadata),
        metadata_json=json.dumps(metadata, default=str, sort_keys=True),
        observed_at=datetime.utcnow(),
    )


def parse_ssdp_payload(payload: bytes | str, source_ip: str | None = None, source_mac: str | None = None, destination_ip: str | None = None) -> PassiveDiscoveryObservation | None:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    if "M-SEARCH" not in text and "NOTIFY" not in text and "HTTP/1.1" not in text:
        return None
    lines = [line.strip() for line in re.split(r"\r?\n", text) if line.strip()]
    if not lines:
        return None
    metadata: dict[str, Any] = {"first_line": lines[0]}
    if lines[0].startswith("HTTP/"):
        metadata["status"] = lines[0]
    else:
        metadata["method"] = lines[0].split(" ", 1)[0]
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().lower()] = value.strip()
    service_name = metadata.get("usn") or metadata.get("location")
    service_type = metadata.get("st") or metadata.get("nt")
    return PassiveDiscoveryObservation(
        protocol="ssdp",
        source_ip=source_ip,
        source_mac=source_mac,
        destination_ip=destination_ip,
        service_name=_bounded_text(service_name, 255),
        service_type=_bounded_text(service_type, 128),
        summary=_summary_from_metadata("ssdp", metadata),
        metadata_json=json.dumps(metadata, default=str, sort_keys=True),
        observed_at=datetime.utcnow(),
    )


def parse_ssdp_packet(packet: Any) -> PassiveDiscoveryObservation | None:
    try:
        from scapy.packet import Raw
    except Exception:
        return None
    if not packet.haslayer(Raw):
        return None
    source_ip, source_mac, destination_ip = _packet_addrs(packet)
    return parse_ssdp_payload(bytes(packet[Raw].load), source_ip, source_mac, destination_ip)


def parse_control_plane_packet(packet: Any) -> PassiveDiscoveryObservation | None:
    source_ip, source_mac, destination_ip = _packet_addrs(packet)
    if not destination_ip:
        return None
    protocol = None
    packet_type = None
    if destination_ip in {"224.0.0.5", "224.0.0.6"}:
        protocol = "ospf"
        packet_type = "OSPF multicast"
    elif destination_ip == "224.0.0.18":
        protocol = "vrrp"
        packet_type = "VRRP multicast"
    elif destination_ip == "224.0.0.2":
        protocol = "hsrp"
        packet_type = "HSRP multicast candidate"
    metadata: dict[str, Any]
    if not protocol:
        if not _is_ipv4_multicast(destination_ip):
            return None
        protocol = "multicast"
        packet_type = "IPv4 multicast packet"
        metadata = _generic_multicast_metadata(packet, destination_ip)
    else:
        metadata = {"packet_type": packet_type, "destination_ip": destination_ip}
    return PassiveDiscoveryObservation(
        protocol=protocol,
        source_ip=source_ip,
        source_mac=source_mac,
        destination_ip=destination_ip,
        summary=packet_type,
        metadata_json=json.dumps(metadata, sort_keys=True),
        observed_at=datetime.utcnow(),
    )


def _is_ipv4_multicast(address: str) -> bool:
    try:
        first_octet = int(address.split(".", 1)[0])
    except (TypeError, ValueError):
        return False
    return 224 <= first_octet <= 239


def _generic_multicast_metadata(packet: Any, destination_ip: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "packet_type": "IPv4 multicast packet",
        "destination_ip": destination_ip,
    }
    try:
        from scapy.layers.inet import UDP

        if packet.haslayer(UDP):
            metadata["transport"] = "udp"
            metadata["source_port"] = int(packet[UDP].sport)
            metadata["destination_port"] = int(packet[UDP].dport)
    except Exception:
        pass
    return metadata


def parse_packet(packet: Any, enabled_protocols: set[str]) -> PassiveDiscoveryObservation | None:
    if "mdns" in enabled_protocols:
        mdns = parse_mdns_packet(packet)
        if mdns:
            return mdns
    if "ssdp" in enabled_protocols:
        ssdp = parse_ssdp_packet(packet)
        if ssdp:
            return ssdp
    if "multicast" in enabled_protocols:
        return parse_control_plane_packet(packet)
    return None


def _metadata_for(row: PassiveDiscoveryObservation) -> dict[str, Any]:
    try:
        value = json.loads(row.metadata_json or "{}")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def observation_signature(row: PassiveDiscoveryObservation) -> tuple[Any, ...]:
    metadata = _metadata_for(row)
    return (
        row.protocol,
        row.source_ip,
        normalize_mac(row.source_mac) if row.source_mac else None,
        row.destination_ip,
        row.service_name,
        row.service_type,
        row.summary,
        metadata.get("source_port"),
        metadata.get("destination_port"),
        metadata.get("query"),
        metadata.get("location"),
    )


def deduplicate_observations(rows: list[PassiveDiscoveryObservation], limit: int) -> list[PassiveDiscoveryObservation]:
    unique: dict[tuple[Any, ...], PassiveDiscoveryObservation] = {}
    for row in rows:
        key = observation_signature(row)
        existing = unique.get(key)
        if existing is None or (row.observed_at and (not existing.observed_at or row.observed_at > existing.observed_at)):
            unique[key] = row
    return sorted(
        unique.values(),
        key=lambda row: row.observed_at or datetime.min,
        reverse=True,
    )[:max(1, limit)]


def _column_matches(column: Any, value: Any) -> Any:
    return column.is_(None) if value is None else column == value


def upsert_passive_observation(db: Session, row: PassiveDiscoveryObservation) -> bool:
    candidates = (
        db.query(PassiveDiscoveryObservation)
        .filter(
            and_(
                PassiveDiscoveryObservation.protocol == row.protocol,
                _column_matches(PassiveDiscoveryObservation.source_ip, row.source_ip),
                _column_matches(PassiveDiscoveryObservation.destination_ip, row.destination_ip),
                _column_matches(PassiveDiscoveryObservation.service_name, row.service_name),
                _column_matches(PassiveDiscoveryObservation.service_type, row.service_type),
                _column_matches(PassiveDiscoveryObservation.summary, row.summary),
            )
        )
        .order_by(PassiveDiscoveryObservation.observed_at.desc())
        .limit(50)
        .all()
    )
    key = observation_signature(row)
    observed_at = row.observed_at or datetime.utcnow()
    row.observed_at = observed_at
    for existing in candidates:
        if observation_signature(existing) != key:
            continue
        existing.observed_at = observed_at
        existing.source_mac = row.source_mac or existing.source_mac
        existing.metadata_json = row.metadata_json or existing.metadata_json
        return False
    db.add(row)
    return True


def _capture_filter(enabled_protocols: set[str]) -> str:
    parts = []
    if "mdns" in enabled_protocols:
        parts.append("udp port 5353")
    if "ssdp" in enabled_protocols:
        parts.append("udp port 1900")
    if "multicast" in enabled_protocols:
        parts.append("ip multicast")
    return " or ".join(parts) or "udp port 5353 or udp port 1900"


def capture_passive_discovery_report(timeout_seconds: int = 30, packet_limit: int = 100, enabled_protocols: set[str] | None = None, reserved: bool = False) -> dict[str, Any]:
    if not reserved and not try_begin_capture():
        return {
            "filter": "",
            "protocols": sorted(enabled_protocols or {"mdns", "ssdp", "multicast"}),
            "packets_seen": 0,
            "packets_parsed": 0,
            "observations_stored": 0,
            "observations_linked": 0,
            "duplicates_skipped": 0,
            "errors": ["Passive discovery capture already running"],
        }
    protocols = enabled_protocols or {"mdns", "ssdp", "multicast"}
    capture_filter = _capture_filter(protocols)
    report: dict[str, Any] = {
        "filter": capture_filter,
        "protocols": sorted(protocols),
        "packets_seen": 0,
        "packets_parsed": 0,
        "observations_stored": 0,
        "observations_linked": 0,
        "duplicates_skipped": 0,
        "errors": [],
    }
    db = SessionLocal()
    try:
        from scapy.sendrecv import sniff

        seen: set[tuple[Any, ...]] = set()

        def handle(packet: Any) -> None:
            report["packets_seen"] += 1
            row = parse_packet(packet, protocols)
            if not row:
                return
            report["packets_parsed"] += 1
            key = observation_signature(row)
            if key in seen:
                report["duplicates_skipped"] += 1
                return
            seen.add(key)
            try:
                if find_linked_device(db, row):
                    report["observations_linked"] += 1
            except Exception as exc:
                logger.debug("Passive discovery device matching failed: %s", exc)
            if upsert_passive_observation(db, row):
                report["observations_stored"] += 1
            else:
                report["duplicates_skipped"] += 1

        sniff(
            filter=capture_filter,
            prn=handle,
            timeout=max(3, min(120, timeout_seconds)),
            count=max(1, min(500, packet_limit)),
            store=False,
        )
        db.commit()
        return report
    except PermissionError as exc:
        logger.warning("Passive discovery needs packet capture permissions: %s", exc)
        db.rollback()
        report["errors"].append(f"Packet capture permission error: {exc}")
        return report
    except Exception as exc:
        logger.warning("Passive discovery capture failed: %s", exc)
        db.rollback()
        report["errors"].append(f"Packet capture failed: {exc}")
        return report
    finally:
        db.close()
        _end_capture()


def capture_passive_discovery(timeout_seconds: int = 30, packet_limit: int = 100, enabled_protocols: set[str] | None = None, reserved: bool = False) -> int:
    report = capture_passive_discovery_report(timeout_seconds, packet_limit, enabled_protocols, reserved)
    return int(report.get("observations_stored") or 0)


def _device_label(device: Device) -> str:
    return device.label or device.hostname or device.ip_address or device.mac_address or f"Device #{device.id}"


def find_linked_device(db: Session, row: PassiveDiscoveryObservation) -> Device | None:
    filters = []
    source_ip = (row.source_ip or "").strip()
    source_mac = normalize_mac(row.source_mac) if row.source_mac else None
    if source_ip:
        filters.append(Device.ip_address == source_ip)
    if source_mac:
        filters.append(Device.mac_address == source_mac)
        filters.append(Device.mac_address == source_mac.lower())
    if filters:
        device = db.query(Device).filter(or_(*filters)).order_by(Device.last_seen.desc()).first()
        if device:
            return device
    if source_ip:
        history_match = (
            db.query(Device)
            .join(DeviceIpHistory, DeviceIpHistory.device_id == Device.id)
            .filter(DeviceIpHistory.ip_address == source_ip)
            .order_by(DeviceIpHistory.last_seen.desc())
            .first()
        )
        if history_match:
            return history_match
    return None


def observation_to_response(row: PassiveDiscoveryObservation, db: Session | None = None) -> dict[str, Any]:
    try:
        metadata = json.loads(row.metadata_json or "{}")
    except Exception:
        metadata = {}
    linked_device = find_linked_device(db, row) if db is not None else None
    return {
        "id": row.id,
        "protocol": row.protocol,
        "source_ip": row.source_ip,
        "source_mac": row.source_mac,
        "destination_ip": row.destination_ip,
        "service_name": row.service_name,
        "service_type": row.service_type,
        "summary": row.summary,
        "metadata": metadata,
        "observed_at": row.observed_at,
        "linked_device_id": linked_device.id if linked_device else None,
        "linked_device_label": _device_label(linked_device) if linked_device else None,
    }
