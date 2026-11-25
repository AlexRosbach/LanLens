"""Authenticated vCenter configuration and manual discovery."""
import asyncio
from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db, SessionLocal
from ..models import User, VsphereConnection, VsphereInventoryObject
from ..services.crypto import encrypt_secret, decrypt_secret
from ..services.settings_helpers import is_advanced_view_enabled
from ..services.vsphere import VsphereClient, VsphereError, validate_endpoint, reconcile_inventory, VISIBLE_FIELDS, visible_fields

router = APIRouter(prefix="/api/vsphere", tags=["vsphere"])
_discovery_lock = asyncio.Lock()
_discovery_job = {"status": "idle", "result": None, "error": None}
_discovery_task = None


class ConfigUpdate(BaseModel):
    enabled: bool = False
    endpoint: str = Field("", max_length=512)
    username: str = Field("", max_length=255)
    password: str | None = Field(None, max_length=4096)
    verify_tls: bool = True
    writeback_sysid: bool = False
    sysid_field_key: int | None = Field(None, ge=-2147483648, le=2147483647)
    visible_fields: list[str] | None = Field(None, max_length=len(VISIBLE_FIELDS))


class EnabledUpdate(BaseModel):
    enabled: bool


def _require_advanced(db):
    if not is_advanced_view_enabled(db):
        raise HTTPException(403, "Advanced View is required")


def _config(db):
    return db.get(VsphereConnection, 1)


def _response(row):
    return {"enabled": bool(row and row.enabled), "endpoint": row.endpoint if row else "",
            "username": row.username if row else "", "has_password": bool(row and row.encrypted_secret),
            "verify_tls": row.verify_tls if row else True, "writeback_sysid": bool(row and row.writeback_sysid), "visible_fields": visible_fields(row),
            "sysid_field_key": row.sysid_field_key if row else None,
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
        if data.password:
            row.encrypted_secret = encrypt_secret(data.password)
        if data.visible_fields is not None:
            if set(data.visible_fields) - set(VISIBLE_FIELDS):
                raise HTTPException(400, "Unsupported VMware inventory field")
            row.visible_fields_json = json.dumps([k for k in VISIBLE_FIELDS if k in data.visible_fields])
        row.verify_tls = data.verify_tls
        if data.writeback_sysid and (data.sysid_field_key is None or changed_target):
            raise HTTPException(400, "Save the vCenter connection and select a VM custom attribute first")
        row.sysid_field_key = None if changed_target else data.sysid_field_key
        row.writeback_sysid = data.writeback_sysid
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
                             verify_tls=row.verify_tls, fields=visible_fields(row))
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
            return await asyncio.wait_for(client.list_custom_fields(), timeout=60)
        except (VsphereError, TimeoutError) as exc:
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
            return await asyncio.wait_for(client.test(), timeout=60)
        except (VsphereError, TimeoutError) as exc:
            raise HTTPException(502, str(exc) or "vCenter test timed out") from None


@router.post("/discover")
async def discover(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_advanced(db)
    if _discovery_lock.locked():
        raise HTTPException(409, "A vSphere operation is already running")
    async with _discovery_lock:
        row = _config(db)
        client = _client(row)
        revision = row.revision
        db.rollback()
        try:
            objects, warnings = await asyncio.wait_for(client.collect(), timeout=900)
        except (VsphereError, TimeoutError) as exc:
            raise HTTPException(502, str(exc) or "vCenter discovery timed out") from None
        db.expire_all()
        current = _config(db)
        if not current or not current.enabled or current.revision != revision:
            raise HTTPException(409, "Configuration changed during discovery")
        _require_advanced(db)
        now = datetime.utcnow()
        counts = reconcile_inventory(db, current.id, objects, now)
        current.last_discovery_at = now
        db.commit()
        return {"hosts": sum(x["kind"] == "host" for x in objects),
                "vms": sum(x["kind"] == "vm" for x in objects),
                "clusters": sum(x["kind"] == "cluster" for x in objects),
                "datacenters": sum(x["kind"] == "datacenter" for x in objects),
                "networks": sum(x["kind"] == "network" for x in objects), "counts": counts, "warnings": warnings}


async def _run_discovery_job():
    try:
        with SessionLocal() as db:
            result = await discover(db=db, _=None)
        _discovery_job.update(status="completed", result=result, error=None)
    except HTTPException as exc:
        _discovery_job.update(status="failed", result=None, error=str(exc.detail))
    except Exception:
        _discovery_job.update(status="failed", result=None, error="vCenter discovery failed; check server logs")


@router.post("/discover/start")
async def start_discovery(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    global _discovery_task
    _require_advanced(db)
    if _discovery_job["status"] == "running":
        return dict(_discovery_job)
    if _discovery_lock.locked():
        raise HTTPException(409, "A vSphere operation is already running")
    _client(_config(db))
    _discovery_job.update(status="running", result=None, error=None)
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
