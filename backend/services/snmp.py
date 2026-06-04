from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import Device, SnmpInterface, SnmpMacTableEntry, SnmpProfile, SnmpSwitch
from .mac_vendor import normalize_mac

OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
OID_IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
OID_IF_SPEED = "1.3.6.1.2.1.2.2.1.5"
OID_IF_PHYS_ADDRESS = "1.3.6.1.2.1.2.2.1.6"
OID_IF_ADMIN_STATUS = "1.3.6.1.2.1.2.2.1.7"
OID_IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
OID_IF_IN_UCAST_PKTS = "1.3.6.1.2.1.2.2.1.11"
OID_IF_IN_NUCAST_PKTS = "1.3.6.1.2.1.2.2.1.12"
OID_IF_IN_DISCARDS = "1.3.6.1.2.1.2.2.1.13"
OID_IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"
OID_IF_IN_UNKNOWN_PROTOS = "1.3.6.1.2.1.2.2.1.15"
OID_IF_OUT_UCAST_PKTS = "1.3.6.1.2.1.2.2.1.17"
OID_IF_OUT_NUCAST_PKTS = "1.3.6.1.2.1.2.2.1.18"
OID_IF_OUT_DISCARDS = "1.3.6.1.2.1.2.2.1.19"
OID_IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.20"
OID_IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
OID_IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
OID_DOT3_STATS_ALIGNMENT_ERRORS = "1.3.6.1.2.1.10.7.2.1.2"
OID_DOT3_STATS_FCS_ERRORS = "1.3.6.1.2.1.10.7.2.1.3"
OID_DOT3_STATS_SINGLE_COLLISIONS = "1.3.6.1.2.1.10.7.2.1.4"
OID_DOT3_STATS_MULTIPLE_COLLISIONS = "1.3.6.1.2.1.10.7.2.1.5"
OID_DOT3_STATS_LATE_COLLISIONS = "1.3.6.1.2.1.10.7.2.1.8"
OID_DOT3_STATS_EXCESSIVE_COLLISIONS = "1.3.6.1.2.1.10.7.2.1.9"
OID_DOT3_STATS_FRAME_TOO_LONGS = "1.3.6.1.2.1.10.7.2.1.13"
OID_DOT1D_TP_FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"
OID_DOT1D_BASE_PORT_IF_INDEX = "1.3.6.1.2.1.17.1.4.1.2"
OID_DOT1Q_TP_FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2"
OID_DOT1Q_BASE_PORT_IF_INDEX = "1.3.6.1.2.1.17.7.1.4.5.1.1"

STATUS_LABELS = {
    "1": "up",
    "2": "down",
    "3": "testing",
    "4": "unknown",
    "5": "dormant",
    "6": "notPresent",
    "7": "lowerLayerDown",
}


@dataclass
class PollResult:
    interfaces: int
    mac_entries: int
    diagnostics: str = ""


@dataclass
class PollStep:
    label: str
    oid: str
    status: str
    rows: int = 0
    error: str = ""


@dataclass(frozen=True)
class VendorSupport:
    key: str
    label: str
    notes: str


VENDOR_SUPPORT = {
    "cisco": VendorSupport(
        key="cisco",
        label="Cisco",
        notes="Cisco switching platforms normally expose IF-MIB plus BRIDGE-MIB or Q-BRIDGE-MIB.",
    ),
    "sophos": VendorSupport(
        key="sophos",
        label="Sophos",
        notes="Sophos firewall/router platforms usually expose IF-MIB; MAC-table endpoint mapping depends on bridge support.",
    ),
    "unifi": VendorSupport(
        key="unifi",
        label="UniFi / Ubiquiti",
        notes="UniFi switches normally expose IF-MIB plus bridge tables; UniFi gateways may expose interfaces but no switch MAC table.",
    ),
    "generic": VendorSupport(
        key="generic",
        label="Generic SNMP",
        notes="Generic SNMP device using standard IF-MIB, BRIDGE-MIB and Q-BRIDGE-MIB where available.",
    ),
}


