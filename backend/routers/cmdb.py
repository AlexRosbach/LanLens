from datetime import datetime
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import CmdbSyncLog, Device, User
from ..services.cmdb import (
    build_payload,
    device_export,
    get_config,
    import_preview,
    push_device,
    test_connection,
    update_config,
    validate_mapping,
)
from ..services.notification import validate_webhook_url

router = APIRouter(prefix="/api/cmdb", tags=["cmdb"])


class CmdbConfigPayload(BaseModel):
    cmdb_rest_enabled: Optional[bool] = None
    cmdb_rest_target_url: Optional[str] = None
    cmdb_rest_import_url: Optional[str] = None
    cmdb_rest_method: Optional[str] = None
    cmdb_rest_auth_type: Optional[str] = None
    cmdb_rest_bearer_token: Optional[str] = None
    cmdb_rest_basic_username: Optional[str] = None
    cmdb_rest_basic_password: Optional[str] = None
    cmdb_rest_header_name: Optional[str] = None
    cmdb_rest_header_value: Optional[str] = None
    cmdb_rest_timeout_seconds: Optional[int] = None
    cmdb_rest_identity_field: Optional[str] = None
    cmdb_rest_import_conflict_strategy: Optional[str] = None
    cmdb_rest_mapping_json: Optional[Any] = None


def _config_response(db: Session) -> dict[str, Any]:
    cfg = get_config(db)
    return {
        "cmdb_rest_enabled": cfg.enabled,
        "cmdb_rest_target_url": cfg.target_url,
        "cmdb_rest_import_url": cfg.import_url,
        "cmdb_rest_method": cfg.method,
        "cmdb_rest_auth_type": cfg.auth_type,
        "cmdb_rest_bearer_token_configured": bool(cfg.bearer_token),
        "cmdb_rest_basic_username": cfg.basic_username,
        "cmdb_rest_basic_password_configured": bool(cfg.basic_password),
        "cmdb_rest_header_name": cfg.header_name,
        "cmdb_rest_header_value_configured": bool(cfg.header_value),
        "cmdb_rest_timeout_seconds": cfg.timeout_seconds,
        "cmdb_rest_identity_field": cfg.identity_field,
        "cmdb_rest_import_conflict_strategy": cfg.import_conflict_strategy,
        "cmdb_rest_mapping_json": cfg.mapping_raw,
        "cmdb_rest_mapping_parsed": cfg.mapping,
        "cmdb_rest_mapping_parse_error": cfg.mapping_error,
        "mapping_errors": validate_mapping(cfg),
    }


@router.get("/config")
def read_config(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _config_response(db)


@router.put("/config")
async def save_config(payload: CmdbConfigPayload, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    data = payload.model_dump(exclude_unset=True)
    for key in ("cmdb_rest_target_url", "cmdb_rest_import_url"):
        url = (data.get(key) or "").strip()
        if url:
            valid, reason = await validate_webhook_url(url, "CMDB REST URL")
            if not valid:
                raise HTTPException(status_code=400, detail=reason)
    update_config(db, data)
    return _config_response(db)


@router.post("/test-connection")
async def test_rest_connection(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = get_config(db)
    url = cfg.target_url or cfg.import_url
    if url:
        valid, reason = await validate_webhook_url(url, "CMDB REST URL")
        if not valid:
            raise HTTPException(status_code=400, detail=reason)
    return await test_connection(cfg)


@router.post("/test-mapping")
def test_mapping(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = get_config(db)
    fields = cfg.mapping.get("fields") if isinstance(cfg.mapping, dict) else {}
    fields = fields if isinstance(fields, dict) else {}
    return {
        "ok": not validate_mapping(cfg),
        "errors": validate_mapping(cfg),
        "fieldCount": len(fields),
        "identityField": cfg.identity_field,
        "scope": "local_structure_only",
    }


@router.get("/devices")
def export_devices(
    changed_since: Optional[datetime] = None,
    segment_id: Optional[int] = None,
    online: Optional[bool] = None,
    registered: Optional[bool] = None,
    device_class: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Device).options(joinedload(Device.segment))
    if changed_since:
        query = query.filter(Device.last_seen >= changed_since)
    if segment_id is not None:
        query = query.filter(Device.segment_id == segment_id)
    if online is not None:
        query = query.filter(Device.is_online == online)
    if registered is not None:
        query = query.filter(Device.is_registered == registered)
    if device_class:
        query = query.filter(Device.device_class == device_class)
    total = query.count()
    rows = query.order_by(Device.last_seen.desc(), Device.id.asc()).offset(offset).limit(limit).all()
    return {
        "items": [device_export(device) for device in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
    }


@router.post("/devices/{device_id}/dry-run")
def dry_run_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    device = db.query(Device).options(joinedload(Device.segment)).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    cfg = get_config(db)
    errors = validate_mapping(cfg)
    return {
        "ok": not errors,
        "errors": errors,
        "write_performed": False,
        "payload": build_payload(device, cfg),
    }


@router.post("/devices/{device_id}/push")
async def push_rest_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    device = db.query(Device).options(joinedload(Device.segment)).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    cfg = get_config(db)
    if cfg.target_url:
        valid, reason = await validate_webhook_url(cfg.target_url, "CMDB REST URL")
        if not valid:
            raise HTTPException(status_code=400, detail=reason)
    return await push_device(db, device, cfg)


@router.post("/import/preview")
async def preview_import(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = get_config(db)
    url = cfg.import_url or cfg.target_url
    if url:
        valid, reason = await validate_webhook_url(url, "CMDB REST import URL")
        if not valid:
            raise HTTPException(status_code=400, detail=reason)
    try:
        return await import_preview(cfg, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"CMDB REST import preview failed: {exc}")


@router.get("/logs")
def list_logs(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(CmdbSyncLog).order_by(CmdbSyncLog.created_at.desc()).limit(min(max(limit, 1), 200)).all()
    return [
        {
            "id": row.id,
            "device_id": row.device_id,
            "mode": row.mode,
            "result": row.result,
            "message": row.message,
            "details": json.loads(row.details_json or "{}"),
            "created_at": row.created_at,
        }
        for row in rows
    ]
