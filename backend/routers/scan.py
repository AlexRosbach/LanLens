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
_manual_scan_pipeline_running = False


async def _run_manual_scan_pipeline() -> None:
    """Run discovery and then populate Connect data for all online devices."""
    global _manual_scan_pipeline_running
    _manual_scan_pipeline_running = True
    try:
        scan_run = await run_scan("manual")
        if not scan_run or scan_run.status != "done":
            return

        from .devices import start_automatic_bulk_port_scan

        port_scan_task = start_automatic_bulk_port_scan()
        if port_scan_task is not None:
            await port_scan_task
    finally:
        _manual_scan_pipeline_running = False


def _manual_scan_is_running() -> bool:
    if _manual_scan_pipeline_running or is_scan_running():
        return True
    from .devices import is_bulk_port_scan_running

    return is_bulk_port_scan_running()


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
    global _manual_scan_pipeline_running
    if _manual_scan_is_running():
        return MessageResponse(message="Scan already running", success=False)
    _manual_scan_pipeline_running = True
    background_tasks.add_task(_run_manual_scan_pipeline)
    return MessageResponse(message="Network discovery and port scan started")


@router.get("/status", response_model=ScanStatusResponse)
def get_scan_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    last = db.query(ScanRun).order_by(ScanRun.started_at.desc()).first()
    active = db.query(Device).filter(Device.is_archived == False)
    total = active.count()
    online = active.filter(Device.is_online == True).count()
    new = active.filter(Device.is_registered == False).count()
    archived = db.query(Device).filter(Device.is_archived == True).count()
    return ScanStatusResponse(
        is_running=_manual_scan_is_running(),
        last_scan=_scan_run_response(last),
        current_stats=ScanInventoryStats(
            total=total,
            online=online,
            offline=max(0, total - online),
            new=new,
            archived=archived,
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
