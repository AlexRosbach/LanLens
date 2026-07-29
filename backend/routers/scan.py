from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..config import settings
from ..database import get_db
from ..models import Device, Notification, ScanRun, User
from ..schemas import MessageResponse, ScanInventoryStats, ScanRunResponse, ScanStatusResponse
from ..services.scanner import is_scan_running, run_scan

router = APIRouter(prefix="/api/scan", tags=["scan"])


def _configured_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    try:
        return utc_value.astimezone(ZoneInfo(settings.tz))
    except ZoneInfoNotFoundError:
        return utc_value


def _scan_run_response(run: ScanRun | None) -> ScanRunResponse | None:
    if run is None:
        return None
    return ScanRunResponse(
        id=run.id,
        started_at=_configured_datetime(run.started_at),
        finished_at=_configured_datetime(run.finished_at),
        scan_type=run.scan_type,
        devices_found=run.devices_found,
        devices_new=run.devices_new,
        devices_offline=run.devices_offline,
        status=run.status,
        error_message=run.error_message,
    )


@router.post("/start", response_model=MessageResponse)
async def start_scan(
    background_tasks: BackgroundTasks,
    _: User = Depends(get_current_user),
):
    if is_scan_running():
        return MessageResponse(message="Scan already running", success=False)
    background_tasks.add_task(run_scan, "manual")
    return MessageResponse(message="Network scan started")


@router.get("/status", response_model=ScanStatusResponse)
def get_scan_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    last = db.query(ScanRun).order_by(ScanRun.started_at.desc()).first()
    active = db.query(Device).filter(Device.is_archived == False)
    total = active.count()
    online = active.filter(Device.is_online == True).count()
    return ScanStatusResponse(
        is_running=is_scan_running(),
        last_scan=_scan_run_response(last),
        current_stats=ScanInventoryStats(
            total=total,
            online=online,
            offline=max(0, total - online),
            unread_notifications=db.query(Notification).filter(Notification.is_read == False).count(),
        ),
    )


@router.get("/history", response_model=list[ScanRunResponse])
def get_scan_history(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    runs = db.query(ScanRun).order_by(ScanRun.started_at.desc()).limit(20).all()
    return [_scan_run_response(run) for run in runs]
