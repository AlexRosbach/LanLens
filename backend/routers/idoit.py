import asyncio
import json
from uuid import uuid4
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from ..auth.dependencies import get_current_user
from ..database import get_db, SessionLocal
from ..models import Device, IdoitSyncLog, User
from ..services.idoit import (
    IdoitConfig,
    idoit_sync_lock,
    IdoitClient,
    IdoitConnectionError,
    build_object_url,
    dry_run,
    build_export_rows,
    device_payload,
    get_config,
    get_or_create_state,
    rows_to_export_csv,
    sync_all_registered_devices_to_idoit,
    sync_device_to_idoit,
    update_config,
    validate_mapping,
    validate_idoit_https_url,
    _normalized_default_object_type,
)
from ..services.notification import validate_webhook_url
from ..services.idoit_scheduler import get_idoit_scheduler_status, update_idoit_interval
from ..services.settings_helpers import is_advanced_feature_enabled
from ..services.dns_names import device_display_name

router = APIRouter(prefix="/api/idoit", tags=["idoit"])


def _require_idoit_enabled(db: Session) -> None:
    if not is_advanced_feature_enabled(db, "show_cmdb_integrations"):
        raise HTTPException(status_code=403, detail="i-doit integrations are disabled")


def _device_display_name(device: Optional[Device], fallback_id: Optional[int]) -> str:
    if device:
        return device_display_name(device)
    if fallback_id:
        return f"Device #{fallback_id}"
    return "System"


class IdoitConfigPayload(BaseModel):
    idoit_enabled: Optional[bool] = None
    idoit_base_url: Optional[str] = None
    idoit_allow_insecure_http: Optional[bool] = None
    idoit_skip_tls_verification: Optional[bool] = None
    idoit_jsonrpc_path: Optional[str] = None
    idoit_portal_url: Optional[str] = None
    idoit_api_key: Optional[str] = None
    idoit_basic_username: Optional[str] = None
    idoit_basic_password: Optional[str] = None
    idoit_timeout_seconds: Optional[int] = None
    idoit_default_object_type: Optional[str] = None
    idoit_auto_sync_enabled: Optional[bool] = None
    idoit_sync_scope: Optional[str] = None
    idoit_create_policy: Optional[str] = None
    idoit_sync_interval_minutes: Optional[int] = None
    idoit_offline_retire_days: Optional[int] = None
    idoit_sync_status_field: Optional[str] = None
    idoit_mapping_json: Optional[Any] = None


class IdoitExportRow(BaseModel):
    include: bool = True
    device_id: Optional[int] = None
    object_type: str = ""
    title: str = ""
    ip_address: str = ""
    mac_address: str = ""
    hostname: str = ""
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    os_info: str = ""
    inventory_no: str = ""
    cmdb_id: str = ""
    location: str = ""
    responsible: str = ""
    notes: str = ""
    snmp_switch: str = ""
    snmp_port: str = ""
    tls_certificates: str = ""
    identity_confidence: str = ""
    lanlens_id: str = ""


class IdoitExportPayload(BaseModel):
    rows: list[IdoitExportRow]


class IdoitSysidLookupPayload(BaseModel):
    sysid: Optional[str] = None


