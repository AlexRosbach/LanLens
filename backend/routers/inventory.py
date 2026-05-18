import csv
import io
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, DeviceHostRelationship, DeviceIgnoreRule, Segment, Service, Setting, User
from ..schemas import (
    DeviceIgnoreRuleCreate,
    DeviceIgnoreRuleResponse,
    DeviceIgnoreRuleUpdate,
    MessageResponse,
    TopologyEdge,
    TopologyNode,
    TopologyResponse,
)

router = APIRouter(prefix="/api/inventory", tags=["inventory"])
ignore_router = APIRouter(prefix="/api/ignore-rules", tags=["ignore-rules"])
backup_router = APIRouter(prefix="/api/backups", tags=["backups"])

SAFE_SETTING_PREFIXES = (
    "scan_",
    "dhcp_",
    "cmdb_",
    "show_",
    "auto_scan_",
    "server_",
    "notify_",
    "smtp_",
    "telegram_",
    "webhook_",
    "port_scan_",
)
SAFE_SETTING_KEYS = {"network_interface"}
SECRET_SETTING_KEY_PARTS = (
    "token",
    "password",
    "secret",
    "api_key",
    "credential",
    "webhook_url",
    "header_value",
    "auth",
    "bearer",
)


def _device_label(device: Device) -> str:
    return device.label or device.hostname or device.ip_address or device.mac_address or f"Device #{device.id}"


def _is_secret_setting(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SECRET_SETTING_KEY_PARTS)


def _safe_csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    candidate = value.lstrip(" \t\r\n")
    if candidate.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r")):
        return f"'{value}"
    return value


def _backup_records(payload: dict[str, Any], key: str, errors: list[str]) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        errors.append(f"{key} must be a list")
        return []
    records = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{key}[{index}] must be an object")
            continue
        records.append(item)
    return records


def _required_text(item: dict[str, Any], key: str, path: str, errors: list[str]) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}.{key} is required")
        return ""
    return value.strip()


@router.get("/topology", response_model=TopologyResponse)
def get_topology(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    devices = db.query(Device).all()
    segments = {s.id: s for s in db.query(Segment).all()}
    counts = dict(
        db.query(Service.device_id, func.count(Service.id))
        .group_by(Service.device_id)
        .all()
    )
    nodes = []
    for device in devices:
        segment = segments.get(device.segment_id) if device.segment_id else None
        nodes.append(TopologyNode(
            id=device.id,
            label=_device_label(device),
            ip_address=device.ip_address,
            device_class=device.device_class,
            is_online=bool(device.is_online),
            segment_id=segment.id if segment else None,
            segment_name=segment.name if segment else None,
            service_count=counts.get(device.id, 0),
        ))
    edges = [
        TopologyEdge(
            source=rel.host_device_id,
            target=rel.child_device_id,
            relationship_type=rel.relationship_type,
            label=rel.match_source,
        )
        for rel in db.query(DeviceHostRelationship).all()
    ]
    return TopologyResponse(nodes=nodes, edges=edges)


@router.get("/report")
def export_report(
    format: str = Query("markdown", pattern="^(markdown|csv|json)$"),
    segment_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Device)
    if segment_id is not None:
        query = query.filter(Device.segment_id == segment_id)
    devices = query.order_by(Device.device_class.asc(), Device.ip_address.asc()).all()
    services_by_device: dict[int, list[Service]] = {}
    for service in db.query(Service).all():
        services_by_device.setdefault(service.device_id, []).append(service)

    if format == "json":
        payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "devices": [_safe_device_export(device, services_by_device.get(device.id, [])) for device in devices],
        }
        return payload

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["CMDB ID", "Name", "IP", "MAC", "Class", "Vendor", "Online", "Location", "Responsible", "Services"])
        for device in devices:
            writer.writerow([_safe_csv_cell(value) for value in [
                device.cmdb_id or "",
                _device_label(device),
                device.ip_address or "",
                device.mac_address or "",
                device.device_class or "",
                device.vendor or "",
                "yes" if device.is_online else "no",
                device.location or "",
                device.responsible or "",
                ", ".join(s.name for s in services_by_device.get(device.id, [])),
            ]])
        return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=lanlens-report.csv"})

    lines = ["# LanLens Network Report", "", f"Generated: {datetime.utcnow().isoformat()} UTC", ""]
    for device in devices:
        lines.extend([
            f"## {_device_label(device)}",
            "",
            f"- CMDB ID: {device.cmdb_id or '—'}",
            f"- IP: {device.ip_address or '—'}",
            f"- MAC: {device.mac_address or '—'}",
            f"- Class: {device.device_class or '—'}",
            f"- Vendor: {device.vendor or '—'}",
            f"- Online: {'yes' if device.is_online else 'no'}",
            f"- Location: {device.location or '—'}",
            f"- Responsible: {device.responsible or '—'}",
        ])
        if device.purpose:
            lines.append(f"- Purpose: {device.purpose}")
        if device.description:
            lines.extend(["", device.description])
        services = services_by_device.get(device.id, [])
        if services:
            lines.extend(["", "Services:"])
            for service in services:
                target = service.url or (f"{service.protocol}://{device.ip_address}:{service.port}" if service.port and device.ip_address else "")
                lines.append(f"- {service.name} ({service.service_type}) {target}".strip())
        lines.append("")
    return Response("\n".join(lines), media_type="text/markdown", headers={"Content-Disposition": "attachment; filename=lanlens-report.md"})


