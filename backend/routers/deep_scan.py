"""Deep scan trigger, configuration, run history, and findings retrieval."""

import json
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import (
    Device,
    DeviceDeepScanConfig,
    DeviceHostRelationship,
    DeepScanFinding,
    DeepScanRun,
    User,
)
from ..schemas import (
    DeepScanConfigResponse,
    DeepScanConfigUpdate,
    DeepScanFindingResponse,
    DeepScanRunResponse,
    DeviceHostRelationshipResponse,
    ManualRelationshipCreate,
    MessageResponse,
    SCAN_PROFILES,
)
from ..services.deep_scanner import run_deep_scan

router = APIRouter(prefix="/api/devices/{device_id}/deep-scan", tags=["deep_scan"])


def _get_device_or_404(device_id: int, db: Session) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


def _get_or_create_config(device_id: int, db: Session) -> DeviceDeepScanConfig:
    config = db.query(DeviceDeepScanConfig).filter(
        DeviceDeepScanConfig.device_id == device_id
    ).first()
    if not config:
        config = DeviceDeepScanConfig(device_id=device_id)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def _run_to_response(run: DeepScanRun) -> DeepScanRunResponse:
    summary = None
    if run.summary_json:
        try:
            summary = json.loads(run.summary_json)
        except (json.JSONDecodeError, TypeError):
            summary = run.summary_json
    return DeepScanRunResponse(
        id=run.id,
        device_id=run.device_id,
        credential_id=run.credential_id,
        profile=run.profile,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        summary=summary,
        error_message=run.error_message,
        triggered_by=run.triggered_by,
    )


def _finding_to_response(f: DeepScanFinding) -> DeepScanFindingResponse:
    value = None
    if f.value_json:
        try:
            value = json.loads(f.value_json)
        except (json.JSONDecodeError, TypeError):
            value = f.value_json
    return DeepScanFindingResponse(
        id=f.id,
        device_id=f.device_id,
        run_id=f.run_id,
        finding_type=f.finding_type,
        key=f.key,
        value=value,
        source=f.source,
        observed_at=f.observed_at,
    )


# ── Config ────────────────────────────────────────────────────────────────────

