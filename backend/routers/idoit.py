import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, IdoitSyncLog, User
from ..services.idoit import (
    IdoitClient,
    dry_run,
    get_config,
    mark_manual_sync_placeholder,
    update_config,
    validate_mapping,
)

router = APIRouter(prefix="/api/idoit", tags=["idoit"])


class IdoitConfigPayload(BaseModel):
    idoit_enabled: Optional[bool] = None
    idoit_base_url: Optional[str] = None
    idoit_jsonrpc_path: Optional[str] = None
    idoit_api_key: Optional[str] = None
    idoit_timeout_seconds: Optional[int] = None
    idoit_default_object_type: Optional[str] = None
    idoit_auto_sync_enabled: Optional[bool] = None
    idoit_sync_status_field: Optional[str] = None
    idoit_mapping_json: Optional[Any] = None


def _config_response(db: Session) -> dict[str, Any]:
    cfg = get_config(db)
    return {
        "idoit_enabled": cfg.enabled,
        "idoit_base_url": cfg.base_url,
        "idoit_jsonrpc_path": cfg.jsonrpc_path,
        "idoit_api_key_configured": bool(cfg.api_key),
        "idoit_timeout_seconds": cfg.timeout_seconds,
        "idoit_default_object_type": cfg.default_object_type,
        "idoit_auto_sync_enabled": cfg.auto_sync_enabled,
        "idoit_sync_status_field": cfg.sync_status_field,
        "idoit_mapping_json": cfg.mapping_raw if cfg.mapping_error else cfg.mapping,
        "idoit_mapping_parse_error": cfg.mapping_error,
        "mapping_errors": validate_mapping(cfg.mapping, cfg.sync_status_field, cfg.default_object_type, cfg.mapping_error),
    }


@router.get("/config")
def read_config(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _config_response(db)


@router.put("/config")
def save_config(payload: IdoitConfigPayload, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    data = payload.model_dump(exclude_unset=True)
    if "idoit_api_key" in data and data["idoit_api_key"] == "••••••••":
        data.pop("idoit_api_key")
    update_config(db, data)
    return _config_response(db)


@router.post("/test-connection")
async def test_connection(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = get_config(db)
    if not cfg.base_url or not cfg.api_key:
        raise HTTPException(status_code=400, detail="i-doit URL and API key are required")
    try:
        return await IdoitClient(cfg).test_connection()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"i-doit connection failed: {exc}")


@router.post("/test-mapping")
def test_mapping(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = get_config(db)
    errors = validate_mapping(cfg.mapping, cfg.sync_status_field, cfg.default_object_type, cfg.mapping_error)
    mapping = cfg.mapping if isinstance(cfg.mapping, dict) else {}
    fields = mapping.get("fields") if isinstance(mapping.get("fields"), dict) else {}
    return {
        "ok": not errors,
        "errors": errors,
        "objectType": mapping.get("objectType") or cfg.default_object_type,
        "syncStatusField": cfg.sync_status_field,
        "fieldCount": len(fields),
        "scope": "local_structure_only",
        "remoteValidation": "not_performed",
    }


@router.post("/devices/{device_id}/dry-run")
def dry_run_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return dry_run(db, device)


@router.post("/devices/{device_id}/sync")
def sync_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return mark_manual_sync_placeholder(db, device)


@router.get("/logs")
def list_logs(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(IdoitSyncLog).order_by(IdoitSyncLog.created_at.desc()).limit(min(max(limit, 1), 200)).all()
    return [
        {
            "id": row.id,
            "device_id": row.device_id,
            "mode": row.mode,
            "result": row.result,
            "idoit_object_id": row.idoit_object_id,
            "message": row.message,
            "details": json.loads(row.details_json or "{}"),
            "created_at": row.created_at,
        }
        for row in rows
    ]
