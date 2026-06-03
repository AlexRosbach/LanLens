import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import DhcpAuthorizedServer, DhcpObservation, User
from ..schemas import (
    DhcpAuthorizedServerCreate,
    DhcpAuthorizedServerResponse,
    DhcpAuthorizedServerUpdate,
    DhcpMonitorStatusResponse,
    DhcpObservationResponse,
    MessageResponse,
)
from ..services.dhcp_monitor import capture_dhcp_observations, is_capture_running, observation_to_response, sniff_dhcp_requests, try_begin_capture
from ..services.mac_vendor import normalize_mac
from ..services.settings_helpers import is_advanced_feature_enabled

router = APIRouter(prefix="/api/dhcp-monitor", tags=["dhcp-monitor"])


def _require_dhcp_monitor_enabled(db: Session) -> None:
    if not is_advanced_feature_enabled(db, "show_dhcp_monitor_nav"):
        raise HTTPException(status_code=403, detail="DHCP Monitor is disabled")


@router.get("/observations", response_model=list[DhcpObservationResponse])
def list_observations(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_dhcp_monitor_enabled(db)
    rows = db.query(DhcpObservation).order_by(DhcpObservation.observed_at.desc()).limit(limit).all()
    authorized_servers = db.query(DhcpAuthorizedServer).filter(DhcpAuthorizedServer.enabled == True).all()
    return [observation_to_response(row, authorized_servers) for row in rows]


@router.get("/authorized-servers", response_model=list[DhcpAuthorizedServerResponse])
def list_authorized_servers(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_dhcp_monitor_enabled(db)
    return db.query(DhcpAuthorizedServer).order_by(DhcpAuthorizedServer.name.asc()).all()


@router.post("/authorized-servers", response_model=DhcpAuthorizedServerResponse)
def create_authorized_server(
    payload: DhcpAuthorizedServerCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_dhcp_monitor_enabled(db)
    name = payload.name.strip()
    server_ip = payload.server_ip.strip() if payload.server_ip and payload.server_ip.strip() else None
    server_mac = normalize_mac(payload.server_mac) if payload.server_mac else None
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    if not server_ip and not server_mac:
        raise HTTPException(status_code=422, detail="Server IP or MAC is required")
    row = DhcpAuthorizedServer(
        name=name,
        server_ip=server_ip,
        server_mac=server_mac,
        enabled=payload.enabled,
        note=payload.note.strip() if payload.note and payload.note.strip() else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/authorized-servers/{server_id}", response_model=DhcpAuthorizedServerResponse)
def update_authorized_server(
    server_id: int,
    payload: DhcpAuthorizedServerUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_dhcp_monitor_enabled(db)
    row = db.query(DhcpAuthorizedServer).filter(DhcpAuthorizedServer.id == server_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Authorized DHCP server not found")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name is required")
        row.name = name
    if payload.server_ip is not None:
        row.server_ip = payload.server_ip.strip() if payload.server_ip.strip() else None
    if payload.server_mac is not None:
        row.server_mac = normalize_mac(payload.server_mac) if payload.server_mac.strip() else None
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.note is not None:
        row.note = payload.note.strip() if payload.note.strip() else None
    if not row.server_ip and not row.server_mac:
        raise HTTPException(status_code=422, detail="Server IP or MAC is required")
    db.commit()
    db.refresh(row)
    return row


@router.delete("/authorized-servers/{server_id}", response_model=MessageResponse)
def delete_authorized_server(
    server_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_dhcp_monitor_enabled(db)
    row = db.query(DhcpAuthorizedServer).filter(DhcpAuthorizedServer.id == server_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Authorized DHCP server not found")
    db.delete(row)
    db.commit()
    return MessageResponse(message="Authorized DHCP server deleted")


@router.post("/capture", response_model=MessageResponse)
def start_capture(
    seconds: int = Query(20, ge=3, le=120),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_dhcp_monitor_enabled(db)
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
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _require_dhcp_monitor_enabled(db)
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
def get_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _require_dhcp_monitor_enabled(db)
    return DhcpMonitorStatusResponse(is_capturing=is_capture_running())
