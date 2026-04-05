from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, Service, User
from ..schemas import MessageResponse, ServiceCreate, ServiceResponse, ServiceUpdate

router = APIRouter(prefix="/api/devices/{device_id}/services", tags=["services"])


def _get_device_or_404(device_id: int, db: Session) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


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
