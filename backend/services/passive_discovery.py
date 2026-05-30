"""Optional passive discovery helpers for multicast/service protocols."""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import PassiveDiscoveryObservation
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
    if not protocol:
        return None
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


def _capture_filter(enabled_protocols: set[str]) -> str:
    parts = []
    if "mdns" in enabled_protocols:
        parts.append("udp port 5353")
    if "ssdp" in enabled_protocols:
        parts.append("udp port 1900")
    if "multicast" in enabled_protocols:
        parts.append("ip multicast")
    return " or ".join(parts) or "udp port 5353 or udp port 1900"


def capture_passive_discovery(timeout_seconds: int = 30, packet_limit: int = 100, enabled_protocols: set[str] | None = None, reserved: bool = False) -> int:
    if not reserved and not try_begin_capture():
        return 0
    protocols = enabled_protocols or {"mdns", "ssdp", "multicast"}
    db = SessionLocal()
    stored = 0
    try:
        from scapy.sendrecv import sniff

        seen: set[tuple[str | None, str | None, str | None, str | None]] = set()

        def handle(packet: Any) -> None:
            nonlocal stored
            row = parse_packet(packet, protocols)
            if not row:
                return
            key = (row.protocol, row.source_ip, row.destination_ip, row.service_name)
            if key in seen:
                return
            seen.add(key)
            db.add(row)
            stored += 1

        sniff(
            filter=_capture_filter(protocols),
            prn=handle,
            timeout=max(3, min(120, timeout_seconds)),
            count=max(1, min(500, packet_limit)),
            store=False,
        )
        db.commit()
        return stored
    except PermissionError as exc:
        logger.warning("Passive discovery needs packet capture permissions: %s", exc)
        db.rollback()
        return 0
    except Exception as exc:
        logger.warning("Passive discovery capture failed: %s", exc)
        db.rollback()
        return 0
    finally:
        db.close()
        _end_capture()


def observation_to_response(row: PassiveDiscoveryObservation) -> dict[str, Any]:
    try:
        metadata = json.loads(row.metadata_json or "{}")
    except Exception:
        metadata = {}
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
    }