def _config_response(db: Session) -> dict[str, Any]:
    cfg = get_config(db)
    return {
        "idoit_enabled": cfg.enabled,
        "idoit_base_url": cfg.base_url,
        "idoit_allow_insecure_http": cfg.allow_insecure_http,
        "idoit_skip_tls_verification": cfg.skip_tls_verification,
        "idoit_jsonrpc_path": cfg.jsonrpc_path,
        "idoit_portal_url": cfg.portal_url,
        "idoit_api_key_configured": bool(cfg.api_key),
        "idoit_basic_username": cfg.basic_username,
        "idoit_basic_password_configured": bool(cfg.basic_password),
        "idoit_timeout_seconds": cfg.timeout_seconds,
        "idoit_default_object_type": cfg.default_object_type,
        "idoit_auto_sync_enabled": cfg.auto_sync_enabled,
        "idoit_sync_scope": cfg.sync_scope,
        "idoit_create_policy": cfg.create_policy,
        "idoit_sync_interval_minutes": cfg.sync_interval_minutes,
        "idoit_offline_retire_days": cfg.offline_retire_days,
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
    try:
        offline_retire_days = max(1, min(3650, int(data.get("idoit_offline_retire_days", cfg.offline_retire_days) or 7)))
    except ValueError:
        offline_retire_days = cfg.offline_retire_days
    return IdoitConfig(
        enabled=bool(data.get("idoit_enabled", cfg.enabled)),
        allow_insecure_http=bool(data.get("idoit_allow_insecure_http", cfg.allow_insecure_http)),
        skip_tls_verification=bool(data.get("idoit_skip_tls_verification", cfg.skip_tls_verification)),
        base_url=(data.get("idoit_base_url", cfg.base_url) or "").strip().rstrip("/"),
        jsonrpc_path=(data.get("idoit_jsonrpc_path", cfg.jsonrpc_path) or "/src/jsonrpc.php").strip() or "/src/jsonrpc.php",
        portal_url=(data.get("idoit_portal_url", cfg.portal_url) or "").strip().rstrip("/"),
        api_key=api_key or "",
        basic_username=(data.get("idoit_basic_username", cfg.basic_username) or "").strip(),
        basic_password=basic_password or "",
        timeout_seconds=timeout,
        default_object_type=_normalized_default_object_type(data.get("idoit_default_object_type", cfg.default_object_type)),
        auto_sync_enabled=bool(data.get("idoit_auto_sync_enabled", cfg.auto_sync_enabled)),
        sync_scope="manual" if data.get("idoit_sync_scope", cfg.sync_scope) == "manual" else "all",
        create_policy="create_missing" if data.get("idoit_create_policy", cfg.create_policy) == "create_missing" else "match_only",
        sync_interval_minutes=sync_interval,
        offline_retire_days=offline_retire_days,
        sync_status_field=data.get("idoit_sync_status_field", cfg.sync_status_field) or "",
        mapping=cfg.mapping,
        mapping_error=cfg.mapping_error,
        mapping_raw=cfg.mapping_raw,
    )


@router.get("/config")
def read_config(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
    return _config_response(db)


@router.put("/config")
async def save_config(payload: IdoitConfigPayload, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
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
    if "idoit_sync_scope" in data:
        data["idoit_sync_scope"] = "manual" if data.get("idoit_sync_scope") == "manual" else "all"
    if "idoit_create_policy" in data:
        data["idoit_create_policy"] = "create_missing" if data.get("idoit_create_policy") == "create_missing" else "match_only"
    current = get_config(db)
    if base_url := data.get("idoit_base_url", current.base_url):
        try:
            validate_idoit_https_url(base_url, bool(data.get("idoit_allow_insecure_http", current.allow_insecure_http)))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        valid, reason = await validate_webhook_url(base_url, "i-doit base URL")
        if not valid:
            raise HTTPException(status_code=400, detail=reason)
    if portal_url := data.get("idoit_portal_url"):
        valid, reason = await validate_webhook_url(portal_url, "i-doit portal URL")
        if not valid:
            raise HTTPException(status_code=400, detail=reason)
    update_config(db, data)
    if "idoit_sync_interval_minutes" in data:
        update_idoit_interval(get_config(db).sync_interval_minutes)
    return _config_response(db)


@router.post("/test-connection")
async def test_connection(payload: Optional[IdoitConfigPayload] = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
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
    try:
        validate_idoit_https_url(cfg.base_url, cfg.allow_insecure_http)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    valid, reason = await validate_webhook_url(cfg.base_url, "i-doit base URL")
    if not valid:
        raise HTTPException(status_code=400, detail=reason)
    try:
        return await IdoitClient(cfg).test_connection()
    except IdoitConnectionError as exc:
        raise HTTPException(status_code=502, detail=exc.to_detail())
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"message": str(exc), "stage": "unexpected", "endpoint": ""})


@router.get("/test-application")
async def test_application(
    title: str = Query(..., min_length=1, max_length=255),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_idoit_enabled(db)
    cfg = get_config(db)
    if not cfg.base_url or not cfg.api_key:
        raise HTTPException(status_code=400, detail="Configure and save i-doit URL and API key first")
    client = IdoitClient(cfg)
    try:
        await client.login()
        return await client.diagnose_application(title)
    except IdoitConnectionError as exc:
        raise HTTPException(status_code=502, detail=exc.to_detail())
    finally:
        await client.logout_best_effort()


@router.post("/test-mapping")
def test_mapping(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
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


@router.get("/export/preview")
def preview_export(
    registered_only: bool = Query(True),
    include_offline: bool = Query(True),
    limit: int = Query(250, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_idoit_enabled(db)
    query = db.query(Device).options(
        joinedload(Device.segment),
        joinedload(Device.idoit_sync),
    )
    if registered_only:
        query = query.filter(Device.is_registered == True)  # noqa: E712
    if not include_offline:
        query = query.filter(Device.is_online == True)  # noqa: E712
    devices = query.order_by(Device.label.asc(), Device.hostname.asc(), Device.id.asc()).limit(limit).all()
    rows = build_export_rows(db, devices, get_config(db))
    return {
        "rows": rows,
        "total": len(rows),
        "registered_only": registered_only,
        "include_offline": include_offline,
    }


@router.post("/export/csv")
def export_csv(payload: IdoitExportPayload, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
    csv_body = rows_to_export_csv([row.model_dump() for row in payload.rows])
    return Response(
        csv_body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=lanlens-idoit-export.csv"},
    )


@router.post("/devices/{device_id}/dry-run")
def dry_run_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return dry_run(db, device)


@router.post("/devices/{device_id}/test-sysid")
async def test_device_sysid_lookup(
    device_id: int,
    payload: Optional[IdoitSysidLookupPayload] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_idoit_enabled(db)
    cfg = get_config(db)
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail={"message": "i-doit integration is disabled", "stage": "configuration", "endpoint": ""})
    if not cfg.base_url or not cfg.api_key:
        missing = []
        if not cfg.base_url:
            missing.append("Base URL")
        if not cfg.api_key:
            missing.append("API key")
        raise HTTPException(status_code=400, detail={"message": f"Missing required i-doit setting(s): {', '.join(missing)}", "stage": "configuration", "endpoint": ""})
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    state = get_or_create_state(db, device)
    requested_sysid = (payload.sysid if payload else None) or state.idoit_sysid or ""
    requested_sysid = requested_sysid.strip()
    if not requested_sysid:
        raise HTTPException(status_code=400, detail={"message": "No i-doit SYSID is stored for this device", "stage": "configuration", "endpoint": ""})
    try:
        validate_idoit_https_url(cfg.base_url, cfg.allow_insecure_http)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    valid, reason = await validate_webhook_url(cfg.base_url, "i-doit base URL")
    if not valid:
        raise HTTPException(status_code=400, detail=reason)
    try:
        client = IdoitClient(cfg)
        await client.login()
        payload_data = device_payload(device, cfg, db)
        object_id = await client.find_object_by_sysid(
            requested_sysid,
            payload_data.get("objectType") if isinstance(payload_data.get("objectType"), str) else None,
        )
        debug = getattr(client, "last_identity_match_debug", {})
        result = {
            "ok": bool(object_id),
            "sysid": requested_sysid,
            "object_id": object_id,
            "object_url": build_object_url(cfg.portal_url, object_id),
            "message": "i-doit SYSID lookup found an existing object" if object_id else "i-doit SYSID lookup did not find a visible object",
            "debug": debug.get("sysid_lookup", debug),
        }
        if object_id:
            try:
                result["object"] = await client.read_object(object_id)
            except IdoitConnectionError as exc:
                result["object_read_error"] = exc.to_detail()
        return result
    except IdoitConnectionError as exc:
        raise HTTPException(status_code=502, detail=exc.to_detail())
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"message": str(exc), "stage": "sysid_lookup", "endpoint": ""})
    finally:
        if "client" in locals():
            await client.logout_best_effort()


# Manual jobs are process-local and use their own DB session. The global lock
# serializes manual and scheduled writers so snapshots cannot race each other.
_sync_jobs: dict[str, dict[str, Any]] = {}
_sync_tasks: set = set()


def _job_progress(job, summary):
    job["progress"] = {key: summary[key] for key in ("total", "success", "failure", "skipped")}
    job["progress"]["current"] = len(summary["results"])


async def _run_sync_job(job_id, device_id):
    job = _sync_jobs[job_id]
    try:
        async with idoit_sync_lock:
            job["status"] = "running"
            with SessionLocal() as db:
                _require_idoit_enabled(db)
                if device_id is None:
                    result = await sync_all_registered_devices_to_idoit(
                        db, mode="manual", skip_unchanged=False,
                        on_progress=lambda summary: _job_progress(job, summary),
                    )
                else:
                    device = db.get(Device, device_id)
                    if not device:
                        raise HTTPException(404, "Device not found")
                    result = await sync_device_to_idoit(db, device, mode="manual")
                job.update(status="completed", result=result)
    except IdoitConnectionError as exc:
        job.update(status="failed", error=exc.to_detail())
    except HTTPException as exc:
        job.update(status="failed", error={"message": str(exc.detail), "stage": "sync"})
    except Exception:
        job.update(status="failed", error={"message": "i-doit sync failed; see sync logs", "stage": "sync"})


def _start_sync_job(device_id):
    for job in _sync_jobs.values():
        if job["status"] in ("queued", "running"):
            if job["device_id"] == device_id:
                return {"job_id": job["job_id"], "status": job["status"]}
            raise HTTPException(409, "Another manual i-doit sync is already running")
    while len(_sync_jobs) >= 32:
        _sync_jobs.pop(next(iter(_sync_jobs)))
    job_id = uuid4().hex
    _sync_jobs[job_id] = {"job_id": job_id, "device_id": device_id, "status": "queued",
                          "progress": None, "result": None, "error": None}
    task = asyncio.create_task(_run_sync_job(job_id, device_id))
    _sync_tasks.add(task)
    task.add_done_callback(_sync_tasks.discard)
    return {"job_id": job_id, "status": "queued"}


@router.post("/devices/{device_id}/sync", status_code=202)
async def sync_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
    if not db.get(Device, device_id):
        raise HTTPException(404, "Device not found")
    return _start_sync_job(device_id)


@router.post("/sync-all", status_code=202)
async def sync_all_devices(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
    return _start_sync_job(None)


@router.get("/sync-jobs/{job_id}")
def sync_job_status(job_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
    job = _sync_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Sync job not found or backend restarted")
    return dict(job)


@router.post("/devices/enable-sync-all")
def enable_sync_for_all_registered_devices(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
    query = db.query(Device).filter(Device.is_registered == True)  # noqa: E712
    total = query.count()
    updated = query.filter(Device.idoit_sync_enabled == False).update(  # noqa: E712
        {Device.idoit_sync_enabled: True},
        synchronize_session=False,
    )
    db.commit()
    return {"total": total, "updated": updated}


def _read_log_details(raw: Optional[str]) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        if isinstance(value, dict):
            return value
    except (ValueError, TypeError, RecursionError):
        pass
    return {"truncated": True, "invalid_legacy_details": True,
            "message": "Stored log details are invalid or truncated; run a new sync for current diagnostics."}


@router.get("/logs")
def list_logs(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_idoit_enabled(db)
    rows = (
        db.query(IdoitSyncLog, Device)
        .outerjoin(Device, IdoitSyncLog.device_id == Device.id)
        .order_by(IdoitSyncLog.created_at.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )
    return [
        {
            "id": row.id,
            "device_id": row.device_id,
            "device_name": _device_display_name(device, row.device_id),
            "mode": row.mode,
            "result": row.result,
            "idoit_object_id": row.idoit_object_id,
            "message": row.message,
            "details": _read_log_details(row.details_json),
            "created_at": row.created_at,
        }
        for row, device in rows
    ]
