import socket
import ssl
from datetime import datetime, timezone
from typing import List
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, Service, ServiceGroup, User
from ..schemas import MessageResponse, ServiceCreate, ServiceGroupCreate, ServiceGroupResponse, ServiceGroupUpdate, ServiceResponse, ServiceUpdate

router = APIRouter(prefix="/api/devices/{device_id}/services", tags=["services"])
global_router = APIRouter(prefix="/api/services", tags=["services"])
TLS_EXPIRING_SOON_DAYS = 30


def _get_device_or_404(device_id: int, db: Session) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


def _cert_name_to_string(value) -> str:
    parts: list[str] = []
    for rdn in value or []:
        for key, item in rdn:
            parts.append(f"{key}={item}")
    return ", ".join(parts)


def _service_tls_target(device: Device, service: Service) -> tuple[str, int, str]:
    if service.url:
        parsed = urlsplit(service.url)
        if parsed.hostname:
            port = parsed.port or (443 if parsed.scheme == "https" else service.port or 443)
            return parsed.hostname, port, parsed.hostname
    if device.ip_address:
        return device.ip_address, service.port or 443, device.hostname or device.ip_address
    raise HTTPException(status_code=400, detail="Service has no URL and device has no IP address")


def _inspect_tls_certificate(host: str, port: int, server_hostname: str) -> dict:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=server_hostname) as tls_sock:
                cert_der = tls_sock.getpeercert(binary_form=True)
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": str(exc),
            "checked_at": datetime.utcnow(),
        }

    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend

        cert = x509.load_der_x509_certificate(cert_der, default_backend())
        expires_at = cert.not_valid_after_utc.replace(tzinfo=None)
        subject = cert.subject.rfc4514_string()
        issuer = cert.issuer.rfc4514_string()
        try:
            san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            sans = ", ".join(san_ext.value.get_values_for_type(x509.DNSName))
        except x509.ExtensionNotFound:
            sans = ""
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": f"Could not parse TLS certificate: {exc}",
            "checked_at": datetime.utcnow(),
        }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if expires_at and expires_at < now:
        status = "expired"
    elif expires_at and (expires_at - now).days <= TLS_EXPIRING_SOON_DAYS:
        status = "expiring_soon"
    else:
        status = "valid"

    return {
        "status": status,
        "expires_at": expires_at,
        "issuer": issuer,
        "subject": subject,
        "sans": sans,
        "self_signed": bool(subject and issuer and subject == issuer),
        "error": None,
        "checked_at": datetime.utcnow(),
    }


def _apply_tls_result(service: Service, result: dict) -> None:
    service.tls_checked_at = result.get("checked_at")
    service.tls_status = result.get("status")
    service.tls_expires_at = result.get("expires_at")
    service.tls_issuer = result.get("issuer")
    service.tls_subject = result.get("subject")
    service.tls_sans = result.get("sans")
    service.tls_self_signed = result.get("self_signed")
    service.tls_error = result.get("error")


@router.get("", response_model=List[ServiceResponse])
def list_services(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _get_device_or_404(device_id, db)
    return (
        db.query(Service)
        .filter(Service.device_id == device_id)
        .order_by(Service.sort_order, Service.created_at)
        .all()
    )


@router.post("", response_model=ServiceResponse, status_code=201)
def create_service(
    device_id: int,
    data: ServiceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _get_device_or_404(device_id, db)
    service = Service(device_id=device_id, **data.model_dump())
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


@router.get("/{service_id}", response_model=ServiceResponse)
def get_service(
    device_id: int,
    service_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    service = db.query(Service).filter(
        Service.id == service_id, Service.device_id == device_id
    ).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.put("/{service_id}", response_model=ServiceResponse)
def update_service(
    device_id: int,
    service_id: int,
    data: ServiceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    service = db.query(Service).filter(
        Service.id == service_id, Service.device_id == device_id
    ).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(service, field, value)

    db.commit()
    db.refresh(service)
    return service


@router.post("/{service_id}/check-tls", response_model=ServiceResponse)
def check_service_tls(
    device_id: int,
    service_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    device = _get_device_or_404(device_id, db)
    service = db.query(Service).filter(
        Service.id == service_id, Service.device_id == device_id
    ).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    host, port, server_hostname = _service_tls_target(device, service)
    result = _inspect_tls_certificate(host, port, server_hostname)
    _apply_tls_result(service, result)
    db.commit()
    db.refresh(service)
    return service


@router.delete("/{service_id}", response_model=MessageResponse)
def delete_service(
    device_id: int,
    service_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    service = db.query(Service).filter(
        Service.id == service_id, Service.device_id == device_id
    ).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    db.delete(service)
    db.commit()
    return MessageResponse(message="Service deleted")


@global_router.get("")
def list_all_services(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = (
        db.query(Service, Device)
        .join(Device, Service.device_id == Device.id)
        .order_by(Service.name, Device.label, Device.hostname, Device.ip_address)
        .all()
    )
    return [
        {
            "id": service.id,
            "device_id": service.device_id,
            "name": service.name,
            "service_type": service.service_type,
            "icon_key": service.icon_key,
            "icon_url": service.icon_url,
            "service_group_id": service.service_group_id,
            "service_group_name": service.service_group.name if service.service_group else None,
            "service_group_color": service.service_group.color if service.service_group else None,
            "url": service.url,
            "port": service.port,
            "protocol": service.protocol,
            "description": service.description,
            "version": service.version,
            "device_label": device.label or device.hostname or device.mac_address,
            "device_ip": device.ip_address,
            "device_class": device.device_class,
        }
        for service, device in rows
    ]


@global_router.get("/groups", response_model=List[ServiceGroupResponse])
def list_service_groups(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(ServiceGroup).order_by(ServiceGroup.sort_order, ServiceGroup.name).all()


@global_router.post("/groups", response_model=ServiceGroupResponse, status_code=201)
def create_service_group(
    data: ServiceGroupCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    group = ServiceGroup(**data.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@global_router.put("/groups/{group_id}", response_model=ServiceGroupResponse)
def update_service_group(
    group_id: int,
    data: ServiceGroupUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    group = db.query(ServiceGroup).filter(ServiceGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Service group not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    db.commit()
    db.refresh(group)
    return group


@global_router.delete("/groups/{group_id}", response_model=MessageResponse)
def delete_service_group(
    group_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    group = db.query(ServiceGroup).filter(ServiceGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Service group not found")
    db.query(Service).filter(Service.service_group_id == group_id).update({"service_group_id": None})
    db.delete(group)
    db.commit()
    return MessageResponse(message="Service group deleted")
