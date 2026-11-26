"""Outbound Windows and Linux inventory-agent enrolment and reporting API.

The agent opens HTTPS connections to LanLens.  LanLens never opens a WinRM
connection to an enrolled endpoint, which also makes remote/off-LAN inventory
possible when the endpoint can reach the configured public LanLens URL.
"""

import hashlib
import ipaddress
import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import AgentEnrollmentToken, DeepScanFinding, DeepScanRun, Device, DeviceChangeEvent, User, WindowsAgent
from ..schemas import AgentEnrollmentTokenCreate, AgentEnrollmentTokenCreated, AgentEnrollmentTokenResponse
from ..services.inventory_timeline import record_inventory_changes

router = APIRouter(prefix="/api/agents", tags=["agents"])
_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "windows_agent"
_MAX_SOFTWARE_ITEMS = 2000
_MAX_FINDING_BYTES = 160_000
_MAX_REPORT_BYTES = 900_000
_MIN_REPORT_INTERVAL = timedelta(seconds=30)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalise_mac(value: str) -> str:
    compact = re.sub(r"[^0-9a-fA-F]", "", value or "")
    if len(compact) != 12:
        return ""
    return ":".join(compact[index:index + 2].upper() for index in range(0, 12, 2))


def _token_response(token: AgentEnrollmentToken) -> AgentEnrollmentTokenResponse:
    return AgentEnrollmentTokenResponse(
        id=token.id, name=token.name, expires_at=token.expires_at,
        revoked_at=token.revoked_at, created_at=token.created_at,
        last_used_at=token.last_used_at,
    )


@router.get("/enrollment-tokens", response_model=list[AgentEnrollmentTokenResponse])
def list_enrollment_tokens(
    db: Session = Depends(get_db), _: User = Depends(get_current_user),
) -> list[AgentEnrollmentTokenResponse]:
    tokens = db.query(AgentEnrollmentToken).order_by(AgentEnrollmentToken.created_at.desc()).all()
    return [_token_response(token) for token in tokens]


