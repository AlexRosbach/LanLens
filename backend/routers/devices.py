import ipaddress
import json
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import SessionLocal, get_db
from ..models import Device, PortScan, User
from ..schemas import (
    DeviceListResponse,
    DeviceResponse,
    DeviceUpdate,
    MessageResponse,
    PortInfo,
    PortScanResponse,
)
from ..services.port_scanner import scan_ports_async

router = APIRouter(prefix="/api/devices", tags=["devices"])


def _parse_ports(raw: str) -> List[PortInfo]:
    try:
        return [PortInfo(**p) for p in json.loads(raw or "[]")]
    except Exception:
        return []


def _latest_scan_response(device: Device) -> Optional[PortScanResponse]:
    if not device.port_scans:
        return None
    latest = device.port_scans[-1]
    return PortScanResponse(
        id=latest.id,
        scanned_at=latest.scanned_at,
        open_ports=_parse_ports(latest.open_ports),
        ssh_available=latest.ssh_available,
        rdp_available=latest.rdp_available,
        http_available=latest.http_available,
        https_available=latest.https_available,
    )


def _device_to_response(device: Device) -> DeviceResponse:
    from ..schemas import ServiceResponse
    return DeviceResponse(
        id=device.id,
        mac_address=device.mac_address,
        ip_address=device.ip_address,
        hostname=device.hostname,
        label=device.label,
        device_class=device.device_class,
        vendor=device.vendor,
        purpose=device.purpose,
        description=device.description,
        location=device.location,
        responsible=device.responsible,
        password_location=device.password_location,
        os_info=device.os_info,
        asset_tag=device.asset_tag,
        notes=device.notes,
        is_registered=device.is_registered,
        is_online=device.is_online,
        first_seen=device.first_seen,
        last_seen=device.last_seen,
        latest_scan=_latest_scan_response(device),
        services=[ServiceResponse.model_validate(s) for s in device.services],
    )


@router.get("", response_model=DeviceListResponse)
def list_devices(
    online_only: Optional[bool] = None,
    unregistered_only: Optional[bool] = None,
    device_class: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Device)

    if online_only is True:
        query = query.filter(Device.is_online == True)
    elif online_only is False:
        query = query.filter(Device.is_online == False)

    if unregistered_only:
        query = query.filter(Device.is_registered == False)

    if device_class:
        query = query.filter(Device.device_class == device_class)

    if search:
        term = f"%{search.lower()}%"
        query = query.filter(
            Device.mac_address.ilike(term)
            | Device.ip_address.ilike(term)
            | Device.label.ilike(term)
            | Device.hostname.ilike(term)
            | Device.vendor.ilike(term)
        )

    all_devices = query.order_by(Device.last_seen.desc()).all()

    # Global network stats (unfiltered) for sidebar display
    total = db.query(Device).count()
    online = db.query(Device).filter(Device.is_online == True).count()
    unregistered = db.query(Device).filter(Device.is_registered == False).count()

    return DeviceListResponse(
        items=[_device_to_response(d) for d in all_devices],
        total=total,
        online=online,
        offline=total - online,
        unregistered=unregistered,
    )


@router.get("/new", response_model=DeviceListResponse)
def get_new_devices(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    devices = db.query(Device).filter(Device.is_registered == False).all()
    total = db.query(Device).count()
    online = db.query(Device).filter(Device.is_online == True).count()
    return DeviceListResponse(
        items=[_device_to_response(d) for d in devices],
        total=total,
        online=online,
        offline=total - online,
        unregistered=len(devices),
    )


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return _device_to_response(device)


@router.put("/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: int,
    update: DeviceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(device, field, value)

    db.commit()
    db.refresh(device)
    return _device_to_response(device)


@router.delete("/{device_id}", response_model=MessageResponse)
def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()
    return MessageResponse(message="Device deleted")


@router.post("/{device_id}/scan-ports", response_model=MessageResponse)
async def trigger_port_scan(
    device_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.ip_address:
        raise HTTPException(status_code=400, detail="Device has no IP address")

    # Validate IP format before passing to nmap
    try:
        ipaddress.IPv4Address(device.ip_address)
    except ValueError:
        raise HTTPException(status_code=400, detail="Device has an invalid IP address")

    background_tasks.add_task(_do_port_scan, device_id, device.ip_address)
    return MessageResponse(message="Port scan started in background")


async def _do_port_scan(device_id: int, ip: str) -> None:
    result = await scan_ports_async(ip)
    if result is None:
        return

    db = SessionLocal()
    try:
        scan = PortScan(
            device_id=device_id,
            open_ports=json.dumps(result["open_ports"]),
            ssh_available=result["ssh_available"],
            rdp_available=result["rdp_available"],
            http_available=result["http_available"],
            https_available=result["https_available"],
        )
        db.add(scan)
        db.commit()
    finally:
        db.close()


@router.get("/{device_id}/ports", response_model=List[PortScanResponse])
def get_device_ports(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    scans = (
        db.query(PortScan)
        .filter(PortScan.device_id == device_id)
        .order_by(PortScan.scanned_at.desc())
        .limit(5)
        .all()
    )
    return [
        PortScanResponse(
            id=s.id,
            scanned_at=s.scanned_at,
            open_ports=_parse_ports(s.open_ports),
            ssh_available=s.ssh_available,
            rdp_available=s.rdp_available,
            http_available=s.http_available,
            https_available=s.https_available,
        )
        for s in scans
    ]
