"""DHCP response monitor.

This is intentionally not a full DHCP process visualizer. It passively captures
DHCP server replies visible to the LanLens host and stores which DHCP server
announced which options.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import DhcpObservation
from .mac_vendor import normalize_mac

logger = logging.getLogger(__name__)

_capture_running = False
DHCP_OPTION_NAMES = {
    1: "subnet_mask",
    3: "router",
    6: "name_server",
    12: "hostname",
    15: "domain",
    28: "broadcast_address",
    50: "requested_addr",
    51: "lease_time",
    53: "message_type",
    54: "server_id",
    55: "param_req_list",
    58: "renewal_time",
    59: "rebinding_time",
    60: "vendor_class_id",
    61: "client_id",
    119: "domain_search",
}


def is_capture_running() -> bool:
    return _capture_running


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return value.hex()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _option_name(name: Any) -> str:
    if isinstance(name, int):
        return DHCP_OPTION_NAMES.get(name, f"option_{name}")
    return str(name)


def _options_to_dict(options: list[Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for option in options:
        if option == "end" or option == "pad":
            continue
        if isinstance(option, tuple) and option:
            key = _option_name(option[0])
            value = _json_safe(option[1] if len(option) == 2 else option[1:])
            parsed[key] = value
            raw[key] = value
        else:
            raw[str(option)] = _json_safe(option)
    parsed["raw"] = raw
    return parsed


def _message_type(options: dict[str, Any]) -> Optional[str]:
    value = options.get("message-type") or options.get("message_type")
    if isinstance(value, int):
        return {
            1: "discover",
            2: "offer",
            3: "request",
            4: "decline",
            5: "ack",
            6: "nak",
            7: "release",
            8: "inform",
        }.get(value, str(value))
    return str(value) if value else None


def _lease_seconds(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _packet_to_observation(packet: Any) -> Optional[DhcpObservation]:
    try:
        from scapy.layers.dhcp import BOOTP, DHCP
        from scapy.layers.inet import IP, UDP
        from scapy.layers.l2 import Ether
    except Exception as exc:
        logger.warning("DHCP monitor unavailable: scapy DHCP layers could not be loaded: %s", exc)
        return None

    if not packet.haslayer(DHCP) or not packet.haslayer(BOOTP) or not packet.haslayer(UDP):
        return None

    udp = packet[UDP]
    # We only persist DHCP server replies. Client broadcasts are intentionally
    # ignored because this monitor answers "which DHCP server announced which options".
    if int(udp.sport) != 67:
        return None

    options = _options_to_dict(packet[DHCP].options)
    msg_type = _message_type(options)
    server_ip = options.get("server_id") or (packet[IP].src if packet.haslayer(IP) else None)
    bootp = packet[BOOTP]
    server_mac = normalize_mac(packet[Ether].src) if packet.haslayer(Ether) else None
    client_mac = normalize_mac(getattr(bootp, "chaddr", b"")[:6].hex(":")) if getattr(bootp, "chaddr", None) else None
    client_hostname = options.get("hostname")

    return DhcpObservation(
        message_type=msg_type,
        server_ip=str(server_ip) if server_ip else None,
        server_mac=server_mac,
        client_mac=client_mac,
        client_hostname=str(client_hostname) if client_hostname else None,
        offered_ip=str(getattr(bootp, "yiaddr", "") or "") or None,
        requested_ip=str(options.get("requested_addr")) if options.get("requested_addr") else None,
        lease_time=_lease_seconds(options.get("lease_time")),
        options_json=json.dumps(options, default=str, sort_keys=True),
        observed_at=datetime.utcnow(),
    )


def _store_packet(db: Session, packet: Any) -> bool:
    row = _packet_to_observation(packet)
    if not row:
        return False
    db.add(row)
    return True


def capture_dhcp_observations(timeout_seconds: int = 20, packet_limit: int = 50) -> int:
    """Capture visible DHCP server replies for a short window."""
    global _capture_running
    if _capture_running:
        return 0
    _capture_running = True
    stored = 0
    db = SessionLocal()
    try:
        try:
            from scapy.sendrecv import sniff
        except Exception as exc:
            logger.warning("DHCP monitor unavailable: scapy sniff could not be loaded: %s", exc)
            return 0

        def handle(packet: Any) -> None:
            nonlocal stored
            if _store_packet(db, packet):
                stored += 1

        sniff(
            filter="udp and src port 67 and dst port 68",
            prn=handle,
            timeout=max(3, min(120, timeout_seconds)),
            count=max(1, min(500, packet_limit)),
            store=False,
        )
        db.commit()
        return stored
    except PermissionError as exc:
        logger.warning("DHCP monitor needs packet capture permissions: %s", exc)
        db.rollback()
        return 0
    except Exception as exc:
        logger.warning("DHCP capture failed: %s", exc)
        db.rollback()
        return 0
    finally:
        db.close()
        _capture_running = False


def observation_to_response(row: DhcpObservation) -> dict[str, Any]:
    try:
        options = json.loads(row.options_json or "{}")
    except Exception:
        options = {}
    return {
        "id": row.id,
        "message_type": row.message_type,
        "server_ip": row.server_ip,
        "server_mac": row.server_mac,
        "client_mac": row.client_mac,
        "client_hostname": row.client_hostname,
        "offered_ip": row.offered_ip,
        "requested_ip": row.requested_ip,
        "lease_time": row.lease_time,
        "options": options,
        "observed_at": row.observed_at,
    }
