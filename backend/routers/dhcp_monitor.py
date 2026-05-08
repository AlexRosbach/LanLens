from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import DhcpObservation, User
from ..schemas import DhcpMonitorStatusResponse, DhcpObservationResponse, MessageResponse
from ..services.dhcp_monitor import capture_dhcp_observations, is_capture_running, observation_to_response

router = APIRouter(prefix="/api/dhcp-monitor", tags=["dhcp-monitor"])


@router.get("/observations", response_model=list[DhcpObservationResponse])
def list_observations(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = db.query(DhcpObservation).order_by(DhcpObservation.observed_at.desc()).limit(limit).all()
    return [observation_to_response(row) for row in rows]


@router.post("/capture", response_model=MessageResponse)
def start_capture(
    background_tasks: BackgroundTasks,
    seconds: int = Query(20, ge=3, le=120),
    _: User = Depends(get_current_user),
):
    if is_capture_running():
        return MessageResponse(message="DHCP capture already running", success=False)
    background_tasks.add_task(capture_dhcp_observations, seconds)
    return MessageResponse(message=f"DHCP capture started for {seconds} seconds")


@router.get("/status", response_model=DhcpMonitorStatusResponse)
def get_status(_: User = Depends(get_current_user)):
    return DhcpMonitorStatusResponse(is_capturing=is_capture_running())
