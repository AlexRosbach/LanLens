"""Operator-facing troubleshooting views built from persisted diagnostic logs."""
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import CmdbSyncLog, Device, IdoitSyncLog, User
from ..services.settings_helpers import get_setting_value, is_advanced_feature_enabled

router = APIRouter(prefix="/api/debug", tags=["debug"])

DEBUG_LEVELS = {"info", "warning", "error", "debug", "trace"}


def _require_debug_enabled(db: Session) -> None:
    if not is_advanced_feature_enabled(db, "show_debug_tools"):
        raise HTTPException(status_code=403, detail="Debug tools are disabled")


def _device_display_name(device: Optional[Device], fallback_id: Optional[int]) -> str:
    if device:
        return device.label or device.hostname or device.ip_address or device.mac_address or f"Device #{device.id}"
    if fallback_id:
        return f"Device #{fallback_id}"
    return "System"


def _parse_details(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        return {"raw": raw}


def _level_for_result(result: str) -> str:
    if result == "failure":
        return "error"
    if result == "skipped":
        return "warning"
    return "info"


def _passes_level(entry_level: str, requested_level: str) -> bool:
    if requested_level in {"debug", "trace", "info"}:
        return True
    if requested_level == "warning":
        return entry_level in {"warning", "error"}
    return entry_level == "error"


def _entry_matches(entry: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        [
            str(entry.get("topic") or ""),
            str(entry.get("source") or ""),
            str(entry.get("mode") or ""),
            str(entry.get("result") or ""),
            str(entry.get("message") or ""),
            str(entry.get("device_name") or ""),
            json.dumps(entry.get("details") or {}, default=str, sort_keys=True),
        ]
    ).lower()
    return query.lower() in haystack


@router.get("/logs")
def list_debug_logs(
    topic: str = Query("all", pattern="^(all|cmdb|idoit)$"),
    level: Optional[str] = Query(None),
    q: str = Query("", max_length=160),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_debug_enabled(db)
    requested_level = (level or get_setting_value(db, "debug_log_level", "warning") or "warning").strip().lower()
    if requested_level not in DEBUG_LEVELS:
        requested_level = "warning"

    entries: list[dict[str, Any]] = []
    if topic in {"all", "idoit"}:
        rows = (
            db.query(IdoitSyncLog, Device)
            .outerjoin(Device, IdoitSyncLog.device_id == Device.id)
            .order_by(IdoitSyncLog.created_at.desc())
            .limit(limit)
            .all()
        )
        for row, device in rows:
            entry_level = _level_for_result(row.result)
            entries.append({
                "id": f"idoit-{row.id}",
                "topic": "idoit",
                "source": "i-doit sync",
                "level": entry_level,
                "device_id": row.device_id,
                "device_name": _device_display_name(device, row.device_id),
                "mode": row.mode,
                "result": row.result,
                "message": row.message,
                "object_id": row.idoit_object_id,
                "details": _parse_details(row.details_json),
                "created_at": row.created_at,
            })

    if topic in {"all", "cmdb"}:
        rows = (
            db.query(CmdbSyncLog, Device)
            .outerjoin(Device, CmdbSyncLog.device_id == Device.id)
            .order_by(CmdbSyncLog.created_at.desc())
            .limit(limit)
            .all()
        )
        for row, device in rows:
            entry_level = _level_for_result(row.result)
            entries.append({
                "id": f"cmdb-{row.id}",
                "topic": "cmdb",
                "source": "CMDB REST",
                "level": entry_level,
                "device_id": row.device_id,
                "device_name": _device_display_name(device, row.device_id),
                "mode": row.mode,
                "result": row.result,
                "message": row.message,
                "object_id": None,
                "details": _parse_details(row.details_json),
                "created_at": row.created_at,
            })

    filtered = [
        entry
        for entry in entries
        if _passes_level(str(entry["level"]), requested_level) and _entry_matches(entry, q.strip())
    ]
    filtered.sort(key=lambda entry: entry["created_at"] if isinstance(entry["created_at"], datetime) else datetime.min, reverse=True)
    return {
        "topic": topic,
        "level": requested_level,
        "query": q,
        "entries": filtered[:limit],
    }
