from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, SnmpInterface, SnmpMacTableEntry, SnmpProfile, SnmpSwitch, User
from ..schemas import MessageResponse
from ..services.settings_helpers import is_advanced_view_enabled
from ..services.snmp import detect_vendor, identity_for_device, poll_switch

router = APIRouter(prefix="/api/snmp", tags=["snmp"])

MASK = "••••••••"
SNMP_VERSIONS = {"1", "2c", "3"}
SNMP_V3_SECURITY_LEVELS = {"noAuthNoPriv", "authNoPriv", "authPriv"}
SNMP_AUTH_PROTOCOLS = {"MD5", "SHA"}
SNMP_PRIVACY_PROTOCOLS = {"DES", "AES"}


def _require_snmp_enabled(db: Session) -> None:
    if not is_advanced_view_enabled(db):
        raise HTTPException(status_code=403, detail="SNMP is disabled")


class SnmpProfilePayload(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    version: str = "2c"
    community: str = Field(default="", max_length=255)
    username: str = Field(default="", max_length=255)
    security_level: str = "noAuthNoPriv"
    auth_protocol: str = Field(default="SHA", max_length=32)
    auth_password: str = Field(default="", max_length=255)
    privacy_protocol: str = Field(default="AES", max_length=32)
    privacy_password: str = Field(default="", max_length=255)
    port: int = Field(default=161, ge=1, le=65535)
    enabled: bool = True


class SnmpSwitchPayload(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    host: str = Field(..., min_length=1, max_length=255)
    profile_id: int
    device_id: Optional[int] = None
    enabled: bool = True


def _profile_response(profile: SnmpProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "version": profile.version,
        "community": MASK if profile.community else "",
        "username": profile.username or "",
        "security_level": profile.security_level or "noAuthNoPriv",
        "auth_protocol": profile.auth_protocol or "",
        "auth_password": MASK if profile.auth_password else "",
        "privacy_protocol": profile.privacy_protocol or "",
        "privacy_password": MASK if profile.privacy_password else "",
        "port": profile.port,
        "enabled": profile.enabled,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _switch_response(switch: SnmpSwitch, interface_count: Optional[int] = None, mac_count: Optional[int] = None) -> dict:
    vendor = detect_vendor(switch.sys_descr or "", switch.sys_object_id or "")
    return {
        "id": switch.id,
        "name": switch.name,
        "host": switch.host,
        "device_id": switch.device_id,
        "profile_id": switch.profile_id,
        "enabled": switch.enabled,
        "sys_name": switch.sys_name,
        "sys_descr": switch.sys_descr,
        "sys_object_id": switch.sys_object_id,
        "vendor": vendor.label,
        "vendor_key": vendor.key,
        "vendor_notes": vendor.notes,
        "last_poll_at": switch.last_poll_at,
        "last_error": switch.last_error,
        "interface_count": interface_count if interface_count is not None else len(switch.interfaces or []),
        "mac_count": mac_count if mac_count is not None else len(switch.mac_entries or []),
    }


def _build_switch_port_visualization(db: Session, switch: SnmpSwitch) -> dict:
    interfaces = (
        db.query(SnmpInterface)
        .filter(SnmpInterface.switch_id == switch.id)
        .order_by(SnmpInterface.if_index.asc())
        .all()
    )
    mac_entries = (
        db.query(SnmpMacTableEntry, Device)
        .outerjoin(Device, func.lower(SnmpMacTableEntry.mac_address) == func.lower(Device.mac_address))
        .filter(SnmpMacTableEntry.switch_id == switch.id)
        .order_by(SnmpMacTableEntry.last_seen_at.desc())
        .all()
    )

    has_mac_vlan_context = False
    endpoints_by_if_index: dict[int, list[dict]] = {}
    for entry, device in mac_entries:
        if entry.if_index is None:
            continue
        if entry.vlan:
            has_mac_vlan_context = True
        endpoints_by_if_index.setdefault(entry.if_index, []).append({
            "mac_address": entry.mac_address,
            "vlan": entry.vlan or "",
            "device_id": device.id if device else None,
            "device_label": (device.label or device.hostname or device.ip_address or device.mac_address) if device else "",
            "last_seen_at": entry.last_seen_at,
        })

    ports = []
    for iface in interfaces:
        endpoints = endpoints_by_if_index.get(iface.if_index, [])
        is_active = iface.oper_status == "up" or bool(endpoints)
        ports.append({
            "if_index": iface.if_index,
            "name": iface.name or "",
            "description": iface.description or "",
            "alias": iface.alias or "",
            "admin_status": iface.admin_status or "",
            "oper_status": iface.oper_status or "",
            "speed_bps": iface.speed_bps,
            "is_active": is_active,
            "endpoints": endpoints,
            "last_seen_at": iface.last_seen_at,
        })

    return {
        "switch": _switch_response(switch, interface_count=len(interfaces), mac_count=len(mac_entries)),
        "has_visualization": bool(interfaces and has_mac_vlan_context),
        "ports": ports,
    }


@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    return [_profile_response(profile) for profile in db.query(SnmpProfile).order_by(SnmpProfile.name.asc()).all()]


@router.post("/profiles")
def create_profile(payload: SnmpProfilePayload, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    version = payload.version.strip()
    security_level = payload.security_level.strip() or "noAuthNoPriv"
    auth_protocol = payload.auth_protocol.strip().upper() or "SHA"
    privacy_protocol = payload.privacy_protocol.strip().upper() or "AES"
    if version not in SNMP_VERSIONS:
        raise HTTPException(status_code=400, detail="SNMP version must be 1, 2c, or 3")
    if version in {"1", "2c"} and not payload.community.strip():
        raise HTTPException(status_code=400, detail="SNMP community is required for v1/v2c profiles")
    if version == "3":
        if not payload.username.strip():
            raise HTTPException(status_code=400, detail="SNMPv3 username is required")
        if security_level not in SNMP_V3_SECURITY_LEVELS:
            raise HTTPException(status_code=400, detail="Invalid SNMPv3 security level")
        if security_level in {"authNoPriv", "authPriv"}:
            if auth_protocol not in SNMP_AUTH_PROTOCOLS:
                raise HTTPException(status_code=400, detail="Invalid SNMPv3 auth protocol")
            if not payload.auth_password.strip():
                raise HTTPException(status_code=400, detail="SNMPv3 auth password is required")
        if security_level == "authPriv":
            if privacy_protocol not in SNMP_PRIVACY_PROTOCOLS:
                raise HTTPException(status_code=400, detail="Invalid SNMPv3 privacy protocol")
            if not payload.privacy_password.strip():
                raise HTTPException(status_code=400, detail="SNMPv3 privacy password is required")
    if db.query(SnmpProfile).filter(SnmpProfile.name == payload.name.strip()).first():
        raise HTTPException(status_code=409, detail="SNMP profile name already exists")
    profile = SnmpProfile(
        name=payload.name.strip(),
        version=version,
        community=payload.community.strip(),
        username=payload.username.strip() or None,
        security_level=security_level if version == "3" else None,
        auth_protocol=auth_protocol if version == "3" and security_level in {"authNoPriv", "authPriv"} else None,
        auth_password=payload.auth_password.strip() if version == "3" and security_level in {"authNoPriv", "authPriv"} else None,
        privacy_protocol=privacy_protocol if version == "3" and security_level == "authPriv" else None,
        privacy_password=payload.privacy_password.strip() if version == "3" and security_level == "authPriv" else None,
        port=payload.port,
        enabled=payload.enabled,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _profile_response(profile)


@router.delete("/profiles/{profile_id}", response_model=MessageResponse)
def delete_profile(profile_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> MessageResponse:
    _require_snmp_enabled(db)
    profile = db.query(SnmpProfile).filter(SnmpProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="SNMP profile not found")

    db.query(SnmpSwitch).filter(SnmpSwitch.profile_id == profile_id).update(
        {SnmpSwitch.profile_id: None},
        synchronize_session=False,
    )
    db.delete(profile)
    db.commit()
    return MessageResponse(message="SNMP profile deleted")


@router.get("/switches")
def list_switches(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    switches = db.query(SnmpSwitch).order_by(SnmpSwitch.name.asc()).all()
    if not switches:
        return []
    switch_ids = [s.id for s in switches]
    interface_counts = {
        row.switch_id: row.cnt
        for row in db.query(
            SnmpInterface.switch_id,
            func.count(SnmpInterface.id).label("cnt"),
        )
        .filter(SnmpInterface.switch_id.in_(switch_ids))
        .group_by(SnmpInterface.switch_id)
        .all()
    }
    mac_counts = {
        row.switch_id: row.cnt
        for row in db.query(
            SnmpMacTableEntry.switch_id,
            func.count(SnmpMacTableEntry.id).label("cnt"),
        )
        .filter(SnmpMacTableEntry.switch_id.in_(switch_ids))
        .group_by(SnmpMacTableEntry.switch_id)
        .all()
    }
    return [
        _switch_response(switch, interface_counts.get(switch.id, 0), mac_counts.get(switch.id, 0))
        for switch in switches
    ]


@router.post("/switches")
def create_switch(payload: SnmpSwitchPayload, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    host = payload.host.strip()
    if db.query(SnmpSwitch).filter(SnmpSwitch.host == host).first():
        raise HTTPException(status_code=409, detail="SNMP switch host already exists")
    profile = db.query(SnmpProfile).filter(SnmpProfile.id == payload.profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="SNMP profile not found")
    device = db.query(Device).filter(Device.id == payload.device_id).first() if payload.device_id else None
    switch = SnmpSwitch(
        name=payload.name.strip(),
        host=host,
        profile_id=profile.id,
        device_id=device.id if device else None,
        enabled=payload.enabled,
    )
    db.add(switch)
    db.commit()
    db.refresh(switch)
    return _switch_response(switch, interface_count=0, mac_count=0)


@router.put("/switches/{switch_id}")
def update_switch(switch_id: int, payload: SnmpSwitchPayload, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    switch = db.query(SnmpSwitch).filter(SnmpSwitch.id == switch_id).first()
    if not switch:
        raise HTTPException(status_code=404, detail="SNMP switch not found")

    host = payload.host.strip()
    if db.query(SnmpSwitch).filter(SnmpSwitch.host == host, SnmpSwitch.id != switch_id).first():
        raise HTTPException(status_code=409, detail="SNMP switch host already exists")

    profile = db.query(SnmpProfile).filter(SnmpProfile.id == payload.profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="SNMP profile not found")

    device = db.query(Device).filter(Device.id == payload.device_id).first() if payload.device_id else None
    if device and db.query(SnmpSwitch).filter(SnmpSwitch.device_id == device.id, SnmpSwitch.id != switch_id).first():
        raise HTTPException(status_code=409, detail="Device is already assigned to another SNMP switch")

    switch.name = payload.name.strip()
    switch.host = host
    switch.profile_id = profile.id
    switch.device_id = device.id if device else None
    switch.enabled = payload.enabled
    db.commit()
    db.refresh(switch)

    interface_count = db.query(SnmpInterface).filter(SnmpInterface.switch_id == switch.id).count()
    mac_count = db.query(SnmpMacTableEntry).filter(SnmpMacTableEntry.switch_id == switch.id).count()
    return _switch_response(switch, interface_count=interface_count, mac_count=mac_count)


@router.delete("/switches/{switch_id}", response_model=MessageResponse)
def delete_switch(switch_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> MessageResponse:
    _require_snmp_enabled(db)
    switch = db.query(SnmpSwitch).filter(SnmpSwitch.id == switch_id).first()
    if not switch:
        raise HTTPException(status_code=404, detail="SNMP switch not found")

    db.delete(switch)
    db.commit()
    return MessageResponse(message="SNMP switch deleted")


@router.post("/switches/{switch_id}/poll")
def poll_snmp_switch(switch_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    switch = db.query(SnmpSwitch).filter(SnmpSwitch.id == switch_id).first()
    if not switch:
        raise HTTPException(status_code=404, detail="SNMP switch not found")
    if not switch.enabled:
        raise HTTPException(status_code=400, detail="SNMP switch is disabled")
    try:
        result = poll_switch(db, switch)
        db.commit()
    except Exception as exc:
        switch.last_error = str(exc)
        switch.last_poll_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        "message": "SNMP poll completed",
        "interfaces": result.interfaces,
        "mac_entries": result.mac_entries,
        "diagnostics": result.diagnostics,
        "switch": _switch_response(switch, interface_count=result.interfaces, mac_count=result.mac_entries),
    }


@router.get("/switches/{switch_id}/interfaces")
def list_switch_interfaces(switch_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    rows = (
        db.query(SnmpInterface)
        .filter(SnmpInterface.switch_id == switch_id)
        .order_by(SnmpInterface.if_index.asc())
        .all()
    )
    return [
        {
            "if_index": row.if_index,
            "name": row.name,
            "description": row.description,
            "alias": row.alias,
            "admin_status": row.admin_status,
            "oper_status": row.oper_status,
            "speed_bps": row.speed_bps,
            "last_seen_at": row.last_seen_at,
        }
        for row in rows
    ]


@router.get("/devices/{device_id}/ports")
def get_device_switch_ports(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    switch = db.query(SnmpSwitch).filter(SnmpSwitch.device_id == device_id).first()
    if not switch:
        return {"switch": None, "has_visualization": False, "ports": []}
    return _build_switch_port_visualization(db, switch)


@router.get("/topology/endpoints")
def list_snmp_endpoints(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    rows = (
        db.query(SnmpMacTableEntry, SnmpSwitch, SnmpInterface, Device)
        .join(SnmpSwitch, SnmpMacTableEntry.switch_id == SnmpSwitch.id)
        .outerjoin(
            SnmpInterface,
            (SnmpMacTableEntry.switch_id == SnmpInterface.switch_id)
            & (SnmpMacTableEntry.if_index == SnmpInterface.if_index),
        )
        .outerjoin(Device, SnmpMacTableEntry.mac_address == Device.mac_address)
        .order_by(SnmpMacTableEntry.last_seen_at.desc())
        .limit(1000)
        .all()
    )
    return [
        {
            "mac_address": entry.mac_address,
            "device_id": device.id if device else None,
            "device_label": (device.label or device.hostname or device.ip_address) if device else "",
            "switch_name": switch.name,
            "switch_host": switch.host,
            "if_index": entry.if_index,
            "interface_name": iface.name if iface else "",
            "interface_alias": iface.alias if iface else "",
            "vlan": entry.vlan or "",
            "last_seen_at": entry.last_seen_at,
        }
        for entry, switch, iface, device in rows
    ]


@router.get("/devices/{device_id}/identity")
def get_device_snmp_identity(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_snmp_enabled(db)
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return identity_for_device(db, device) or {}
