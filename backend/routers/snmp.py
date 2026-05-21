from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, SnmpInterface, SnmpMacTableEntry, SnmpProfile, SnmpSwitch, User
from ..services.snmp import identity_for_device, poll_switch

router = APIRouter(prefix="/api/snmp", tags=["snmp"])

MASK = "••••••••"


class SnmpProfilePayload(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    version: str = "2c"
    community: str = Field(..., min_length=1, max_length=255)
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
        "port": profile.port,
        "enabled": profile.enabled,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _switch_response(switch: SnmpSwitch, interface_count: Optional[int] = None, mac_count: Optional[int] = None) -> dict:
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
        "last_poll_at": switch.last_poll_at,
        "last_error": switch.last_error,
        "interface_count": interface_count if interface_count is not None else len(switch.interfaces or []),
        "mac_count": mac_count if mac_count is not None else len(switch.mac_entries or []),
    }


@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [_profile_response(profile) for profile in db.query(SnmpProfile).order_by(SnmpProfile.name.asc()).all()]


@router.post("/profiles")
def create_profile(payload: SnmpProfilePayload, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if payload.version != "2c":
        raise HTTPException(status_code=400, detail="Only SNMP v2c profiles are supported in this foundation release")
    if db.query(SnmpProfile).filter(SnmpProfile.name == payload.name.strip()).first():
        raise HTTPException(status_code=409, detail="SNMP profile name already exists")
    profile = SnmpProfile(
        name=payload.name.strip(),
        version=payload.version,
        community=payload.community.strip(),
        port=payload.port,
        enabled=payload.enabled,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _profile_response(profile)


@router.get("/switches")
def list_switches(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
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
    return _switch_response(switch)


@router.post("/switches/{switch_id}/poll")
def poll_snmp_switch(switch_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
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
        "switch": _switch_response(switch),
    }


@router.get("/switches/{switch_id}/interfaces")
def list_switch_interfaces(switch_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
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


@router.get("/topology/endpoints")
def list_snmp_endpoints(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    entries = db.query(SnmpMacTableEntry).order_by(SnmpMacTableEntry.last_seen_at.desc()).limit(1000).all()
    if not entries:
        return []

    switch_ids = {e.switch_id for e in entries}
    switches = {s.id: s for s in db.query(SnmpSwitch).filter(SnmpSwitch.id.in_(switch_ids)).all()}

    iface_keys = {(e.switch_id, e.if_index) for e in entries if e.if_index is not None}
    ifaces: dict[tuple, SnmpInterface] = {}
    if iface_keys:
        sw_ids_for_ifaces = {k[0] for k in iface_keys}
        for iface in db.query(SnmpInterface).filter(SnmpInterface.switch_id.in_(sw_ids_for_ifaces)).all():
            ifaces[(iface.switch_id, iface.if_index)] = iface

    mac_addresses = {e.mac_address for e in entries}
    devices = {d.mac_address: d for d in db.query(Device).filter(Device.mac_address.in_(mac_addresses)).all()}

    result = []
    for entry in entries:
        switch = switches.get(entry.switch_id)
        iface = ifaces.get((entry.switch_id, entry.if_index)) if entry.if_index is not None else None
        device = devices.get(entry.mac_address)
        result.append({
            "mac_address": entry.mac_address,
            "device_id": device.id if device else None,
            "device_label": (device.label or device.hostname or device.ip_address) if device else "",
            "switch_name": switch.name if switch else "",
            "switch_host": switch.host if switch else "",
            "if_index": entry.if_index,
            "interface_name": iface.name if iface else "",
            "interface_alias": iface.alias if iface else "",
            "vlan": entry.vlan or "",
            "last_seen_at": entry.last_seen_at,
        })
    return result


@router.get("/devices/{device_id}/identity")
def get_device_snmp_identity(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return identity_for_device(db, device) or {}
