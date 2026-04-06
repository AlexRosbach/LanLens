import ipaddress
import json
from typing import List, Optional, Set

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import SessionLocal, get_db
from ..models import Device, DeviceView, Notification, PortScan, Setting, User
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


def _get_dhcp_range(db: Session):
    """Return (dhcp_start_int, dhcp_end_int) as integers for IP comparison, or None."""
    try:
        start_row = db.query(Setting).filter(Setting.key == "dhcp_start").first()
        end_row = db.query(Setting).filter(Setting.key == "dhcp_end").first()
        if start_row and start_row.value and end_row and end_row.value:
            return (
                int(ipaddress.IPv4Address(start_row.value)),
                int(ipaddress.IPv4Address(end_row.value)),
            )
    except Exception:
        pass
    return None


def _is_dhcp(ip: Optional[str], dhcp_range) -> bool:
    if not ip or not dhcp_range:
        return False
    try:
        ip_int = int(ipaddress.IPv4Address(ip))
        return dhcp_range[0] <= ip_int <= dhcp_range[1]
    except Exception:
        return False


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


def _get_viewed_device_ids(db: Session, current_user: User) -> Set[int]:
    return {
        device_id for (device_id,) in db.query(DeviceView.device_id)
        .filter(DeviceView.user_id == current_user.id)
        .all()
    }


def _device_to_response(device: Device, dhcp_range=None, viewed_device_ids: Optional[Set[int]] = None) -> DeviceResponse:
    from ..schemas import ServiceResponse

    if viewed_device_ids is None:
        viewed_device_ids = set()
    is_new = not device.is_registered and device.id not in viewed_device_ids

    return DeviceResponse(
        id=device.id,
        mac_address=device.mac_address,
        ip_address=device.ip_address,
        hostname=device.hostname,
        label=device.label,
        device_class=device.device_class,
        vendor=device.vendor,
        segment_id=device.segment_id,
        segment_name=device.segment.name if device.segment else None,
        segment_color=device.segment.color if device.segment else None,
        is_dhcp=_is_dhcp(device.ip_address, dhcp_range),
        purpose=device.purpose,
        description=device.description,
        location=device.location,
        responsible=device.responsible,
        password_location=device.password_location,
        os_info=device.os_info,
        asset_tag=device.asset_tag,
        notes=device.notes,
        is_registered=device.is_registered,
        is_new=is_new,
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
    current_user: User = Depends(get_current_user),
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
    viewed_device_ids = _get_viewed_device_ids(db, current_user)

    total = db.query(Device).count()
    online = db.query(Device).filter(Device.is_online == True).count()
    unregistered = db.query(Device).filter(Device.is_registered == False).count()
    dhcp_range = _get_dhcp_range(db)

    return DeviceListResponse(
        items=[_device_to_response(d, dhcp_range, viewed_device_ids) for d in all_devices],
        total=total,
        online=online,
        offline=total - online,
        unregistered=unregistered,
    )


@router.get("/new", response_model=DeviceListResponse)
def get_new_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    viewed_subquery = db.query(DeviceView.device_id).filter(DeviceView.user_id == current_user.id)
    devices = (
        db.query(Device)
        .filter(Device.is_registered == False)
        .filter(~Device.id.in_(viewed_subquery))
        .order_by(Device.last_seen.desc())
        .all()
    )
    total = db.query(Device).count()
    online = db.query(Device).filter(Device.is_online == True).count()
    unregistered = db.query(Device).filter(Device.is_registered == False).count()
    dhcp_range = _get_dhcp_range(db)
    viewed_device_ids = _get_viewed_device_ids(db, current_user)
    return DeviceListResponse(
        items=[_device_to_response(d, dhcp_range, viewed_device_ids) for d in devices],
        total=total,
        online=online,
        offline=total - online,
        unregistered=unregistered,
    )


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    dhcp_range = _get_dhcp_range(db)
    viewed_device_ids = _get_viewed_device_ids(db, current_user)
    return _device_to_response(device, dhcp_range, viewed_device_ids)


@router.put("/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: int,
    update: DeviceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    registering_now = update.is_registered is True and not device.is_registered

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(device, field, value)

    if registering_now:
        db.query(Notification).filter(
            Notification.device_id == device.id,
            Notification.event_type == "new_device",
            Notification.is_read == False,
        ).update({"is_read": True})

    db.commit()
    db.refresh(device)
    dhcp_range = _get_dhcp_range(db)
    viewed_device_ids = _get_viewed_device_ids(db, current_user)
    return _device_to_response(device, dhcp_range, viewed_device_ids)


@router.post("/{device_id}/mark-viewed", response_model=MessageResponse)
def mark_device_viewed(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    existing = db.query(DeviceView).filter(
        DeviceView.user_id == current_user.id,
        DeviceView.device_id == device.id,
    ).first()
    if not existing:
        try:
            db.add(DeviceView(user_id=current_user.id, device_id=device.id))
            db.commit()
        except IntegrityError:
            db.rollback()
    return MessageResponse(message="Device marked as viewed")


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
