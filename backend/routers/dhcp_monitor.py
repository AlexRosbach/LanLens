import threading

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import DhcpObservation, User
from ..schemas import DhcpMonitorStatusResponse, DhcpObservationResponse, MessageResponse
from ..services.dhcp_monitor import capture_dhcp_observations, is_capture_running, observation_to_response, sniff_dhcp_requests, try_begin_capture

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
    seconds: int = Query(20, ge=3, le=120),
    _: User = Depends(get_current_user),
):
    if not try_begin_capture():
        return MessageResponse(message="DHCP capture already running", success=False)
    threading.Thread(
        target=capture_dhcp_observations,
        args=(seconds, 50, True),
        name="lanlens-dhcp-probe",
        daemon=True,
    ).start()
    return MessageResponse(message=f"DHCP probe started for {seconds} seconds")


@router.post("/sniff-requests", response_model=MessageResponse)
def start_request_sniffing(
    seconds: int = Query(30, ge=3, le=120),
    _: User = Depends(get_current_user),
):
    if not try_begin_capture():
        return MessageResponse(message="DHCP capture already running", success=False)
    threading.Thread(
        target=sniff_dhcp_requests,
        args=(seconds, 100, True),
        name="lanlens-dhcp-request-sniff",
        daemon=True,
    ).start()
    return MessageResponse(message=f"DHCP request sniffing started for {seconds} seconds")


@router.get("/status", response_model=DhcpMonitorStatusResponse)
def get_status(_: User = Depends(get_current_user)):
    return DhcpMonitorStatusResponse(is_capturing=is_capture_running())
