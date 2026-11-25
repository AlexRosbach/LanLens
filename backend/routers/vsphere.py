"""Authenticated vCenter configuration and manual discovery."""
import asyncio
from datetime import datetime, timedelta
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db, SessionLocal
from ..models import User, VsphereConnection, VsphereInventoryObject
from ..services.vsphere_debug import log_vsphere
from ..services.crypto import encrypt_secret, decrypt_secret
from ..services.settings_helpers import is_advanced_view_enabled
from ..services.vsphere import VsphereClient, VsphereError, validate_endpoint, reconcile_inventory, VISIBLE_FIELDS, visible_fields, attribute_mappings, device_field_mappings, DEVICE_ATTRIBUTE_TARGETS

router = APIRouter(prefix="/api/vsphere", tags=["vsphere"])
_discovery_lock = asyncio.Lock()
_discovery_job = {"status": "idle", "result": None, "error": None}
_discovery_task = None


class DeviceFieldMapping(BaseModel):
    target: str
    overwrite: bool = False


class ConfigUpdate(BaseModel):
    enabled: bool = False
    endpoint: str = Field("", max_length=512)
    username: str = Field("", max_length=255)
    password: str | None = Field(None, max_length=4096)
    verify_tls: bool = True
    writeback_sysid: bool = False
    sysid_field_key: int | None = Field(None, ge=-2147483648, le=2147483647)
    read_sysid: bool = False
    auto_scan_enabled: bool | None = None
    scan_interval_minutes: int | None = Field(None, ge=5, le=10080)
    attribute_mappings: dict[str, str] = Field(default_factory=dict, max_length=64)
    device_field_mappings: dict[str, DeviceFieldMapping] | None = Field(None, max_length=64)
    visible_fields: list[str] | None = Field(None, max_length=len(VISIBLE_FIELDS))


class EnabledUpdate(BaseModel):
    enabled: bool


def _require_advanced(db):
    if not is_advanced_view_enabled(db):
        raise HTTPException(403, "Advanced View is required")


def _config(db):
    return db.get(VsphereConnection, 1)


def _next_scan_at(row, now):
    if not (row and row.enabled and row.auto_scan_enabled and row.endpoint and row.username and row.encrypted_secret):
        return None
    last = row.last_scan_attempt_at or row.last_discovery_at
    return last + timedelta(minutes=row.scan_interval_minutes or 60) if last else now


def _response(row):
    next_scan = _next_scan_at(row, datetime.utcnow())
    return {"enabled": bool(row and row.enabled), "endpoint": row.endpoint if row else "",
            "username": row.username if row else "", "has_password": bool(row and row.encrypted_secret),
            "verify_tls": row.verify_tls if row else True, "writeback_sysid": bool(row and row.writeback_sysid), "visible_fields": visible_fields(row),
            "sysid_field_key": row.sysid_field_key if row else None,
            "read_sysid": bool(row and row.read_sysid), "attribute_mappings": attribute_mappings(row),
            "device_field_mappings": device_field_mappings(row),
            "auto_scan_enabled": bool(row and row.auto_scan_enabled),
            "scan_interval_minutes": (row.scan_interval_minutes or 60) if row else 60,
            "last_scan_attempt_at": row.last_scan_attempt_at.isoformat() + "Z" if row and row.last_scan_attempt_at else None,
            "next_scan_at": next_scan.isoformat() + "Z" if next_scan else None,
            "last_discovery_at": row.last_discovery_at.isoformat() + "Z" if row and row.last_discovery_at else None}


