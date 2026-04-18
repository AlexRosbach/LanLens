"""Admin endpoints: settings export/import, database export.

Authorization: LanLens is a single-user application — only one account can
be created. All endpoints require a valid session (`get_current_user`) AND
that the user has completed initial setup (`force_password_change=False`).
This prevents a freshly-created account that hasn't changed its default
password from exporting secrets or downloading the database.
"""

import io
import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db, IS_SQLITE, DB_PATH
from ..models import Setting, User
from ..schemas import MessageResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_setup_complete(current_user: User = Depends(get_current_user)) -> User:
    """Ensure the account has completed initial password setup before granting access."""
    if current_user.force_password_change:
        raise HTTPException(
            status_code=403,
            detail="Complete the initial password setup before accessing admin endpoints.",
        )
    return current_user


@router.get("/export/settings")
def export_settings(
    db: Session = Depends(get_db),
    _: User = Depends(_require_setup_complete),
):
    """Export all application settings as a JSON file."""
    rows = db.query(Setting).all()
    data = {
        "version": "1.4.1",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "settings": {r.key: r.value for r in rows},
    }
    content = json.dumps(data, indent=2, ensure_ascii=False)
    return StreamingResponse(
        io.StringIO(content),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=lanlens-settings.json"},
    )


@router.get("/export/database")
def export_database(
    _: User = Depends(_require_setup_complete),
):
    """Download the SQLite database file (only available when using SQLite)."""
    if not IS_SQLITE or not DB_PATH:
        raise HTTPException(
            status_code=400,
            detail="Database export as file is only supported for SQLite. Use your database's native backup tool for MariaDB/PostgreSQL.",
        )
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Database file not found")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return FileResponse(
        DB_PATH,
        media_type="application/octet-stream",
        filename=f"lanlens-backup-{ts}.db",
    )


@router.post("/import/settings", response_model=MessageResponse)
async def import_settings(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(_require_setup_complete),
):
    """Import settings from a previously exported JSON file."""
    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")

    # Accept both {"settings": {...}} and flat {"key": "value"} formats
    settings_dict = data.get("settings", data) if isinstance(data, dict) else {}
    if not isinstance(settings_dict, dict):
        raise HTTPException(status_code=400, detail="Settings must be a JSON object")

    # Filter out metadata keys
    skip_keys = {"version", "exported_at"}
    count = 0
    for key, value in settings_dict.items():
        if key in skip_keys:
            continue
        if not isinstance(key, str):
            continue
        str_value = str(value) if value is not None else ""
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = str_value
        else:
            db.add(Setting(key=key, value=str_value))
        count += 1

    db.commit()
    return MessageResponse(message=f"Successfully imported {count} settings. Reload the page to apply.")