def detect_vendor(sys_descr: str = "", sys_object_id: str = "") -> VendorSupport:
    text = f"{sys_descr} {sys_object_id}".lower()
    if "1.3.6.1.4.1.9." in sys_object_id or "cisco" in text:
        return VENDOR_SUPPORT["cisco"]
    if "1.3.6.1.4.1.41112." in sys_object_id or "ubiquiti" in text or "unifi" in text:
        return VENDOR_SUPPORT["unifi"]
    if "1.3.6.1.4.1.2604." in sys_object_id or "sophos" in text or "sfos" in text or "astaro" in text:
        return VENDOR_SUPPORT["sophos"]
    return VENDOR_SUPPORT["generic"]


def _clean_snmp_value(raw: str) -> str:
    value = raw.strip()
    for prefix in ("STRING:", "INTEGER:", "Gauge32:", "Counter32:", "Counter64:", "Timeticks:", "OID:"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value.strip()


def _snmp_command(profile: SnmpProfile, host: str, oid: str, port: int = 161) -> list[str]:
    target = f"{host}:{port}"
    base = [
        "snmpwalk",
        "-On",
        "-t",
        "2",
        "-r",
        "1",
    ]
    if profile.version in {"1", "2c"}:
        return [
            *base,
            f"-v{profile.version}",
            "-c",
            profile.community or "",
            target,
            oid,
        ]
    if profile.version == "3":
        cmd = [
            *base,
            "-v3",
            "-l",
            profile.security_level or "noAuthNoPriv",
            "-u",
            profile.username or "",
        ]
        if profile.security_level in {"authNoPriv", "authPriv"}:
            cmd.extend(["-a", profile.auth_protocol or "SHA", "-A", profile.auth_password or ""])
        if profile.security_level == "authPriv":
            cmd.extend(["-x", profile.privacy_protocol or "AES", "-X", profile.privacy_password or ""])
        cmd.extend([
            target,
            oid,
        ])
        return cmd
    raise RuntimeError(f"Unsupported SNMP version: {profile.version}")


def _format_snmp_error(host: str, port: int, detail: str = "") -> str:
    message = detail.strip()
    lower = message.lower()
    if "timeout" in lower or "no response" in lower:
        return (
            f"SNMP timeout: no response from {host}:{port}. "
            "Check that SNMP is enabled on the target, UDP/161 is reachable from the LanLens container, "
            "and the selected SNMP version/community or SNMPv3 credentials match the device."
        )
    if "authorizationerror" in lower or "authentication failure" in lower or "unknown user name" in lower:
        return (
            f"SNMP authentication failed for {host}:{port}. "
            "Check the selected profile, community string, SNMPv3 user, auth protocol and privacy settings."
        )
    return message or f"snmpwalk failed for {host}:{port}"


def _snmpwalk(profile: SnmpProfile, host: str, oid: str, port: int = 161, timeout: int = 8) -> dict[str, str]:
    cmd = _snmp_command(
        profile,
        host,
        oid,
        port,
    )
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError("snmpwalk is not installed in the LanLens container") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(_format_snmp_error(host, port, "Timeout")) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(_format_snmp_error(host, port, detail or f"snmpwalk failed with exit code {completed.returncode}"))

    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if " = " not in line:
            continue
        left, right = line.split(" = ", 1)
        suffix = left.strip().removeprefix(f".{oid}.").removeprefix(f"{oid}.")
        values[suffix] = _clean_snmp_value(right)
    return values


def _optional_snmpwalk(profile: SnmpProfile, host: str, oid: str, port: int = 161) -> dict[str, str]:
    try:
        return _snmpwalk(profile, host, oid, port)
    except RuntimeError:
        return {}


def _poll_target_summary(switch: SnmpSwitch, profile: SnmpProfile, port: int) -> str:
    profile_bits = [
        f"target={switch.host}:{port}",
        f"switch={switch.name}",
        f"profile={profile.name or profile.id}",
        f"version={profile.version}",
    ]
    if profile.version == "3":
        profile_bits.append(f"security={profile.security_level or 'noAuthNoPriv'}")
        if profile.security_level in {"authNoPriv", "authPriv"}:
            profile_bits.append(f"auth={profile.auth_protocol or 'SHA'}")
        if profile.security_level == "authPriv":
            profile_bits.append(f"privacy={profile.privacy_protocol or 'AES'}")
    return "SNMP poll target: " + ", ".join(profile_bits)


def _format_poll_steps(target: str, steps: list[PollStep]) -> str:
    lines = [target, "SNMP poll steps:"]
    for step in steps:
        if step.status == "ok":
            lines.append(f"- OK: {step.label} ({step.oid}) returned {step.rows} rows")
        elif step.status == "skipped":
            lines.append(f"- SKIPPED: {step.label} ({step.oid})")
        else:
            suffix = f": {step.error}" if step.error else ""
            lines.append(f"- FAILED: {step.label} ({step.oid}){suffix}")
    return "\n".join(lines)


def _snmpwalk_step(
    profile: SnmpProfile,
    switch: SnmpSwitch,
    oid: str,
    port: int,
    label: str,
    steps: list[PollStep],
    required: bool = True,
) -> dict[str, str]:
    try:
        values = _snmpwalk(profile, switch.host, oid, port)
        steps.append(PollStep(label=label, oid=oid, status="ok", rows=len(values)))
        return values
    except RuntimeError as exc:
        steps.append(PollStep(label=label, oid=oid, status="failed", error=str(exc)))
        if required:
            raise
        return {}


def _first_value(values: dict[str, str]) -> str:
    return next(iter(values.values()), "")


def _snmpget(profile: SnmpProfile, host: str, oid: str, port: int = 161) -> str:
    values = _snmpwalk(profile, host, oid, port=port)
    return next(iter(values.values()), "")


def _parse_mac_suffix(suffix: str) -> Optional[str]:
    parts = suffix.split(".")[-6:]
    if len(parts) != 6:
        return None
    try:
        return normalize_mac(":".join(f"{int(part):02x}" for part in parts))
    except ValueError:
        return None


def _parse_q_bridge_suffix(suffix: str) -> tuple[Optional[str], Optional[str]]:
    parts = suffix.split(".")
    if len(parts) < 7:
        return None, None
    vlan = parts[-7]
    mac = _parse_mac_suffix(".".join(parts[-6:]))
    return (vlan if vlan.isdigit() else None), mac


def _parse_bridge_port_map(raw: dict[str, str]) -> dict[int, int]:
    port_map: dict[int, int] = {}
    for suffix, value in raw.items():
        if not suffix.isdigit():
            continue
        match = re.search(r"\d+", value)
        if match:
            port_map[int(suffix)] = int(match.group(0))
    return port_map


def _parse_counter(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    match = re.search(r"\d+", raw)
    return int(match.group(0)) if match else None


def _counter_value(values: dict[str, str], if_index: int) -> Optional[int]:
    return _parse_counter(values.get(str(if_index)))


def _counter_sum(values: dict[str, dict[str, str]], keys: list[str], if_index: int) -> Optional[int]:
    total = 0
    found = False
    for key in keys:
        value = _counter_value(values.get(key, {}), if_index)
        if value is not None:
            total += value
            found = True
    return total if found else None


def _merge_port_maps(*maps: dict[int, int]) -> dict[int, int]:
    merged: dict[int, int] = {}
    for port_map in maps:
        merged.update(port_map)
    return merged


def _upsert_interface(db: Session, switch: SnmpSwitch, if_index: int, values: dict[str, dict[str, str]], now: datetime) -> None:
    row = (
        db.query(SnmpInterface)
        .filter(SnmpInterface.switch_id == switch.id, SnmpInterface.if_index == if_index)
        .first()
    )
    if row is None:
        row = SnmpInterface(switch_id=switch.id, if_index=if_index)
        db.add(row)
    row.name = values["names"].get(str(if_index)) or row.name
    row.description = values["descr"].get(str(if_index)) or row.description
    row.alias = values["alias"].get(str(if_index)) or row.alias
    row.if_type = _counter_value(values["type"], if_index) or row.if_type
    row.admin_status = STATUS_LABELS.get(values["admin"].get(str(if_index), ""), values["admin"].get(str(if_index)))
    row.oper_status = STATUS_LABELS.get(values["oper"].get(str(if_index), ""), values["oper"].get(str(if_index)))
    speed = values["speed"].get(str(if_index))
    row.speed_bps = int(speed) if speed and speed.isdigit() else row.speed_bps
    row.phys_address = values["phys"].get(str(if_index)) or row.phys_address
    row.in_unicast_packets = _counter_value(values["in_ucast"], if_index)
    row.in_non_unicast_packets = _counter_value(values["in_nucast"], if_index)
    row.out_unicast_packets = _counter_value(values["out_ucast"], if_index)
    row.out_non_unicast_packets = _counter_value(values["out_nucast"], if_index)
    row.in_discards = _counter_value(values["in_discards"], if_index)
    row.out_discards = _counter_value(values["out_discards"], if_index)
    row.in_errors = _counter_value(values["in_errors"], if_index)
    row.out_errors = _counter_value(values["out_errors"], if_index)
    row.unknown_protocols = _counter_value(values["unknown_protocols"], if_index)
    row.crc_errors = _counter_sum(values, ["dot3_alignment_errors", "dot3_fcs_errors"], if_index)
    row.collision_errors = _counter_sum(
        values,
        ["dot3_single_collisions", "dot3_multiple_collisions", "dot3_late_collisions", "dot3_excessive_collisions"],
        if_index,
    )
    row.fragment_errors = _counter_value(values["dot3_frame_too_longs"], if_index)
    row.last_seen_at = now


def _upsert_mac_entry(
    db: Session,
    switch: SnmpSwitch,
    mac: str,
    if_index: Optional[int],
    now: datetime,
    vlan: Optional[str] = None,
) -> None:
    query = db.query(SnmpMacTableEntry).filter(
        SnmpMacTableEntry.switch_id == switch.id,
        SnmpMacTableEntry.mac_address == mac,
    )
    query = query.filter(SnmpMacTableEntry.vlan == vlan) if vlan else query.filter(SnmpMacTableEntry.vlan.is_(None))
    row = query.first()
    if row is None:
        row = SnmpMacTableEntry(switch_id=switch.id, mac_address=mac, vlan=vlan, learned_at=now)
        db.add(row)
    row.if_index = if_index
    row.last_seen_at = now


def _target_identity(switch: SnmpSwitch) -> dict[str, Any]:
    return {
        "switch_id": switch.id,
        "switch_device_id": switch.device_id,
        "switch_name": switch.name or "",
        "switch_host": switch.host or "",
        "if_index": None,
        "interface_name": "",
        "interface_alias": "",
        "vlan": "",
        "last_seen_at": switch.last_poll_at.isoformat() if switch.last_poll_at else "",
        "confidence": "target",
    }


def _interface_stats(iface: Optional[SnmpInterface]) -> dict[str, Any]:
    if not iface:
        return {}
    return {
        "interface_speed_bps": iface.speed_bps,
        "interface_admin_status": iface.admin_status or "",
        "interface_oper_status": iface.oper_status or "",
        "interface_in_unicast_packets": iface.in_unicast_packets,
        "interface_in_non_unicast_packets": iface.in_non_unicast_packets,
        "interface_out_unicast_packets": iface.out_unicast_packets,
        "interface_out_non_unicast_packets": iface.out_non_unicast_packets,
        "interface_in_discards": iface.in_discards,
        "interface_out_discards": iface.out_discards,
        "interface_in_errors": iface.in_errors,
        "interface_out_errors": iface.out_errors,
        "interface_unknown_protocols": iface.unknown_protocols,
        "interface_crc_errors": iface.crc_errors,
        "interface_collision_errors": iface.collision_errors,
        "interface_fragment_errors": iface.fragment_errors,
    }


def _switch_like_device_class(vendor: VendorSupport, switch: SnmpSwitch, interface_count: int) -> Optional[str]:
    text = " ".join(
        value
        for value in [
            switch.name or "",
            switch.sys_name or "",
            switch.sys_descr or "",
            switch.sys_object_id or "",
        ]
        if value
    ).lower()
    if not text or interface_count <= 0:
        return None
    if re.search(r"\b(switch|catalyst|nexus|cbs\d|sg\d|sf\d|small business)\b", text):
        return "Switch"
    if vendor.key == "unifi" and "usw" in text:
        return "Switch"
    return None


def _linked_device_for_target(db: Session, switch: SnmpSwitch) -> Optional[Device]:
    if switch.device_id:
        return db.query(Device).filter(Device.id == switch.device_id).first()
    if switch.host:
        return db.query(Device).filter(Device.ip_address == switch.host).first()
    return None


def _apply_target_identity_to_device(db: Session, switch: SnmpSwitch, vendor: VendorSupport, interface_count: int) -> None:
    device = _linked_device_for_target(db, switch)
    if not device:
        return
    inferred_class = _switch_like_device_class(vendor, switch, interface_count)
    current_class = (device.device_class or "").strip().lower()
    if inferred_class and current_class in {"", "unknown"}:
        device.device_class = inferred_class
    if vendor.key != "generic" and not (device.vendor or "").strip():
        device.vendor = vendor.label


def _linked_target_for_device(db: Session, device: Device) -> Optional[SnmpSwitch]:
    filters = []
    if device.id is not None:
        filters.append(SnmpSwitch.device_id == device.id)
    if device.ip_address:
        filters.append(SnmpSwitch.host == device.ip_address)
    if not filters:
        return None
    return (
        db.query(SnmpSwitch)
        .filter(or_(*filters))
        .order_by(SnmpSwitch.device_id.is_(None).asc(), SnmpSwitch.last_poll_at.desc().nullslast(), SnmpSwitch.name.asc())
        .first()
    )


def _poll_mac_tables(
    db: Session,
    switch: SnmpSwitch,
    profile: SnmpProfile,
    port: int,
    now: datetime,
    steps: list[PollStep],
) -> int:
    bridge_ports = _merge_port_maps(
        _parse_bridge_port_map(_snmpwalk_step(profile, switch, OID_DOT1D_BASE_PORT_IF_INDEX, port, "BRIDGE-MIB base-port map", steps, required=False)),
        _parse_bridge_port_map(_snmpwalk_step(profile, switch, OID_DOT1Q_BASE_PORT_IF_INDEX, port, "Q-BRIDGE-MIB VLAN base-port map", steps, required=False)),
    )
    mac_count = 0

    for suffix, bridge_port_value in _snmpwalk_step(profile, switch, OID_DOT1D_TP_FDB_PORT, port, "BRIDGE-MIB MAC forwarding table", steps, required=False).items():
        mac = _parse_mac_suffix(suffix)
        bridge_match = re.search(r"\d+", bridge_port_value)
        if not mac or not bridge_match:
            continue
        if_index = bridge_ports.get(int(bridge_match.group(0)))
        _upsert_mac_entry(db, switch, mac, if_index, now)
        mac_count += 1

    for suffix, bridge_port_value in _snmpwalk_step(profile, switch, OID_DOT1Q_TP_FDB_PORT, port, "Q-BRIDGE-MIB VLAN MAC forwarding table", steps, required=False).items():
        vlan, mac = _parse_q_bridge_suffix(suffix)
        bridge_match = re.search(r"\d+", bridge_port_value)
        if not mac or not bridge_match:
            continue
        if_index = bridge_ports.get(int(bridge_match.group(0)))
        _upsert_mac_entry(db, switch, mac, if_index, now, vlan=vlan)
        mac_count += 1

    return mac_count


def poll_switch(db: Session, switch: SnmpSwitch) -> PollResult:
    if not switch.profile:
        raise RuntimeError("SNMP switch has no profile assigned")
    if switch.profile.version not in {"1", "2c", "3"}:
        raise RuntimeError(f"Unsupported SNMP version: {switch.profile.version}")

    profile = switch.profile
    port = switch.profile.port or 161
    now = datetime.utcnow()
    steps: list[PollStep] = []
    target_summary = _poll_target_summary(switch, profile, port)

    system_values = {
        "descr": _snmpwalk_step(profile, switch, OID_SYS_DESCR, port, "System description", steps, required=False),
        "object_id": _snmpwalk_step(profile, switch, OID_SYS_OBJECT_ID, port, "System object ID", steps, required=False),
        "name": _snmpwalk_step(profile, switch, OID_SYS_NAME, port, "System name", steps, required=False),
    }
    if not any(system_values.values()):
        diagnostics = _format_poll_steps(target_summary, steps)
        raise RuntimeError(f"SNMP target did not return any system identity values.\n\n{diagnostics}")
    switch.sys_descr = _first_value(system_values["descr"]) or switch.sys_descr
    switch.sys_object_id = _first_value(system_values["object_id"]) or switch.sys_object_id
    switch.sys_name = _first_value(system_values["name"]) or switch.sys_name

    vendor = detect_vendor(switch.sys_descr or "", switch.sys_object_id or "")

    values = {
        "descr": _snmpwalk_step(profile, switch, OID_IF_DESCR, port, "IF-MIB interface descriptions", steps, required=False),
        "type": _snmpwalk_step(profile, switch, OID_IF_TYPE, port, "IF-MIB interface types", steps, required=False),
        "speed": _snmpwalk_step(profile, switch, OID_IF_SPEED, port, "IF-MIB interface speeds", steps, required=False),
        "phys": _snmpwalk_step(profile, switch, OID_IF_PHYS_ADDRESS, port, "IF-MIB interface MAC addresses", steps, required=False),
        "admin": _snmpwalk_step(profile, switch, OID_IF_ADMIN_STATUS, port, "IF-MIB admin status", steps, required=False),
        "oper": _snmpwalk_step(profile, switch, OID_IF_OPER_STATUS, port, "IF-MIB operational status", steps, required=False),
        "in_ucast": _snmpwalk_step(profile, switch, OID_IF_IN_UCAST_PKTS, port, "IF-MIB inbound unicast packets", steps, required=False),
        "in_nucast": _snmpwalk_step(profile, switch, OID_IF_IN_NUCAST_PKTS, port, "IF-MIB inbound non-unicast packets", steps, required=False),
        "in_discards": _snmpwalk_step(profile, switch, OID_IF_IN_DISCARDS, port, "IF-MIB inbound discards", steps, required=False),
        "in_errors": _snmpwalk_step(profile, switch, OID_IF_IN_ERRORS, port, "IF-MIB inbound errors", steps, required=False),
        "unknown_protocols": _snmpwalk_step(profile, switch, OID_IF_IN_UNKNOWN_PROTOS, port, "IF-MIB unknown protocols", steps, required=False),
        "out_ucast": _snmpwalk_step(profile, switch, OID_IF_OUT_UCAST_PKTS, port, "IF-MIB outbound unicast packets", steps, required=False),
        "out_nucast": _snmpwalk_step(profile, switch, OID_IF_OUT_NUCAST_PKTS, port, "IF-MIB outbound non-unicast packets", steps, required=False),
        "out_discards": _snmpwalk_step(profile, switch, OID_IF_OUT_DISCARDS, port, "IF-MIB outbound discards", steps, required=False),
        "out_errors": _snmpwalk_step(profile, switch, OID_IF_OUT_ERRORS, port, "IF-MIB outbound errors", steps, required=False),
        "names": _snmpwalk_step(profile, switch, OID_IF_NAME, port, "IF-MIB interface names", steps, required=False),
        "alias": _snmpwalk_step(profile, switch, OID_IF_ALIAS, port, "IF-MIB interface aliases", steps, required=False),
        "dot3_alignment_errors": _snmpwalk_step(profile, switch, OID_DOT3_STATS_ALIGNMENT_ERRORS, port, "EtherLike-MIB alignment errors", steps, required=False),
        "dot3_fcs_errors": _snmpwalk_step(profile, switch, OID_DOT3_STATS_FCS_ERRORS, port, "EtherLike-MIB FCS/CRC errors", steps, required=False),
        "dot3_single_collisions": _snmpwalk_step(profile, switch, OID_DOT3_STATS_SINGLE_COLLISIONS, port, "EtherLike-MIB single collision frames", steps, required=False),
        "dot3_multiple_collisions": _snmpwalk_step(profile, switch, OID_DOT3_STATS_MULTIPLE_COLLISIONS, port, "EtherLike-MIB multiple collision frames", steps, required=False),
        "dot3_late_collisions": _snmpwalk_step(profile, switch, OID_DOT3_STATS_LATE_COLLISIONS, port, "EtherLike-MIB late collisions", steps, required=False),
        "dot3_excessive_collisions": _snmpwalk_step(profile, switch, OID_DOT3_STATS_EXCESSIVE_COLLISIONS, port, "EtherLike-MIB excessive collisions", steps, required=False),
        "dot3_frame_too_longs": _snmpwalk_step(profile, switch, OID_DOT3_STATS_FRAME_TOO_LONGS, port, "EtherLike-MIB frame-too-long fragments", steps, required=False),
    }

    indexes = sorted({int(key) for group in values.values() for key in group.keys() if key.isdigit()})
    for if_index in indexes:
        _upsert_interface(db, switch, if_index, values, now)

    mac_count = _poll_mac_tables(db, switch, profile, port, now, steps)
    diagnostics = _format_poll_steps(target_summary, steps)

    switch.last_poll_at = now
    switch.last_error = None
    switch.last_diagnostics = diagnostics
    _apply_target_identity_to_device(db, switch, vendor, len(indexes))
    switch.updated_at = now
    return PollResult(interfaces=len(indexes), mac_entries=mac_count, diagnostics=diagnostics)


def identity_for_device(db: Session, device: Device) -> Optional[dict[str, Any]]:
    linked_target = _linked_target_for_device(db, device)
    if not device.mac_address or device.mac_address.startswith("ip:"):
        return _target_identity(linked_target) if linked_target else None
    mac = normalize_mac(device.mac_address)
    entry = (
        db.query(SnmpMacTableEntry)
        .filter(SnmpMacTableEntry.mac_address == mac)
        .order_by(SnmpMacTableEntry.last_seen_at.desc())
        .first()
    )
    if not entry:
        return _target_identity(linked_target) if linked_target else None
    iface = None
    if entry.if_index is not None:
        iface = (
            db.query(SnmpInterface)
            .filter(SnmpInterface.switch_id == entry.switch_id, SnmpInterface.if_index == entry.if_index)
            .first()
        )
    switch = db.query(SnmpSwitch).filter(SnmpSwitch.id == entry.switch_id).first()
    identity = {
        "switch_id": entry.switch_id,
        "switch_device_id": switch.device_id if switch else None,
        "switch_name": (switch.name if switch else "") or "",
        "switch_host": (switch.host if switch else "") or "",
        "if_index": entry.if_index,
        "interface_name": ((iface.name or iface.description) if iface else "") or "",
        "interface_alias": (iface.alias if iface else "") or "",
        "vlan": entry.vlan or "",
        "last_seen_at": entry.last_seen_at.isoformat() if entry.last_seen_at else "",
        "confidence": "high" if entry.if_index else "medium",
    }
    identity.update(_interface_stats(iface))
    return identity


def bulk_identities_for_devices(db: Session, devices: list[Device]) -> dict[int, dict[str, Any]]:
    """Return a {device_id: identity} map for all devices using bulk DB queries.

    This avoids the N+1 pattern of calling identity_for_device() per device.
    Devices without a MAC or with an ip:-prefixed pseudo-MAC are skipped.
    """
    mac_to_device_id: dict[str, int] = {}
    for device in devices:
        if not device.mac_address or device.mac_address.startswith("ip:"):
            continue
        mac_to_device_id[normalize_mac(device.mac_address)] = device.id

    if not mac_to_device_id:
        result: dict[int, dict[str, Any]] = {}
        _add_linked_target_identities(db, devices, result)
        return result

    all_macs = list(mac_to_device_id.keys())
    all_entries = (
        db.query(SnmpMacTableEntry)
        .filter(SnmpMacTableEntry.mac_address.in_(all_macs))
        .order_by(SnmpMacTableEntry.last_seen_at.desc())
        .all()
    )
    # Keep only the latest entry per MAC.
    latest_by_mac: dict[str, SnmpMacTableEntry] = {}
    for entry in all_entries:
        if entry.mac_address not in latest_by_mac:
            latest_by_mac[entry.mac_address] = entry

    if not latest_by_mac:
        return {}

    switch_ids = {e.switch_id for e in latest_by_mac.values()}
    switches: dict[int, SnmpSwitch] = {
        s.id: s for s in db.query(SnmpSwitch).filter(SnmpSwitch.id.in_(switch_ids)).all()
    }

    ifaces: dict[tuple[int, int], SnmpInterface] = {}
    iface_switch_ids = {e.switch_id for e in latest_by_mac.values() if e.if_index is not None}
    if iface_switch_ids:
        for iface in db.query(SnmpInterface).filter(SnmpInterface.switch_id.in_(iface_switch_ids)).all():
            ifaces[(iface.switch_id, iface.if_index)] = iface

    result: dict[int, dict[str, Any]] = {}
    for mac, entry in latest_by_mac.items():
        device_id = mac_to_device_id.get(mac)
        if device_id is None:
            continue
        switch = switches.get(entry.switch_id)
        iface = ifaces.get((entry.switch_id, entry.if_index)) if entry.if_index is not None else None
        identity = {
            "switch_id": entry.switch_id,
            "switch_device_id": switch.device_id if switch else None,
            "switch_name": (switch.name if switch else "") or "",
            "switch_host": (switch.host if switch else "") or "",
            "if_index": entry.if_index,
            "interface_name": ((iface.name or iface.description) if iface else "") or "",
            "interface_alias": (iface.alias if iface else "") or "",
            "vlan": entry.vlan or "",
            "last_seen_at": entry.last_seen_at.isoformat() if entry.last_seen_at else "",
            "confidence": "high" if entry.if_index else "medium",
        }
        identity.update(_interface_stats(iface))
        result[device_id] = identity
    _add_linked_target_identities(db, devices, result)
    return result


def _add_linked_target_identities(db: Session, devices: list[Device], result: dict[int, dict[str, Any]]) -> None:
    remaining_devices = [device for device in devices if device.id not in result]
    if not remaining_devices:
        return

    device_ids = [device.id for device in remaining_devices]
    ip_to_device_id = {device.ip_address: device.id for device in remaining_devices if device.ip_address}
    filters = [SnmpSwitch.device_id.in_(device_ids)]
    if ip_to_device_id:
        filters.append(SnmpSwitch.host.in_(list(ip_to_device_id.keys())))

    switches = (
        db.query(SnmpSwitch)
        .filter(or_(*filters))
        .order_by(SnmpSwitch.device_id.is_(None).asc(), SnmpSwitch.last_poll_at.desc().nullslast(), SnmpSwitch.name.asc())
        .all()
    )
    for switch in switches:
        device_id = switch.device_id or ip_to_device_id.get(switch.host)
        if device_id is not None and device_id not in result:
            result[device_id] = _target_identity(switch)