@router.post("/enrollment-tokens", response_model=AgentEnrollmentTokenCreated, status_code=201)
def create_enrollment_token(
    data: AgentEnrollmentTokenCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AgentEnrollmentTokenCreated:
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Token name must not be empty")
    if data.expires_in_minutes is not None and not 1 <= data.expires_in_minutes <= 5256000:
        raise HTTPException(status_code=400, detail="expires_in_minutes must be between 1 and 5256000")
    raw_token = secrets.token_urlsafe(32)
    token = AgentEnrollmentToken(
        name=name,
        token_hash=_sha256(raw_token),
        expires_at=(datetime.utcnow() + timedelta(minutes=data.expires_in_minutes)) if data.expires_in_minutes else None,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    response = _token_response(token).model_dump()
    return AgentEnrollmentTokenCreated(**response, token=raw_token)


@router.post("/enrollment-tokens/{token_id}/revoke", response_model=AgentEnrollmentTokenResponse)
def revoke_enrollment_token(
    token_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user),
) -> AgentEnrollmentTokenResponse:
    token = db.query(AgentEnrollmentToken).filter(AgentEnrollmentToken.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Enrollment token not found")
    if token.revoked_at is None:
        now = datetime.utcnow()
        # Lock the token row before touching agents, serializing against enrollment.
        db.query(AgentEnrollmentToken).filter(AgentEnrollmentToken.id == token.id,
                                              AgentEnrollmentToken.revoked_at.is_(None)).update(
            {AgentEnrollmentToken.revoked_at: now}, synchronize_session=False)
        db.query(WindowsAgent).filter(WindowsAgent.enrollment_token_id == token.id,
                                     WindowsAgent.revoked_at.is_(None)).update(
            {WindowsAgent.revoked_at: now}, synchronize_session=False)
        db.commit()
        db.refresh(token)
    return _token_response(token)


class AgentEnrollRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    hostname: str = Field(min_length=1, max_length=255)
    primary_mac: str = Field(min_length=12, max_length=32)
    os_info: Optional[str] = Field(default=None, max_length=255)
    kernel_version: Optional[str] = Field(default=None, max_length=255)
    ip_addresses: list[str] = Field(default_factory=list, max_length=64)
    platform: Literal["windows", "linux"] = "windows"

    @field_validator("ip_addresses")
    @classmethod
    def validate_ips(cls, values):
        return [str(ipaddress.ip_address(value)) for value in values]


class AgentFinding(BaseModel):
    finding_type: Literal["hardware", "os", "software", "service", "container", "audit", "hypervisor"]
    key: str = Field(min_length=1, max_length=256)
    value: Any = None
    source: Optional[str] = Field(default=None, max_length=64)

    @field_validator("value")
    @classmethod
    def validate_size(cls, value):
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > _MAX_FINDING_BYTES:
            raise ValueError("Finding exceeds maximum size")
        return value


class AgentReportRequest(BaseModel):
    sequence: int = Field(ge=1)
    hostname: str = Field(min_length=1, max_length=255)
    primary_mac: str = Field(min_length=12, max_length=32)
    os_info: Optional[str] = Field(default=None, max_length=255)
    kernel_version: Optional[str] = Field(default=None, max_length=255)
    ip_addresses: list[str] = Field(default_factory=list, max_length=64)
    software: list[dict[str, Any]] = Field(default_factory=list, max_length=_MAX_SOFTWARE_ITEMS)
    findings: list[AgentFinding] = Field(default_factory=list, max_length=128)
    platform: Literal["windows", "linux"] = "windows"

    @field_validator("ip_addresses")
    @classmethod
    def validate_ips(cls, values):
        return [str(ipaddress.ip_address(value)) for value in values]

    @model_validator(mode="after")
    def validate_inventory(self):
        if len(self.model_dump_json().encode("utf-8")) > _MAX_REPORT_BYTES:
            raise ValueError("Inventory report exceeds maximum size")
        return self


def _active_token(raw_token: str, db: Session) -> AgentEnrollmentToken:
    token = db.query(AgentEnrollmentToken).filter(AgentEnrollmentToken.token_hash == _sha256(raw_token)).first()
    if not token or token.revoked_at is not None or token.last_used_at is not None or (token.expires_at and token.expires_at <= datetime.utcnow()):
        raise HTTPException(status_code=401, detail="Invalid, used, expired, or revoked enrollment token")
    return token


def _find_or_create_device(payload: AgentEnrollRequest | AgentReportRequest, db: Session) -> Device:
    mac_address = _normalise_mac(payload.primary_mac)
    if not mac_address:
        raise HTTPException(status_code=400, detail="A valid primary MAC address is required")
    device = db.query(Device).filter(Device.mac_address == mac_address).first()
    primary_ip = next((ip for ip in payload.ip_addresses if len(ip) <= 45), None)
    if device is None:
        device = Device(
            mac_address=mac_address, hostname=payload.hostname.strip(), ip_address=primary_ip,
            os_info=payload.os_info, kernel_version=payload.kernel_version,
            device_class="Windows Server" if payload.platform == "windows" else "Linux Server",
            is_registered=True, is_online=True,
        )
        db.add(device)
        db.flush()
    else:
        device.hostname = payload.hostname.strip() or device.hostname
        device.ip_address = primary_ip or device.ip_address
        device.os_info = payload.os_info or device.os_info
        device.kernel_version = payload.kernel_version or device.kernel_version
        device.is_online = True
        device.last_seen = datetime.utcnow()
    return device


@router.post("/enroll")
def enroll_agent(payload: AgentEnrollRequest, db: Session = Depends(get_db)) -> dict[str, str | int]:
    token = _active_token(payload.token, db)
    now = datetime.utcnow()
    # Consume the token atomically; the transaction rolls back on enrollment failure.
    consumed = db.query(AgentEnrollmentToken).filter(
        AgentEnrollmentToken.id == token.id, AgentEnrollmentToken.last_used_at.is_(None),
        AgentEnrollmentToken.revoked_at.is_(None),
        or_(AgentEnrollmentToken.expires_at.is_(None), AgentEnrollmentToken.expires_at > now),
    ).update({AgentEnrollmentToken.last_used_at: now}, synchronize_session=False)
    if consumed != 1:
        db.rollback()
        raise HTTPException(status_code=401, detail="Enrollment token is no longer valid")
    device = _find_or_create_device(payload, db)
    agent = db.query(WindowsAgent).filter(WindowsAgent.device_id == device.id).first()
    if agent is not None and agent.revoked_at is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Revoke the existing agent's enrollment token before re-enrolling")
    agent_id = secrets.token_urlsafe(18)
    agent_secret = secrets.token_urlsafe(32)
    if agent is None:
        agent = WindowsAgent(
            agent_id=agent_id, device_id=device.id, enrollment_token_id=token.id,
            platform=payload.platform, secret_hash=_sha256(f"{agent_id}.{agent_secret}"),
        )
        db.add(agent)
    else:
        replaced = db.query(WindowsAgent).filter(WindowsAgent.id == agent.id, WindowsAgent.revoked_at.is_not(None)).update({
            WindowsAgent.agent_id: agent_id, WindowsAgent.enrollment_token_id: token.id,
            WindowsAgent.secret_hash: _sha256(f"{agent_id}.{agent_secret}"), WindowsAgent.platform: payload.platform,
            WindowsAgent.last_sequence: 0, WindowsAgent.last_seen_at: None, WindowsAgent.revoked_at: None,
        }, synchronize_session=False)
        if replaced != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Agent identity already replaced")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Agent identity already exists")
    return {"agent_id": agent_id, "agent_secret": agent_secret, "device_id": device.id, "report_path": "/api/agents/report"}


def _authenticated_agent(authorization: Optional[str], db: Session) -> WindowsAgent:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Agent authentication required")
    credential = authorization[7:].strip()
    if "." not in credential:
        raise HTTPException(status_code=401, detail="Invalid agent authentication")
    agent_id, _ = credential.split(".", 1)
    agent = db.query(WindowsAgent).filter(WindowsAgent.agent_id == agent_id).first()
    if not agent or agent.revoked_at is not None or not secrets.compare_digest(agent.secret_hash, _sha256(credential)):
        raise HTTPException(status_code=401, detail="Invalid or revoked agent")
    return agent


@router.post("/unenroll")
def unenroll_agent(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    agent = _authenticated_agent(authorization, db)
    now = datetime.utcnow()
    changed = db.query(WindowsAgent).filter(WindowsAgent.id == agent.id,
        WindowsAgent.agent_id == agent.agent_id, WindowsAgent.revoked_at.is_(None)).update(
        {WindowsAgent.revoked_at: now}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Agent identity changed")
    if agent.enrollment_token_id:
        db.query(AgentEnrollmentToken).filter(AgentEnrollmentToken.id == agent.enrollment_token_id,
            AgentEnrollmentToken.revoked_at.is_(None)).update({AgentEnrollmentToken.revoked_at: now}, synchronize_session=False)
    db.add(DeviceChangeEvent(device_id=agent.device_id, event_type="agent_unenrolled",
        source=f"lanlens_{agent.platform or 'windows'}_agent", message="Agent registration revoked by local uninstall"))
    db.commit()
    return {"status": "revoked"}


@router.post("/report")
def report_agent_inventory(
    payload: AgentReportRequest,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    agent = _authenticated_agent(authorization, db)
    if payload.sequence <= agent.last_sequence:
        raise HTTPException(status_code=409, detail="Stale or replayed agent report")
    device = db.get(Device, agent.device_id)
    if device is None or device.mac_address != _normalise_mac(payload.primary_mac):
        raise HTTPException(status_code=409, detail="Agent identity does not match the reported device")
    if agent.platform is not None and agent.platform != payload.platform:
        raise HTTPException(status_code=409, detail="Agent platform does not match enrollment")
    now = datetime.utcnow()
    if agent.last_seen_at and now - agent.last_seen_at < _MIN_REPORT_INTERVAL:
        raise HTTPException(status_code=429, detail="Agent reporting too frequently")
    # Compare-and-set guards against concurrent reports and concurrent revocation.
    updated = db.query(WindowsAgent).filter(
        WindowsAgent.id == agent.id, WindowsAgent.agent_id == agent.agent_id,
        WindowsAgent.revoked_at.is_(None), WindowsAgent.last_sequence == agent.last_sequence,
    ).update({WindowsAgent.last_sequence: payload.sequence, WindowsAgent.last_seen_at: now,
              WindowsAgent.platform: payload.platform}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Agent identity or sequence changed")
    previous_identity = {field: getattr(device, field) for field in ("hostname", "ip_address", "os_info", "kernel_version")}
    device = _find_or_create_device(payload, db)
    identity_changes = [f"device/{field}" for field, old in previous_identity.items() if getattr(device, field) != old]
    run = DeepScanRun(
        device_id=device.id, profile=f"{payload.platform}_agent", status="done", triggered_by="agent",
        finished_at=datetime.utcnow(), summary_json=json.dumps({
            "software_count": len(payload.software), "finding_count": len(payload.findings),
            "transport": "outbound_agent", "platform": payload.platform,
        }),
    )
    db.add(run)
    db.flush()
    source = f"lanlens_{payload.platform}_agent"
    findings = [
        DeepScanFinding(device_id=device.id, run_id=run.id, finding_type="os", key="operating_system",
                        value_json=json.dumps({"name": payload.os_info, "kernel": payload.kernel_version}), source=source),
        DeepScanFinding(device_id=device.id, run_id=run.id, finding_type="software", key="installed_software",
                        value_json=json.dumps(payload.software), source=source),
    ]
    seen = {("os", "operating_system"), ("software", "installed_software")}
    for finding in payload.findings:
        identity = (finding.finding_type, finding.key)
        if identity in seen:
            continue
        seen.add(identity)
        findings.append(DeepScanFinding(
            device_id=device.id, run_id=run.id, finding_type=finding.finding_type,
            key=finding.key, value_json=json.dumps(finding.value), source=source,
        ))
    db.add_all(findings)
    changed = record_inventory_changes(db, run, f"{payload.platform}_agent", source)
    for field, before in previous_identity.items():
        after = getattr(device, field)
        if before != after:
            db.add(DeviceChangeEvent(device_id=device.id, event_type="inventory_finding_changed",
                field_name=field, old_value=before, new_value=after, source=source,
                message=f"Scan #{run.id}: device field updated"))
    changed.extend(identity_changes)
    # Existing installations may already have accepted reports but no timeline
    # entries from older builds. Record the next report once, even if identical.
    recorded = (db.query(DeviceChangeEvent.id).filter_by(device_id=device.id,
                source=source, event_type="agent_inventory_received").first())
    if not recorded or changed:
        message = ("First recorded inventory report accepted" if not recorded else "Agent inventory changed")
        message += f"; scan #{run.id}; {len(findings)} findings; {len(payload.software)} applications"
        if changed:
            message += "; changed: " + ", ".join(changed[:20])[:1000]
        db.add(DeviceChangeEvent(device_id=device.id, event_type="agent_inventory_received",
                                 source=source, message=message, created_at=now))
    db.commit()
    return {"status": "accepted", "device_id": device.id, "run_id": run.id,
            "finding_count": len(findings), "software_count": len(payload.software), "changed_count": len(changed)}


@router.get("/windows/uninstall.ps1", response_class=PlainTextResponse)
def windows_uninstall_script() -> PlainTextResponse:
    return FileResponse(_ASSET_DIR / "uninstall.ps1", media_type="text/plain; charset=utf-8")


@router.get("/windows/install.ps1", response_class=PlainTextResponse)
def windows_install_script() -> PlainTextResponse:
    return FileResponse(_ASSET_DIR / "install.ps1", media_type="text/plain; charset=utf-8")


@router.get("/windows/LanLensAgent.cs", response_class=PlainTextResponse)
def windows_agent_source() -> PlainTextResponse:
    return FileResponse(_ASSET_DIR / "LanLensAgent.cs", media_type="text/plain; charset=utf-8")


@router.get("/linux/install.sh", response_class=PlainTextResponse)
def linux_install_script() -> PlainTextResponse:
    asset_dir = Path(__file__).resolve().parents[1] / "assets" / "linux_agent"
    return FileResponse(asset_dir / "install.sh", media_type="text/plain; charset=utf-8")


@router.get("/linux/lanlens-agent.py", response_class=PlainTextResponse)
def linux_agent_source() -> PlainTextResponse:
    asset_dir = Path(__file__).resolve().parents[1] / "assets" / "linux_agent"
    return FileResponse(asset_dir / "lanlens-agent.py", media_type="text/plain; charset=utf-8")