@router.get("/config")
def get_config(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_advanced(db)
    return _response(_config(db))


@router.put("/config")
async def save_config(data: ConfigUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_advanced(db)
    if _discovery_lock.locked():
        raise HTTPException(409, "Discovery or connection test is in progress")
    async with _discovery_lock:
        row = _config(db)
        try:
            endpoint = validate_endpoint(data.endpoint) if data.endpoint.strip() else ""
        except VsphereError as exc:
            raise HTTPException(400, str(exc)) from None
        username = data.username.strip()
        changed_target = bool(row and (row.endpoint != endpoint or row.username != username))
        if (endpoint or username or data.password) and (not endpoint or not username or
                             not (data.password or (row and row.encrypted_secret and not changed_target))):
            raise HTTPException(400, "Configure the vCenter HTTPS URL, username and password")
        if row is None:
            row = VsphereConnection(id=1, revision=0)
            db.add(row)
        if changed_target:
            # Never forward saved credentials to a different target/account.
            row.encrypted_secret = ""
            if row.endpoint != endpoint:
                db.query(VsphereInventoryObject).filter_by(connection_id=1).delete(synchronize_session=False)
                row.last_discovery_at = None
                row.last_scan_attempt_at = None
        if data.password:
            row.encrypted_secret = encrypt_secret(data.password)
        if data.visible_fields is not None:
            if set(data.visible_fields) - set(VISIBLE_FIELDS):
                raise HTTPException(400, "Unsupported VMware inventory field")
            row.visible_fields_json = json.dumps([k for k in VISIBLE_FIELDS if k in data.visible_fields])
        row.verify_tls = data.verify_tls
        if (data.writeback_sysid or data.read_sysid) and (data.sysid_field_key is None or changed_target):
            raise HTTPException(400, "Save the vCenter connection and select a VM custom attribute first")
        row.sysid_field_key = None if changed_target else data.sysid_field_key
        row.writeback_sysid = data.writeback_sysid
        row.read_sysid = data.read_sysid
        import re
        if any(not re.fullmatch(r"-?\d{1,10}", k) or not v.strip() or len(v) > 100 for k, v in data.attribute_mappings.items()):
            raise HTTPException(400, "Invalid custom attribute mapping")
        if len({v.strip().casefold() for v in data.attribute_mappings.values()}) != len(data.attribute_mappings):
            raise HTTPException(400, "Custom field labels must be unique")
        row.attribute_mappings_json = json.dumps({} if changed_target else {k: v.strip() for k, v in data.attribute_mappings.items()})
        if changed_target:
            row.device_field_mappings_json = "{}"
        elif data.device_field_mappings is not None:
            mappings = {k: rule.model_dump() for k, rule in data.device_field_mappings.items()}
            if any(not re.fullmatch(r"-?\d{1,10}", k) or rule["target"] not in DEVICE_ATTRIBUTE_TARGETS
                   for k, rule in mappings.items()):
                raise HTTPException(400, "Invalid LanLens device field mapping")
            if len({rule["target"] for rule in mappings.values()}) != len(mappings):
                raise HTTPException(400, "Each LanLens target field may be mapped only once")
            row.device_field_mappings_json = json.dumps(mappings)
        if data.auto_scan_enabled is not None:
            row.auto_scan_enabled = data.auto_scan_enabled
        if data.scan_interval_minutes is not None:
            row.scan_interval_minutes = data.scan_interval_minutes
        row.endpoint, row.username, row.enabled = endpoint, username, data.enabled
        row.revision = (row.revision or 0) + 1
        db.commit()
        return _response(row)


def _set_feature_enabled(db, enabled: bool):
    row = _config(db)
    if row is None:
        if not enabled:
            return None
        row = VsphereConnection(id=1, enabled=True, revision=1)
        db.add(row)
        db.flush()
    elif row.enabled != enabled:
        row.enabled = enabled
        row.revision = (row.revision or 0) + 1
    return row


@router.put("/enabled")
async def set_enabled(data: EnabledUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_advanced(db)
    if _discovery_lock.locked():
        raise HTTPException(409, "A vSphere operation is already running")
    async with _discovery_lock:
        row = _set_feature_enabled(db, data.enabled)
        db.commit()
        return _response(row)


def _client(row):
    if not row or not row.enabled or not row.endpoint or not row.username or not row.encrypted_secret:
        raise HTTPException(400, "Enable and configure vSphere first")
    try:
        return VsphereClient(row.endpoint, row.username, decrypt_secret(row.encrypted_secret),
                             verify_tls=row.verify_tls, fields=visible_fields(row),
                             attribute_keys=set(attribute_mappings(row)) | set(device_field_mappings(row)) | ({str(row.sysid_field_key)} if row.read_sysid and row.sysid_field_key is not None else set()))
    except (ValueError, VsphereError):
        raise HTTPException(400, "Invalid vSphere settings or stored credential; re-enter the password") from None


@router.get("/custom-fields")
async def custom_fields(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_advanced(db)
    if _discovery_lock.locked():
        raise HTTPException(409, "A vSphere operation is already running")
    async with _discovery_lock:
        client = _client(_config(db))
        db.rollback()
        try:
            fields = await asyncio.wait_for(client.list_custom_fields(), timeout=60)
            log_vsphere(db, "custom_fields", "info", "VM custom attribute lookup completed", {"count": len(fields)})
            return fields
        except (VsphereError, TimeoutError) as exc:
            log_vsphere(db, "custom_fields", "error", "VM custom attribute lookup failed", {"error_type": type(exc).__name__})
            raise HTTPException(502, str(exc) or "Custom attribute lookup timed out") from None


@router.post("/test")
async def test_connection(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_advanced(db)
    if _discovery_lock.locked():
        raise HTTPException(409, "A vSphere operation is already running")
    async with _discovery_lock:
        client = _client(_config(db))
        db.rollback()
        try:
            log_vsphere(db, "test", "info", "Connection test started")
            client.diagnostic = lambda level, message, details: log_vsphere(db, "test", level, message, details)
            result = await asyncio.wait_for(client.test(), timeout=60)
            log_vsphere(db, "test", "info", "Connection test succeeded", {"host_count": result.get("host_count", 0)})
            return result
        except (VsphereError, TimeoutError) as exc:
            log_vsphere(db, "test", "error", "Connection test failed", {"error_type": type(exc).__name__})
            raise HTTPException(502, str(exc) or "vCenter test timed out") from None


@router.post("/discover")
async def discover(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return await _discover_inventory(db)


async def _discover_inventory(db, mode="manual"):
    _require_advanced(db)
    if _discovery_lock.locked():
        raise HTTPException(409, "A vSphere operation is already running")
    async with _discovery_lock:
        row = _config(db)
        client = _client(row)
        revision = row.revision
        row.last_scan_attempt_at = datetime.utcnow()
        db.commit()
        try:
            log_vsphere(db, "discovery", "info", "Inventory discovery started", {"timeout_seconds": 900, "trigger": mode})
            client.diagnostic = lambda level, message, details: log_vsphere(db, "discovery", level, message, details)
            objects, warnings = await asyncio.wait_for(client.collect(), timeout=900)
        except (VsphereError, TimeoutError) as exc:
            log_vsphere(db, "discovery", "error", "Inventory discovery failed", {"error_type": type(exc).__name__})
            raise HTTPException(502, str(exc) or "vCenter discovery timed out") from None
        db.expire_all()
        current = _config(db)
        if not current or not current.enabled or current.revision != revision:
            raise HTTPException(409, "Configuration changed during discovery")
        _require_advanced(db)
        now = datetime.utcnow()
        try:
            counts = reconcile_inventory(db, current.id, objects, now)
            current.last_discovery_at = now
            db.commit()
        except Exception:
            db.rollback()
            log_vsphere(db, "discovery", "error", "Inventory reconciliation or database save failed")
            raise
        result = {"hosts": sum(x["kind"] == "host" for x in objects),
                "vms": sum(x["kind"] == "vm" for x in objects),
                "clusters": sum(x["kind"] == "cluster" for x in objects),
                "datacenters": sum(x["kind"] == "datacenter" for x in objects),
                "networks": sum(x["kind"] == "network" for x in objects), "counts": counts, "warnings": warnings}
        # Warnings can contain VM identifiers; log counts, not upstream strings.
        log_vsphere(db, "discovery", "warning" if warnings else "info", "Inventory discovery and matching completed",
                    {**{k: v for k, v in result.items() if k != "warnings"}, "warning_count": len(warnings)})
        return result


async def _run_discovery_job(mode="manual"):
    try:
        with SessionLocal() as db:
            result = await _discover_inventory(db, mode=mode)
        _discovery_job.update(status="completed", result=result, error=None)
    except asyncio.CancelledError:
        _discovery_job.update(status="failed", result=None, error="Discovery interrupted")
        raise
    except HTTPException as exc:
        _discovery_job.update(status="failed", result=None, error=str(exc.detail))
    except Exception:
        _discovery_job.update(status="failed", result=None, error="vCenter discovery failed; check server logs")


async def scheduled_discovery_tick():
    """Check persisted schedule; share the manual job status and discovery lock."""
    if _discovery_lock.locked() or _discovery_job["status"] == "running":
        return False
    with SessionLocal() as db:
        if not is_advanced_view_enabled(db):
            return False
        now = datetime.utcnow()
        due = _next_scan_at(_config(db), now)
        if due is None or due > now:
            return False
    _discovery_job.update(status="running", result=None, error=None, trigger="scheduled")
    await _run_discovery_job(mode="scheduled")
    return True


@router.post("/discover/start")
async def start_discovery(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    global _discovery_task
    _require_advanced(db)
    if _discovery_job["status"] == "running":
        return dict(_discovery_job)
    if _discovery_lock.locked():
        raise HTTPException(409, "A vSphere operation is already running")
    _client(_config(db))
    _discovery_job.update(status="running", result=None, error=None, trigger="manual")
    _discovery_task = asyncio.create_task(_run_discovery_job())
    return dict(_discovery_job)


@router.get("/discover/status")
def discovery_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_advanced(db)
    return dict(_discovery_job)


@router.get("/inventory")
def inventory(kind: str = Query("vm", pattern="^(host|vm|cluster|datacenter|network)$"), offset: int = Query(0, ge=0),
              limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db),
              _: User = Depends(get_current_user)):
    _require_advanced(db)
    row = _config(db)
    if not row or not row.enabled:
        return {"items": [], "total": 0}
    q = db.query(VsphereInventoryObject).filter_by(connection_id=row.id, kind=kind)
    return {"total": q.count(), "items": [
        {"id": item.id, "external_id": item.external_id, "name": item.name, "device_id": item.device_id if item.match_status in ("existing", "created", "stale") else None,
         "match_status": item.match_status, "metadata": json.loads(item.metadata_json)}
        for item in q.order_by(VsphereInventoryObject.name, VsphereInventoryObject.id).offset(offset).limit(limit)
    ]}
