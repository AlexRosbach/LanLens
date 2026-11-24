"""Authenticated vCenter configuration and manual discovery."""
import asyncio
from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import User, VsphereConnection, VsphereInventoryObject
from ..services.crypto import encrypt_secret, decrypt_secret
from ..services.settings_helpers import is_advanced_view_enabled
from ..services.vsphere import VsphereClient, VsphereError, validate_endpoint, reconcile_inventory, VISIBLE_FIELDS, visible_fields

router = APIRouter(prefix="/api/vsphere", tags=["vsphere"])
_discovery_lock = asyncio.Lock()


class ConfigUpdate(BaseModel):
    enabled: bool = False
    endpoint: str = Field("", max_length=512)
    username: str = Field("", max_length=255)
    password: str | None = Field(None, max_length=4096)
    verify_tls: bool = True
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
            "verify_tls": row.verify_tls if row else True, "visible_fields": visible_fields(row),
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
        if data.enabled and (not endpoint or not username or
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
        row.endpoint, row.username, row.enabled = endpoint, username, data.enabled
        row.revision = (row.revision or 0) + 1
        db.commit()
        return _response(row)


@router.put("/enabled")
async def set_enabled(data: EnabledUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_advanced(db)
    if _discovery_lock.locked():
        raise HTTPException(409, "A vSphere operation is already running")
    async with _discovery_lock:
        row = _config(db)
        if not row:
            if data.enabled:
                raise HTTPException(400, "Configure vSphere in Inventory tools first")
            return _response(None)
        if data.enabled and not (row.endpoint and row.username and row.encrypted_secret):
            raise HTTPException(400, "Configure vSphere in Inventory tools first")
        row.enabled = data.enabled
        row.revision = (row.revision or 0) + 1
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
            objects, warnings = await asyncio.wait_for(client.collect(), timeout=90)
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
                "datacenters": sum(x["kind"] == "datacenter" for x in objects), "counts": counts, "warnings": warnings}


@router.get("/inventory")
def inventory(kind: str = Query("vm", pattern="^(host|vm|cluster|datacenter)$"), offset: int = Query(0, ge=0),
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