def _safe_device_export(device: Device, services: list[Service]) -> dict[str, Any]:
    return {
        "id": device.id,
        "cmdb_id": device.cmdb_id,
        "label": device.label,
        "hostname": device.hostname,
        "ip_address": device.ip_address,
        "mac_address": device.mac_address,
        "device_class": device.device_class,
        "vendor": device.vendor,
        "purpose": device.purpose,
        "description": device.description,
        "location": device.location,
        "responsible": device.responsible,
        "os_info": device.os_info,
        "asset_tag": device.asset_tag,
        "notes": device.notes,
        "is_registered": device.is_registered,
        "is_online": device.is_online,
        "ignored": device.ignored,
        "notifications_muted": device.notifications_muted,
        "maintenance_until": device.maintenance_until.isoformat() if device.maintenance_until else None,
        "maintenance_note": device.maintenance_note,
        "services": [
            {
                "name": s.name,
                "service_type": s.service_type,
                "url": s.url,
                "port": s.port,
                "protocol": s.protocol,
                "description": s.description,
                "version": s.version,
                "username_hint": s.username_hint,
                "notes": s.notes,
            }
            for s in services
        ],
    }


@ignore_router.get("", response_model=list[DeviceIgnoreRuleResponse])
def list_ignore_rules(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(DeviceIgnoreRule).order_by(DeviceIgnoreRule.created_at.desc()).all()


@ignore_router.post("", response_model=DeviceIgnoreRuleResponse)
def create_ignore_rule(payload: DeviceIgnoreRuleCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if payload.rule_type not in {"mac", "ip", "hostname", "segment", "device_class"}:
        raise HTTPException(status_code=400, detail="Unsupported ignore rule type")
    rule = DeviceIgnoreRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@ignore_router.put("/{rule_id}", response_model=DeviceIgnoreRuleResponse)
def update_ignore_rule(rule_id: int, payload: DeviceIgnoreRuleUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rule = db.query(DeviceIgnoreRule).filter(DeviceIgnoreRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Ignore rule not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@ignore_router.delete("/{rule_id}", response_model=MessageResponse)
def delete_ignore_rule(rule_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rule = db.query(DeviceIgnoreRule).filter(DeviceIgnoreRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Ignore rule not found")
    db.delete(rule)
    db.commit()
    return MessageResponse(message="Ignore rule deleted")


@backup_router.get("/selective")
def export_selective_backup(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    services_by_device: dict[int, list[Service]] = {}
    for service in db.query(Service).all():
        services_by_device.setdefault(service.device_id, []).append(service)
    settings = {
        row.key: row.value
        for row in db.query(Setting).all()
        if (row.key.startswith(SAFE_SETTING_PREFIXES) or row.key in SAFE_SETTING_KEYS) and not _is_secret_setting(row.key)
    }
    payload = {
        "format": "lanlens-selective-backup-v1",
        "generated_at": datetime.utcnow().isoformat(),
        "settings": settings,
        "segments": [
            {"name": s.name, "description": s.description, "ip_start": s.ip_start, "ip_end": s.ip_end, "color": s.color}
            for s in db.query(Segment).order_by(Segment.name.asc()).all()
        ],
        "devices": [_safe_device_export(device, services_by_device.get(device.id, [])) for device in db.query(Device).all()],
        "ignore_rules": [
            {
                "name": r.name,
                "rule_type": r.rule_type,
                "pattern": r.pattern,
                "enabled": r.enabled,
                "mute_notifications": r.mute_notifications,
                "ignore_discovery": r.ignore_discovery,
                "note": r.note,
            }
            for r in db.query(DeviceIgnoreRule).all()
        ],
    }
    return Response(json.dumps(payload, indent=2, default=str), media_type="application/json", headers={"Content-Disposition": "attachment; filename=lanlens-selective-backup.json"})


@backup_router.post("/selective/import-preview")
def preview_selective_import(payload: dict[str, Any], db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if payload.get("format") != "lanlens-selective-backup-v1":
        raise HTTPException(status_code=400, detail="Unsupported backup format")
    errors: list[str] = []
    warnings: list[str] = []
    conflicts: list[dict[str, Any]] = []

    settings = payload.get("settings", {})
    if not isinstance(settings, dict):
        errors.append("settings must be an object")
        settings = {}
    for key in settings:
        if not isinstance(key, str) or not key.strip():
            errors.append("settings keys must be non-empty strings")
        elif _is_secret_setting(key):
            errors.append(f"settings.{key} looks like secret material and cannot be imported from selective backups")
        elif not (key.startswith(SAFE_SETTING_PREFIXES) or key in SAFE_SETTING_KEYS):
            warnings.append(f"settings.{key} is not part of the selective backup allowlist")

    segments = _backup_records(payload, "segments", errors)
    for index, segment in enumerate(segments):
        name = _required_text(segment, "name", f"segments[{index}]", errors)
        if name and db.query(Segment.id).filter(Segment.name == name).first():
            conflicts.append({"type": "segment", "key": name, "action": "update_existing"})

    devices = _backup_records(payload, "devices", errors)
    for index, device in enumerate(devices):
        if not any(device.get(key) for key in ("cmdb_id", "mac_address", "ip_address", "hostname", "label")):
            errors.append(f"devices[{index}] needs at least one identity field")
            continue
        match_filters = []
        if device.get("cmdb_id"):
            match_filters.append(Device.cmdb_id == str(device["cmdb_id"]))
        if device.get("mac_address"):
            match_filters.append(Device.mac_address == str(device["mac_address"]))
        if device.get("ip_address"):
            match_filters.append(Device.ip_address == str(device["ip_address"]))
        if match_filters and db.query(Device.id).filter(or_(*match_filters)).first():
            conflicts.append({"type": "device", "key": device.get("cmdb_id") or device.get("mac_address") or device.get("ip_address"), "action": "update_existing"})

    ignore_rules = _backup_records(payload, "ignore_rules", errors)
    for index, rule in enumerate(ignore_rules):
        name = _required_text(rule, "name", f"ignore_rules[{index}]", errors)
        _required_text(rule, "rule_type", f"ignore_rules[{index}]", errors)
        _required_text(rule, "pattern", f"ignore_rules[{index}]", errors)
        if name and db.query(DeviceIgnoreRule.id).filter(DeviceIgnoreRule.name == name).first():
            conflicts.append({"type": "ignore_rule", "key": name, "action": "update_existing"})

    if errors:
        raise HTTPException(status_code=400, detail={"message": "Selective backup import preview failed validation", "errors": errors})

    return {
        "write_performed": False,
        "settings": len(settings),
        "segments": len(segments),
        "devices": len(devices),
        "ignore_rules": len(ignore_rules),
        "conflicts": conflicts,
        "warnings": warnings,
        "secrets_included": False,
    }