@router.get("/config", response_model=DeepScanConfigResponse)
def get_deep_scan_config(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DeepScanConfigResponse:
    _get_device_or_404(device_id, db)
    config = _get_or_create_config(device_id, db)
    return DeepScanConfigResponse(
        device_id=config.device_id,
        enabled=config.enabled,
        credential_id=config.credential_id,
        scan_profile=config.scan_profile,
        auto_scan_enabled=config.auto_scan_enabled,
        interval_minutes=config.interval_minutes,
        last_scan_at=config.last_scan_at,
    )


@router.put("/config", response_model=DeepScanConfigResponse)
def update_deep_scan_config(
    device_id: int,
    data: DeepScanConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DeepScanConfigResponse:
    _get_device_or_404(device_id, db)

    if data.scan_profile is not None and data.scan_profile not in SCAN_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scan_profile. Must be one of: {SCAN_PROFILES}",
        )
    if data.interval_minutes is not None and data.interval_minutes < 5:
        raise HTTPException(status_code=400, detail="interval_minutes must be >= 5")

    config = _get_or_create_config(device_id, db)

    # Use model_fields_set so credential_id: null can explicitly clear the assignment
    fields = data.model_fields_set

    if "enabled" in fields and data.enabled is not None:
        config.enabled = data.enabled
    if "credential_id" in fields:
        # null means "no credential assigned" — allowed to unset
        config.credential_id = data.credential_id
    if "scan_profile" in fields and data.scan_profile is not None:
        config.scan_profile = data.scan_profile
    if "auto_scan_enabled" in fields and data.auto_scan_enabled is not None:
        config.auto_scan_enabled = data.auto_scan_enabled
    if "interval_minutes" in fields and data.interval_minutes is not None:
        config.interval_minutes = data.interval_minutes

    db.commit()
    db.refresh(config)
    return DeepScanConfigResponse(
        device_id=config.device_id,
        enabled=config.enabled,
        credential_id=config.credential_id,
        scan_profile=config.scan_profile,
        auto_scan_enabled=config.auto_scan_enabled,
        interval_minutes=config.interval_minutes,
        last_scan_at=config.last_scan_at,
    )


# ── Run trigger ───────────────────────────────────────────────────────────────

@router.post("/run", response_model=MessageResponse)
async def trigger_deep_scan(
    device_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MessageResponse:
    device = _get_device_or_404(device_id, db)

    if not device.ip_address:
        raise HTTPException(status_code=400, detail="Device has no IP address to scan")

    config = _get_or_create_config(device_id, db)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Deep scan is not enabled for this device")
    if not config.credential_id:
        raise HTTPException(
            status_code=400, detail="No credential assigned. Configure the deep scan first."
        )

    # Prevent concurrent scans for the same device
    running = (
        db.query(DeepScanRun)
        .filter(DeepScanRun.device_id == device_id, DeepScanRun.status == "running")
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail="A deep scan is already running for this device")

    background_tasks.add_task(run_deep_scan, device_id, "manual")
    return MessageResponse(message="Deep scan started")


# ── Run history ───────────────────────────────────────────────────────────────

@router.get("/runs", response_model=List[DeepScanRunResponse])
def list_runs(
    device_id: int,
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[DeepScanRunResponse]:
    _get_device_or_404(device_id, db)
    runs = (
        db.query(DeepScanRun)
        .filter(DeepScanRun.device_id == device_id)
        .order_by(DeepScanRun.started_at.desc())
        .limit(limit)
        .all()
    )
    return [_run_to_response(r) for r in runs]


@router.get("/runs/{run_id}", response_model=DeepScanRunResponse)
def get_run(
    device_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DeepScanRunResponse:
    _get_device_or_404(device_id, db)
    run = (
        db.query(DeepScanRun)
        .filter(DeepScanRun.id == run_id, DeepScanRun.device_id == device_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return _run_to_response(run)


# ── Findings ──────────────────────────────────────────────────────────────────

@router.get("/findings", response_model=List[DeepScanFindingResponse])
def get_findings(
    device_id: int,
    finding_type: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[DeepScanFindingResponse]:
    _get_device_or_404(device_id, db)

    # Return findings from the latest completed run (or all if no filter)
    latest_run = (
        db.query(DeepScanRun)
        .filter(DeepScanRun.device_id == device_id, DeepScanRun.status == "done")
        .order_by(DeepScanRun.started_at.desc())
        .first()
    )
    if not latest_run:
        return []

    q = db.query(DeepScanFinding).filter(
        DeepScanFinding.device_id == device_id,
        DeepScanFinding.run_id == latest_run.id,
    )
    if finding_type:
        q = q.filter(DeepScanFinding.finding_type == finding_type)
    findings = q.order_by(DeepScanFinding.finding_type, DeepScanFinding.key).all()
    return [_finding_to_response(f) for f in findings]


# ── Host/Guest relationships ───────────────────────────────────────────────────

@router.get("/relationships", response_model=List[DeviceHostRelationshipResponse])
def get_relationships(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[DeviceHostRelationshipResponse]:
    _get_device_or_404(device_id, db)
    rels = (
        db.query(DeviceHostRelationship)
        .filter(
            (DeviceHostRelationship.child_device_id == device_id)
            | (DeviceHostRelationship.host_device_id == device_id)
        )
        .all()
    )
    return [
        DeviceHostRelationshipResponse(
            id=r.id,
            child_device_id=r.child_device_id,
            host_device_id=r.host_device_id,
            relationship_type=r.relationship_type,
            match_source=r.match_source,
            vm_identifier=r.vm_identifier,
            observed_at=r.observed_at,
            last_confirmed_at=r.last_confirmed_at,
        )
        for r in rels
    ]


@router.post("/relationships", response_model=DeviceHostRelationshipResponse, status_code=201)
def create_manual_relationship(
    device_id: int,
    data: ManualRelationshipCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DeviceHostRelationshipResponse:
    """Manually link this device (as guest/VM) to a host device."""
    _get_device_or_404(device_id, db)
    host = db.query(Device).filter(Device.id == data.host_device_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host device not found")
    if data.host_device_id == device_id:
        raise HTTPException(status_code=400, detail="A device cannot be its own host")

    # Check for existing relationship
    existing = db.query(DeviceHostRelationship).filter(
        DeviceHostRelationship.child_device_id == device_id,
        DeviceHostRelationship.host_device_id == data.host_device_id,
    ).first()

    from datetime import datetime as _dt
    if existing:
        # Update vm_identifier if provided
        if data.vm_identifier is not None:
            existing.vm_identifier = data.vm_identifier
        existing.match_source = "manual"
        existing.last_confirmed_at = _dt.utcnow()
        db.commit()
        db.refresh(existing)
        rel = existing
    else:
        rel = DeviceHostRelationship(
            child_device_id=device_id,
            host_device_id=data.host_device_id,
            relationship_type="vm_on_host",
            match_source="manual",
            vm_identifier=data.vm_identifier,
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)

    return DeviceHostRelationshipResponse(
        id=rel.id,
        child_device_id=rel.child_device_id,
        host_device_id=rel.host_device_id,
        relationship_type=rel.relationship_type,
        match_source=rel.match_source,
        vm_identifier=rel.vm_identifier,
        observed_at=rel.observed_at,
        last_confirmed_at=rel.last_confirmed_at,
    )


@router.delete("/relationships/{rel_id}", response_model=MessageResponse)
def delete_relationship(
    device_id: int,
    rel_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MessageResponse:
    """Delete a host/guest relationship (manual or auto-detected)."""
    _get_device_or_404(device_id, db)
    rel = db.query(DeviceHostRelationship).filter(
        DeviceHostRelationship.id == rel_id,
        (DeviceHostRelationship.child_device_id == device_id)
        | (DeviceHostRelationship.host_device_id == device_id),
    ).first()
    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    db.delete(rel)
    db.commit()
    return MessageResponse(message="Relationship deleted")
