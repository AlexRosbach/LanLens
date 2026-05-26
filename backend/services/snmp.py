from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Device, SnmpInterface, SnmpMacTableEntry, SnmpProfile, SnmpSwitch
from .mac_vendor import normalize_mac

OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
OID_IF_SPEED = "1.3.6.1.2.1.2.2.1.5"
OID_IF_PHYS_ADDRESS = "1.3.6.1.2.1.2.2.1.6"
OID_IF_ADMIN_STATUS = "1.3.6.1.2.1.2.2.1.7"
OID_IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
OID_IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
OID_IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
OID_DOT1D_TP_FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"
OID_DOT1D_BASE_PORT_IF_INDEX = "1.3.6.1.2.1.17.1.4.1.2"

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
        raise RuntimeError(f"SNMP polling timed out for {host}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail or f"snmpwalk failed with exit code {completed.returncode}")

    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if " = " not in line:
            continue
        left, right = line.split(" = ", 1)
        suffix = left.strip().removeprefix(f".{oid}.").removeprefix(f"{oid}.")
        values[suffix] = _clean_snmp_value(right)
    return values


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


def _parse_bridge_port_map(raw: dict[str, str]) -> dict[int, int]:
    port_map: dict[int, int] = {}
    for suffix, value in raw.items():
        if not suffix.isdigit():
            continue
        match = re.search(r"\d+", value)
        if match:
            port_map[int(suffix)] = int(match.group(0))
    return port_map


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
    row.admin_status = STATUS_LABELS.get(values["admin"].get(str(if_index), ""), values["admin"].get(str(if_index)))
    row.oper_status = STATUS_LABELS.get(values["oper"].get(str(if_index), ""), values["oper"].get(str(if_index)))
    speed = values["speed"].get(str(if_index))
    row.speed_bps = int(speed) if speed and speed.isdigit() else row.speed_bps
    row.phys_address = values["phys"].get(str(if_index)) or row.phys_address
    row.last_seen_at = now


def _upsert_mac_entry(db: Session, switch: SnmpSwitch, mac: str, if_index: Optional[int], now: datetime) -> None:
    row = (
        db.query(SnmpMacTableEntry)
        .filter(
            SnmpMacTableEntry.switch_id == switch.id,
            SnmpMacTableEntry.mac_address == mac,
            SnmpMacTableEntry.vlan.is_(None),
        )
        .first()
    )
    if row is None:
        row = SnmpMacTableEntry(switch_id=switch.id, mac_address=mac, vlan=None, learned_at=now)
        db.add(row)
    row.if_index = if_index
    row.last_seen_at = now


def poll_switch(db: Session, switch: SnmpSwitch) -> PollResult:
    if not switch.profile:
        raise RuntimeError("SNMP switch has no profile assigned")
    if switch.profile.version not in {"1", "2c", "3"}:
        raise RuntimeError(f"Unsupported SNMP version: {switch.profile.version}")

    profile = switch.profile
    port = switch.profile.port or 161
    now = datetime.utcnow()

    switch.sys_descr = _snmpget(profile, switch.host, OID_SYS_DESCR, port)
    switch.sys_object_id = _snmpget(profile, switch.host, OID_SYS_OBJECT_ID, port)
    switch.sys_name = _snmpget(profile, switch.host, OID_SYS_NAME, port)

    values = {
        "descr": _snmpwalk(profile, switch.host, OID_IF_DESCR, port),
        "speed": _snmpwalk(profile, switch.host, OID_IF_SPEED, port),
        "phys": _snmpwalk(profile, switch.host, OID_IF_PHYS_ADDRESS, port),
        "admin": _snmpwalk(profile, switch.host, OID_IF_ADMIN_STATUS, port),
        "oper": _snmpwalk(profile, switch.host, OID_IF_OPER_STATUS, port),
        "names": _snmpwalk(profile, switch.host, OID_IF_NAME, port),
        "alias": _snmpwalk(profile, switch.host, OID_IF_ALIAS, port),
    }
    indexes = sorted({int(key) for group in values.values() for key in group.keys() if key.isdigit()})
    for if_index in indexes:
        _upsert_interface(db, switch, if_index, values, now)

    bridge_ports = _parse_bridge_port_map(_snmpwalk(profile, switch.host, OID_DOT1D_BASE_PORT_IF_INDEX, port))
    mac_raw = _snmpwalk(profile, switch.host, OID_DOT1D_TP_FDB_PORT, port)
    mac_count = 0
    for suffix, bridge_port_value in mac_raw.items():
        mac = _parse_mac_suffix(suffix)
        bridge_match = re.search(r"\d+", bridge_port_value)
        if not mac or not bridge_match:
            continue
        if_index = bridge_ports.get(int(bridge_match.group(0)))
        _upsert_mac_entry(db, switch, mac, if_index, now)
        mac_count += 1

    switch.last_poll_at = now
    switch.last_error = None
    switch.updated_at = now
    return PollResult(interfaces=len(indexes), mac_entries=mac_count)


def identity_for_device(db: Session, device: Device) -> Optional[dict[str, Any]]:
    if not device.mac_address or device.mac_address.startswith("ip:"):
        return None
    mac = normalize_mac(device.mac_address)
    entry = (
        db.query(SnmpMacTableEntry)
        .filter(SnmpMacTableEntry.mac_address == mac)
        .order_by(SnmpMacTableEntry.last_seen_at.desc())
        .first()
    )
    if not entry:
        return None
    iface = None
    if entry.if_index is not None:
        iface = (
            db.query(SnmpInterface)
            .filter(SnmpInterface.switch_id == entry.switch_id, SnmpInterface.if_index == entry.if_index)
            .first()
        )
    switch = db.query(SnmpSwitch).filter(SnmpSwitch.id == entry.switch_id).first()
    return {
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
        return {}

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
        result[device_id] = {
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
    return result
