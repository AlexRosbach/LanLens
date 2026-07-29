"""Device DNS names and optional read-only Microsoft DNS integration."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, DeviceDnsName, User
from ..schemas import (
    DeviceDnsNameResponse,
    MicrosoftDnsConfigResponse,
    MicrosoftDnsConfigUpdate,
    PreferredDeviceNameUpdate,
)
from ..services.dns_names import (
    MicrosoftDnsConfig,
    collect_standard_dns_names,
    get_microsoft_dns_config,
    normalize_dns_name,
    save_microsoft_dns_config,
    synchronize_microsoft_dns,
)

router = APIRouter(prefix="/api/dns-names", tags=["dns-names"])
logger = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (ValueError, RuntimeError)):
        return str(exc)[:500]
    return "Microsoft DNS request failed; verify the server, WinRM transport, credential, and read permissions"


def _config_response(config: MicrosoftDnsConfig) -> MicrosoftDnsConfigResponse:
    return MicrosoftDnsConfigResponse(
        dns_names_enabled=config.dns_names_enabled,
        enabled=config.enabled,
        server=config.server,
        zones=config.zones or [],
        credential_id=config.credential_id,
        interval_minutes=config.interval_minutes,
        last_sync_at=config.last_sync_at,
        last_error=config.last_error,
    )


@router.get("/config", response_model=MicrosoftDnsConfigResponse)
def get_config(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MicrosoftDnsConfigResponse:
    return _config_response(get_microsoft_dns_config(db))


@router.put("/config", response_model=MicrosoftDnsConfigResponse)
def update_config(
    data: MicrosoftDnsConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MicrosoftDnsConfigResponse:
    if data.enabled and (not data.server.strip() or data.credential_id is None):
        raise HTTPException(status_code=400, detail="Microsoft DNS server and WinRM credential are required")
    config = MicrosoftDnsConfig(
        dns_names_enabled=data.dns_names_enabled,
        enabled=data.enabled,
        server=data.server,
        zones=data.zones,
        credential_id=data.credential_id,
        interval_minutes=max(5, data.interval_minutes),
    )
    save_microsoft_dns_config(db, config)
    db.commit()
    from ..services.dns_names_scheduler import update_dns_names_schedule
    update_dns_names_schedule()
    return _config_response(get_microsoft_dns_config(db))


@router.post("/test")
def test_connection(
    data: MicrosoftDnsConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    config = MicrosoftDnsConfig(
        dns_names_enabled=data.dns_names_enabled,
        enabled=True,
        server=data.server,
        zones=data.zones,
        credential_id=data.credential_id,
        interval_minutes=max(5, data.interval_minutes),
    )
    try:
        from ..services.dns_names import fetch_microsoft_dns_records
        records = fetch_microsoft_dns_records(db, config)
    except Exception as exc:
        logger.warning("Microsoft DNS connection test failed: %s", exc)
        raise HTTPException(status_code=502, detail=_safe_error(exc))
    return {"ok": True, "records": len(records), "zones": len(config.zones or [])}


@router.post("/sync")
def synchronize(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    config = get_microsoft_dns_config(db)
    try:
        return {"ok": True, **synchronize_microsoft_dns(db, config)}
    except Exception as exc:
        from ..services.dns_names import _set_setting
        logger.warning("Microsoft DNS synchronization failed: %s", exc)
        _set_setting(db, "microsoft_dns_last_error", _safe_error(exc))
        db.commit()
        raise HTTPException(status_code=502, detail=_safe_error(exc))


@router.get("/devices/{device_id}", response_model=list[DeviceDnsNameResponse])
def list_device_names(
    device_id: int,
    refresh: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DeviceDnsNameResponse]:
    config = get_microsoft_dns_config(db)
    if not config.dns_names_enabled:
        raise HTTPException(status_code=404, detail="DNS names feature is disabled")
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if refresh:
        collect_standard_dns_names(db, device)
        db.commit()
    rows = (
        db.query(DeviceDnsName)
        .filter(DeviceDnsName.device_id == device_id)
        .order_by(DeviceDnsName.status, DeviceDnsName.name)
        .all()
    )
    return [DeviceDnsNameResponse.model_validate(row) for row in rows]


@router.put("/devices/{device_id}/preferred")
def set_preferred_name(
    device_id: int,
    data: PreferredDeviceNameUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if data.mode not in {"automatic", "manual", "discovered"}:
        raise HTTPException(status_code=400, detail="mode must be automatic, manual, or discovered")
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    name = (
        (data.name or "").strip().rstrip(".")
        if data.mode == "manual"
        else normalize_dns_name(data.name)
    )
    if data.mode != "automatic" and not name:
        raise HTTPException(status_code=400, detail="A preferred name is required")
    if data.mode == "discovered":
        exists = (
            db.query(DeviceDnsName)
            .filter(DeviceDnsName.device_id == device_id, DeviceDnsName.name == name)
            .first()
        )
        if not exists:
            raise HTTPException(status_code=400, detail="Selected name was not discovered for this device")
    device.preferred_name_mode = data.mode
    device.preferred_name = name or None
    db.commit()
    return {"ok": True, "mode": device.preferred_name_mode, "name": device.preferred_name}
