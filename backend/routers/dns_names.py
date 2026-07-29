"""Device DNS names and optional read-only AXFR integration."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, DeviceDnsName, User
from ..schemas import (
    DeviceDnsNameResponse,
    AxfrDnsConfigResponse,
    AxfrDnsConfigUpdate,
    PreferredDeviceNameUpdate,
)
from ..services.dns_names import (
    AxfrDnsConfig,
    collect_standard_dns_names,
    get_axfr_dns_config,
    normalize_dns_name,
    save_axfr_dns_config,
    synchronize_axfr_dns,
)

router = APIRouter(prefix="/api/dns-names", tags=["dns-names"])
logger = logging.getLogger(__name__)
TSIG_ALGORITHMS = {"hmac-sha256", "hmac-sha384", "hmac-sha512"}


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (ValueError, RuntimeError)):
        return str(exc)[:500]
    return "AXFR request failed; verify the DNS server, zone-transfer ACL, zone, port, and optional TSIG settings"


def _config_response(config: AxfrDnsConfig) -> AxfrDnsConfigResponse:
    return AxfrDnsConfigResponse(
        dns_names_enabled=config.dns_names_enabled,
        enabled=config.enabled,
        server=config.server,
        zones=config.zones or [],
        port=config.port,
        timeout_seconds=config.timeout_seconds,
        tsig_key_name=config.tsig_key_name,
        tsig_algorithm=config.tsig_algorithm,
        tsig_configured=bool(config.tsig_secret),
        interval_minutes=config.interval_minutes,
        last_sync_at=config.last_sync_at,
        last_error=config.last_error,
    )


@router.get("/config", response_model=AxfrDnsConfigResponse)
def get_config(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AxfrDnsConfigResponse:
    return _config_response(get_axfr_dns_config(db))


@router.put("/config", response_model=AxfrDnsConfigResponse)
def update_config(
    data: AxfrDnsConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AxfrDnsConfigResponse:
    if data.enabled and (not data.server.strip() or not data.zones):
        raise HTTPException(status_code=400, detail="AXFR DNS server and at least one zone are required")
    if data.tsig_algorithm not in TSIG_ALGORITHMS:
        raise HTTPException(status_code=400, detail="Unsupported TSIG algorithm")
    current = get_axfr_dns_config(db)
    tsig_secret = None if data.clear_tsig_secret else (data.tsig_secret or current.tsig_secret)
    config = AxfrDnsConfig(
        dns_names_enabled=data.dns_names_enabled,
        enabled=data.enabled,
        server=data.server,
        zones=data.zones,
        port=max(1, min(65535, data.port)),
        timeout_seconds=max(3, min(120, data.timeout_seconds)),
        tsig_key_name=data.tsig_key_name,
        tsig_secret=tsig_secret,
        tsig_algorithm=data.tsig_algorithm,
        interval_minutes=max(5, data.interval_minutes),
    )
    save_axfr_dns_config(db, config)
    db.commit()
    from ..services.dns_names_scheduler import update_dns_names_schedule
    update_dns_names_schedule()
    return _config_response(get_axfr_dns_config(db))


@router.post("/test")
def test_connection(
    data: AxfrDnsConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if data.tsig_algorithm not in TSIG_ALGORITHMS:
        raise HTTPException(status_code=400, detail="Unsupported TSIG algorithm")
    current = get_axfr_dns_config(db)
    config = AxfrDnsConfig(
        dns_names_enabled=data.dns_names_enabled,
        enabled=True,
        server=data.server,
        zones=data.zones,
        port=max(1, min(65535, data.port)),
        timeout_seconds=max(3, min(120, data.timeout_seconds)),
        tsig_key_name=data.tsig_key_name,
        tsig_secret=None if data.clear_tsig_secret else (data.tsig_secret or current.tsig_secret),
        tsig_algorithm=data.tsig_algorithm,
        interval_minutes=max(5, data.interval_minutes),
    )
    try:
        from ..services.dns_names import fetch_axfr_dns_records
        records = fetch_axfr_dns_records(config)
    except Exception as exc:
        logger.warning("AXFR connection test failed: %s", exc)
        raise HTTPException(status_code=502, detail=_safe_error(exc))
    return {"ok": True, "records": len(records), "zones": len(config.zones or [])}


@router.post("/sync")
def synchronize(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    config = get_axfr_dns_config(db)
    try:
        return {"ok": True, **synchronize_axfr_dns(db, config)}
    except Exception as exc:
        from ..services.dns_names import _set_setting
        logger.warning("AXFR synchronization failed: %s", exc)
        _set_setting(db, "axfr_dns_last_error", _safe_error(exc))
        db.commit()
        raise HTTPException(status_code=502, detail=_safe_error(exc))


@router.get("/devices/{device_id}", response_model=list[DeviceDnsNameResponse])
def list_device_names(
    device_id: int,
    refresh: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DeviceDnsNameResponse]:
    config = get_axfr_dns_config(db)
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
