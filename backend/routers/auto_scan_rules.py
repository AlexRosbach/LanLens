"""
CRUD endpoints for global auto-scan rules.

Rules are evaluated by poll_auto_scans() every 60 s and trigger deep scans for all
matching devices (by device_class, or all classes when device_class is NULL) that have
not been scanned within the rule's interval.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import AutoScanRule, Credential, User
from ..schemas import AutoScanRuleCreate, AutoScanRuleResponse, AutoScanRuleUpdate, MessageResponse, SCAN_PROFILES

router = APIRouter(prefix="/api/auto-scan-rules", tags=["auto-scan-rules"])


@router.get("", response_model=List[AutoScanRuleResponse])
def list_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(AutoScanRule).order_by(AutoScanRule.created_at).all()


@router.post("", response_model=AutoScanRuleResponse)
def create_rule(
    data: AutoScanRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.query(Credential).filter(Credential.id == data.credential_id).first():
        raise HTTPException(status_code=404, detail="Credential not found")
    if data.interval_minutes < 5:
        raise HTTPException(status_code=400, detail="interval_minutes must be at least 5")
    if data.scan_profile not in SCAN_PROFILES:
        raise HTTPException(status_code=400, detail=f"Invalid scan_profile. Must be one of: {SCAN_PROFILES}")

    rule = AutoScanRule(
        name=data.name,
        device_class=data.device_class or None,
        credential_id=data.credential_id,
        scan_profile=data.scan_profile,
        interval_minutes=data.interval_minutes,
        enabled=data.enabled,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/{rule_id}", response_model=AutoScanRuleResponse)
def get_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(AutoScanRule).filter(AutoScanRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.put("/{rule_id}", response_model=AutoScanRuleResponse)
def update_rule(
    rule_id: int,
    data: AutoScanRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(AutoScanRule).filter(AutoScanRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Use model_fields_set so that an explicit `null` (e.g. device_class: null)
    # can clear a field, while a missing key leaves the field unchanged.
    fields = data.model_fields_set

    if "name" in fields and data.name is not None:
        rule.name = data.name
    if "device_class" in fields:
        # null means "all classes" — stored as NULL in DB
        rule.device_class = data.device_class or None
    if "credential_id" in fields and data.credential_id is not None:
        if not db.query(Credential).filter(Credential.id == data.credential_id).first():
            raise HTTPException(status_code=404, detail="Credential not found")
        rule.credential_id = data.credential_id
    if "scan_profile" in fields and data.scan_profile is not None:
        if data.scan_profile not in SCAN_PROFILES:
            raise HTTPException(status_code=400, detail=f"Invalid scan_profile. Must be one of: {SCAN_PROFILES}")
        rule.scan_profile = data.scan_profile
    if "interval_minutes" in fields and data.interval_minutes is not None:
        if data.interval_minutes < 5:
            raise HTTPException(status_code=400, detail="interval_minutes must be at least 5")
        rule.interval_minutes = data.interval_minutes
    if "enabled" in fields and data.enabled is not None:
        rule.enabled = data.enabled

    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", response_model=MessageResponse)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(AutoScanRule).filter(AutoScanRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return MessageResponse(message="Rule deleted")
