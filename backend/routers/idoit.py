import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, IdoitSyncLog, User
from ..services.idoit import (
    IdoitConfig,
    IdoitClient,
    IdoitConnectionError,
    dry_run,
    get_config,
    sync_device_to_idoit,
    update_config,
    validate_mapping,
)
from ..services.notification import validate_webhook_url
from ..services.idoit_scheduler import get_idoit_scheduler_status, update_idoit_interval

router = APIRouter(prefix="/api/idoit", tags=["idoit"])


class IdoitConfigPayload(BaseModel):
    idoit_enabled: Optional[bool] = None
    idoit_base_url: Optional[str] = None
    idoit_jsonrpc_path: Optional[str] = None
    idoit_portal_url: Optional[str] = None
    idoit_api_key: Optional[str] = None
    idoit_basic_username: Optional[str] = None
    idoit_basic_password: Optional[str] = None
    idoit_timeout_seconds: Optional[int] = None
    idoit_default_object_type: Optional[str] = None
    idoit_auto_sync_enabled: Optional[bool] = None
    idoit_sync_interval_minutes: Optional[int] = None
    idoit_sync_status_field: Optional[str] = None
    idoit_mapping_json: Optional[Any] = None


def _config_response(db: Session) -> dict[str, Any]:
    cfg = get_config(db)
    return {
        "idoit_enabled": cfg.enabled,
        "idoit_base_url": cfg.base_url,
        "idoit_jsonrpc_path": cfg.jsonrpc_path,
        "idoit_portal_url": cfg.portal_url,
        "idoit_api_key_configured": bool(cfg.api_key),
        "idoit_basic_username": cfg.basic_username,
        "idoit_basic_password_configured": bool(cfg.basic_password),
        "idoit_timeout_seconds": cfg.timeout_seconds,
        "idoit_default_object_type": cfg.default_object_type,
        "idoit_auto_sync_enabled": cfg.auto_sync_enabled,
        "idoit_sync_interval_minutes": cfg.sync_interval_minutes,
        "idoit_sync_status_field": cfg.sync_status_field,
        # Keep the editable setting as a string and expose the parsed object
        # separately. That avoids clients guessing whether idoit_mapping_json is
        # raw JSON text or already-decoded data.
        "idoit_mapping_json": cfg.mapping_raw,
        "idoit_mapping_raw": cfg.mapping_raw,
        "idoit_mapping_parsed": cfg.mapping,
        "idoit_mapping_parse_error": cfg.mapping_error,
        "mapping_errors": validate_mapping(cfg.mapping, cfg.sync_status_field, cfg.default_object_type, cfg.mapping_error),
        "scheduler": get_idoit_scheduler_status(),
    }


def _config_with_overrides(cfg: IdoitConfig, data: dict[str, Any]) -> IdoitConfig:
    api_key = data.get("idoit_api_key", cfg.api_key)
    if api_key == "••••••••":
        api_key = cfg.api_key
    basic_password = data.get("idoit_basic_password", cfg.basic_password)
    if basic_password == "••••••••":
        basic_password = cfg.basic_password
    try:
        timeout = max(3, min(120, int(data.get("idoit_timeout_seconds", cfg.timeout_seconds) or 15)))
    except ValueError:
        timeout = cfg.timeout_seconds
    try:
        sync_interval = max(5, min(1440, int(data.get("idoit_sync_interval_minutes", cfg.sync_interval_minutes) or 60)))
    except ValueError:
        sync_interval = cfg.sync_interval_minutes
    return IdoitConfig(
        enabled=bool(data.get("idoit_enabled", cfg.enabled)),
        base_url=(data.get("idoit_base_url", cfg.base_url) or "").strip().rstrip("/"),
        jsonrpc_path=(data.get("idoit_jsonrpc_path", cfg.jsonrpc_path) or "/src/jsonrpc.php").strip() or "/src/jsonrpc.php",
        portal_url=(data.get("idoit_portal_url", cfg.portal_url) or "").strip().rstrip("/"),
        api_key=api_key or "",
        basic_username=(data.get("idoit_basic_username", cfg.basic_username) or "").strip(),
        basic_password=basic_password or "",
        timeout_seconds=timeout,
        default_object_type=data.get("idoit_default_object_type", cfg.default_object_type) or "C__OBJTYPE__SERVER",
        auto_sync_enabled=bool(data.get("idoit_auto_sync_enabled", cfg.auto_sync_enabled)),
        sync_interval_minutes=sync_interval,
        sync_status_field=data.get("idoit_sync_status_field", cfg.sync_status_field) or "C__CATG__GLOBAL.comment",
        mapping=cfg.mapping,
        mapping_error=cfg.mapping_error,
        mapping_raw=cfg.mapping_raw,
    )


@router.get("/config")
def read_config(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _config_response(db)


@router.put("/config")
async def save_config(payload: IdoitConfigPayload, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    data = payload.model_dump(exclude_unset=True)
    if "idoit_api_key" in data and data["idoit_api_key"] == "••••••••":
        data.pop("idoit_api_key")
    if "idoit_basic_password" in data and data["idoit_basic_password"] == "••••••••":
        data.pop("idoit_basic_password")
    if "idoit_basic_username" in data:
        data["idoit_basic_username"] = (data.get("idoit_basic_username") or "").strip()
    if "idoit_base_url" in data:
        data["idoit_base_url"] = (data.get("idoit_base_url") or "").strip()
    if "idoit_portal_url" in data:
        data["idoit_portal_url"] = (data.get("idoit_portal_url") or "").strip()
    if "idoit_jsonrpc_path" in data:
        data["idoit_jsonrpc_path"] = (data.get("idoit_jsonrpc_path") or "").strip() or "/src/jsonrpc.php"
    if base_url := data.get("idoit_base_url"):
        valid, reason = await validate_webhook_url(base_url, "i-doit base URL")
        if not valid:
            raise HTTPException(status_code=400, detail=reason)
    if portal_url := data.get("idoit_portal_url"):
        valid, reason = await validate_webhook_url(portal_url, "i-doit portal URL")
        if not valid:
            raise HTTPException(status_code=400, detail=reason)
    update_config(db, data)
    if "idoit_sync_interval_minutes" in data:
        update_idoit_interval(int(data.get("idoit_sync_interval_minutes") or 60))
    return _config_response(db)


@router.post("/test-connection")
async def test_connection(payload: Optional[IdoitConfigPayload] = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = get_config(db)
    if payload:
        data = payload.model_dump(exclude_unset=True)
        cfg = _config_with_overrides(cfg, data)
    if not cfg.base_url or not cfg.api_key:
        missing = []
        if not cfg.base_url:
            missing.append("Base URL")
        if not cfg.api_key:
            missing.append("API key")
        raise HTTPException(status_code=400, detail={"message": f"Missing required i-doit setting(s): {', '.join(missing)}", "stage": "configuration", "endpoint": ""})
    valid, reason = await validate_webhook_url(cfg.base_url, "i-doit base URL")
    if not valid:
        raise HTTPException(status_code=400, detail=reason)
    try:
        return await IdoitClient(cfg).test_connection()
    except IdoitConnectionError as exc:
        raise HTTPException(status_code=502, detail=exc.to_detail())
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"message": str(exc), "stage": "unexpected", "endpoint": ""})


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
async def sync_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        return await sync_device_to_idoit(db, device, mode="manual")
    except IdoitConnectionError as exc:
        raise HTTPException(status_code=502, detail=exc.to_detail())
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"message": str(exc), "stage": "sync", "endpoint": ""})


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
