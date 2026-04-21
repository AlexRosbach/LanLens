import ipaddress
import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Set

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

logger = logging.getLogger(__name__)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import SessionLocal, get_db
from ..models import DeepScanFinding, Device, DeviceView, Notification, PortScan, Segment, Setting, User
from ..schemas import (
    DeviceListResponse,
    DeviceResponse,
    DeviceUpdate,
    MessageResponse,
    PortInfo,
    PortRangeScanRequest,
    PortScanResponse,
    SinglePortScanRequest,
)
from ..services.port_scanner import normalize_port_spec, scan_ports_async, scan_single_port_async

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


@dataclass(frozen=True)
class SegmentRange:
    start: int
    end: int
    span: int
    segment: Segment


def _prepare_segment_ranges(segments: List[Segment]) -> List[SegmentRange]:
    prepared: List[SegmentRange] = []
    for segment in segments:
        try:
            start = int(ipaddress.IPv4Address(segment.ip_start))
            end = int(ipaddress.IPv4Address(segment.ip_end))
        except Exception:
            continue
        if start > end:
            continue
        prepared.append(SegmentRange(start=start, end=end, span=end - start, segment=segment))
    return prepared


def _get_matching_segment(ip: Optional[str], segment_ranges: List[SegmentRange]) -> Optional[Segment]:
    if not ip:
        return None
    try:
        ip_int = int(ipaddress.IPv4Address(ip))
    except Exception:
        return None

    best_match: Optional[SegmentRange] = None
    for entry in segment_ranges:
        if entry.start <= ip_int <= entry.end:
            if best_match is None or entry.span < best_match.span:
                best_match = entry

    return best_match.segment if best_match else None


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


