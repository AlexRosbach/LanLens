from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import ScanRun, User
from ..schemas import MessageResponse, ScanRunResponse, ScanStatusResponse
from ..services.scanner import is_scan_running, run_scan

router = APIRouter(prefix="/api/scan", tags=["scan"])


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
    return ScanStatusResponse(
        is_running=is_scan_running(),
        last_scan=last,
    )


@router.get("/history", response_model=list[ScanRunResponse])
def get_scan_history(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    runs = db.query(ScanRun).order_by(ScanRun.started_at.desc()).limit(20).all()
    return runs