def _device_to_response(
    device: Device,
    dhcp_range=None,
    viewed_device_ids: Optional[Set[int]] = None,
    hardware_summaries: Optional[dict] = None,
    host_labels: Optional[dict] = None,
    segment_ranges: Optional[List[SegmentRange]] = None,
) -> DeviceResponse:
    from ..schemas import ServiceResponse

    if viewed_device_ids is None:
        viewed_device_ids = set()
    is_new = not device.is_registered and device.id not in viewed_device_ids
    matched_segment = _get_matching_segment(device.ip_address, segment_ranges or [])

    return DeviceResponse(
        id=device.id,
        mac_address=device.mac_address,
        ip_address=device.ip_address,
        hostname=device.hostname,
        label=device.label,
        device_class=device.device_class,
        vendor=device.vendor,
        segment_id=matched_segment.id if matched_segment else None,
        segment_name=matched_segment.name if matched_segment else None,
        segment_color=matched_segment.color if matched_segment else None,
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
        hardware_summary=(hardware_summaries or {}).get(device.id),
        host_label=(host_labels or {}).get(device.id),
        cmdb_id=device.cmdb_id,
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
    segment_ranges = _prepare_segment_ranges(db.query(Segment).all())

    # Batch-fetch hardware findings for device list display (cpu, memory, model)
    hardware_summaries: dict = {}
    if all_devices:
        device_id_list = [d.id for d in all_devices]
        hw_rows = (
            db.query(DeepScanFinding.device_id, DeepScanFinding.key, DeepScanFinding.value_json)
            .filter(
                DeepScanFinding.device_id.in_(device_id_list),
                DeepScanFinding.finding_type == "hardware",
                DeepScanFinding.key.in_(["cpu", "memory", "model"]),
            )
            .order_by(DeepScanFinding.device_id, DeepScanFinding.key, DeepScanFinding.observed_at.desc())
            .all()
        )
        # Group by device_id, keep latest per key
        hw_by_device: dict = {}
        for device_id, key, value_json in hw_rows:
            if device_id not in hw_by_device:
                hw_by_device[device_id] = {}
            if key not in hw_by_device[device_id] and value_json:
                try:
                    hw_by_device[device_id][key] = json.loads(value_json)
                except Exception:
                    hw_by_device[device_id][key] = value_json

        for device_id, hw in hw_by_device.items():
            parts = []
            # CPU: extract model name from lscpu output
            cpu_raw = hw.get("cpu", "")
            if cpu_raw:
                for line in str(cpu_raw).splitlines():
                    if "model name" in line.lower():
                        cpu_val = line.split(":", 1)[-1].strip()
                        # Shorten: remove "Intel(R) Core(TM)" prefix and "CPU @ X.XGHz" suffix
                        cpu_val = cpu_val.replace("(R)", "").replace("(TM)", "").strip()
                        cpu_val = cpu_val.split(" CPU ")[0].strip()
                        cpu_val = cpu_val.split(" @ ")[0].strip()
                        if cpu_val:
                            parts.append(cpu_val[:40])
                        break
            # Memory: extract total from free -h
            mem_raw = hw.get("memory", "")
            if mem_raw:
                for line in str(mem_raw).splitlines():
                    if line.lower().startswith("mem:"):
                        tokens = line.split()
                        if len(tokens) >= 2:
                            mem_total = tokens[1]
                            # Convert Gi/Mi to GB/MB for clarity
                            mem_total = mem_total.replace("Gi", " GB").replace("Mi", " MB").replace("Gib", " GB")
                            parts.append(f"{mem_total} RAM")
                        break
            # Fallback to model
            if not parts:
                model_raw = hw.get("model", "")
                if model_raw:
                    parts.append(str(model_raw).strip()[:60])
            if parts:
                hardware_summaries[device_id] = " · ".join(parts)

    # Batch-fetch host relationships for VM-class devices
    from ..models import DeviceHostRelationship
    host_labels: dict = {}
    vm_devices = [d for d in all_devices if "VM" in d.device_class]
    if vm_devices:
        vm_ids = [d.id for d in vm_devices]
        host_rels = (
            db.query(DeviceHostRelationship)
            .filter(DeviceHostRelationship.child_device_id.in_(vm_ids))
            .all()
        )
        host_device_ids = list({r.host_device_id for r in host_rels})
        host_devices_map = {}
        if host_device_ids:
            hosts = db.query(Device).filter(Device.id.in_(host_device_ids)).all()
            for h in hosts:
                host_devices_map[h.id] = h.label or h.hostname or h.mac_address
        for rel in host_rels:
            if rel.child_device_id not in host_labels:
                host_labels[rel.child_device_id] = host_devices_map.get(rel.host_device_id, f"Host #{rel.host_device_id}")

    return DeviceListResponse(
        items=[_device_to_response(d, dhcp_range, viewed_device_ids, hardware_summaries, host_labels, segment_ranges) for d in all_devices],
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
    segment_ranges = _prepare_segment_ranges(db.query(Segment).all())
    return DeviceListResponse(
        items=[_device_to_response(d, dhcp_range, viewed_device_ids, segment_ranges=segment_ranges) for d in devices],
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
    # Fetch hardware summary for single device (cpu, memory, model)
    hw_summary: dict = {}
    hw_rows = (
        db.query(DeepScanFinding.key, DeepScanFinding.value_json)
        .filter(
            DeepScanFinding.device_id == device_id,
            DeepScanFinding.finding_type == "hardware",
            DeepScanFinding.key.in_(["cpu", "memory", "model"]),
        )
        .order_by(DeepScanFinding.key, DeepScanFinding.observed_at.desc())
        .all()
    )
    hw: dict = {}
    for key, value_json in hw_rows:
        if key not in hw and value_json:
            try:
                hw[key] = json.loads(value_json)
            except Exception:
                hw[key] = value_json
    if hw:
        parts = []
        cpu_raw = hw.get("cpu", "")
        if cpu_raw:
            for line in str(cpu_raw).splitlines():
                if "model name" in line.lower():
                    cpu_val = line.split(":", 1)[-1].strip()
                    cpu_val = cpu_val.replace("(R)", "").replace("(TM)", "").strip()
                    cpu_val = cpu_val.split(" CPU ")[0].strip()
                    cpu_val = cpu_val.split(" @ ")[0].strip()
                    if cpu_val:
                        parts.append(cpu_val[:40])
                    break
        mem_raw = hw.get("memory", "")
        if mem_raw:
            for line in str(mem_raw).splitlines():
                if line.lower().startswith("mem:"):
                    total = line.split()[1]
                    total = total.replace("Gi", " GB").replace("Mi", " MB").replace("Gib", " GB")
                    parts.append(f"{total} RAM")
                    break
        if not parts:
            model_raw = hw.get("model", "")
            if model_raw:
                parts.append(str(model_raw).strip()[:60])
        if parts:
            hw_summary[device_id] = " · ".join(parts)
    # Fetch host label for VM-class devices
    from ..models import DeviceHostRelationship
    host_labels: dict = {}
    if "VM" in (device.device_class or ""):
        host_rel = (
            db.query(DeviceHostRelationship)
            .filter(DeviceHostRelationship.child_device_id == device_id)
            .first()
        )
        if host_rel:
            host_dev = db.query(Device).filter(Device.id == host_rel.host_device_id).first()
            if host_dev:
                host_labels[device_id] = host_dev.label or host_dev.hostname or host_dev.mac_address
            else:
                host_labels[device_id] = f"Host #{host_rel.host_device_id}"
    segment_ranges = _prepare_segment_ranges(db.query(Segment).all())
    return _device_to_response(device, dhcp_range, viewed_device_ids, hw_summary, host_labels, segment_ranges)


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

    # Auto-generate CMDB ID when device is first registered and has no ID yet
    if registering_now and not device.cmdb_id:
        try:
            from ..services.cmdb import generate_cmdb_id, get_cmdb_settings
            prefix, digits = get_cmdb_settings(db)
            for _attempt in range(3):
                try:
                    with db.begin_nested():
                        device.cmdb_id = generate_cmdb_id(db, prefix, digits)
                        db.flush()  # catch IntegrityError within savepoint only
                    break
                except IntegrityError:
                    device.cmdb_id = None
        except Exception as exc:
            logger.warning("CMDB ID generation failed: %s", exc)

    db.commit()
    db.refresh(device)
    dhcp_range = _get_dhcp_range(db)
    viewed_device_ids = _get_viewed_device_ids(db, current_user)
    segment_ranges = _prepare_segment_ranges(db.query(Segment).all())
    return _device_to_response(device, dhcp_range, viewed_device_ids, segment_ranges=segment_ranges)


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


@router.post("/{device_id}/generate-cmdb-id", response_model=DeviceResponse)
def regenerate_cmdb_id(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate or regenerate a CMDB ID for this device."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    from ..services.cmdb import generate_cmdb_id, get_cmdb_settings
    prefix, digits = get_cmdb_settings(db)
    for _attempt in range(3):
        try:
            device.cmdb_id = generate_cmdb_id(db, prefix, digits)
            db.flush()
            break
        except IntegrityError:
            db.rollback()
    else:
        raise HTTPException(status_code=409, detail="Could not generate a unique CMDB ID after 3 attempts. Try again.")
    db.commit()
    db.refresh(device)
    dhcp_range = _get_dhcp_range(db)
    viewed_device_ids = _get_viewed_device_ids(db, current_user)
    segment_ranges = _prepare_segment_ranges(db.query(Segment).all())
    return _device_to_response(device, dhcp_range, viewed_device_ids, segment_ranges=segment_ranges)


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

    # Read the global port scan range from settings
    port_scan_range = db.query(Setting).filter(Setting.key == "port_scan_range").first()
    port_spec = port_scan_range.value if port_scan_range and port_scan_range.value else "top:1000"

    background_tasks.add_task(_do_port_scan, device_id, device.ip_address, port_spec)
    return MessageResponse(message="Port scan started in background")


async def _do_port_scan(device_id: int, ip: str, port_spec: str = "top:1000") -> None:
    result = await scan_ports_async(ip, port_spec=port_spec)
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


@router.post("/{device_id}/scan-port-range", response_model=MessageResponse)
async def trigger_port_range_scan(
    device_id: int,
    body: PortRangeScanRequest,
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

    port_spec = normalize_port_spec(body.port_range)
    if not port_spec or port_spec.isdigit():
        raise HTTPException(status_code=400, detail="Port range is invalid")

    background_tasks.add_task(_do_port_scan, device_id, device.ip_address, port_spec)
    return MessageResponse(message=f"Scan for port range '{port_spec}' started in background")


@router.post("/{device_id}/scan-single-port", response_model=MessageResponse)
async def trigger_single_port_scan(
    device_id: int,
    body: SinglePortScanRequest,
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

    if body.port < 1 or body.port > 65535:
        raise HTTPException(status_code=400, detail="Port must be between 1 and 65535")

    background_tasks.add_task(_do_single_port_scan, device_id, device.ip_address, body.port)
    return MessageResponse(message=f"Scan for port {body.port} started in background")


async def _do_single_port_scan(device_id: int, ip: str, port: int) -> None:
    """Scan a single port and merge result into the latest PortScan record (or create one)."""
    result = await scan_single_port_async(ip, port)
    if result is None:
        return

    db = SessionLocal()
    try:
        # Fetch the latest existing scan for this device
        existing = (
            db.query(PortScan)
            .filter(PortScan.device_id == device_id)
            .order_by(PortScan.scanned_at.desc())
            .first()
        )

        if existing:
            # Merge the new port result into the existing open_ports list
            current_ports: list = json.loads(existing.open_ports or "[]")
            new_ports = result["open_ports"]

            # Remove any previous entry for this port and add the fresh one
            current_ports = [p for p in current_ports if p["port"] != port]
            current_ports.extend(new_ports)
            current_ports.sort(key=lambda p: p["port"])

            existing.open_ports = json.dumps(current_ports)
            existing.scanned_at = __import__("datetime").datetime.utcnow()
            # Recompute protocol flags from scratch so a closed port clears its flag
            existing.ssh_available   = False
            existing.rdp_available   = False
            existing.http_available  = False
            existing.https_available = False
            for p in current_ports:
                if p["port"] == 22:
                    existing.ssh_available = True
                elif p["port"] == 3389:
                    existing.rdp_available = True
                elif p["port"] == 80:
                    existing.http_available = True
                elif p["port"] == 443:
                    existing.https_available = True
        else:
            # No prior scan — create a new PortScan record
            existing = PortScan(
                device_id=device_id,
                open_ports=json.dumps(result["open_ports"]),
                ssh_available=result["ssh_available"],
                rdp_available=result["rdp_available"],
                http_available=result["http_available"],
                https_available=result["https_available"],
            )
            db.add(existing)

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
