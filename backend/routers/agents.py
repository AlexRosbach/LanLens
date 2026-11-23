"""Outbound Windows inventory-agent enrolment and reporting API.

The agent opens HTTPS connections to LanLens.  LanLens never opens a WinRM
connection to an enrolled endpoint, which also makes remote/off-LAN inventory
possible when the endpoint can reach the configured public LanLens URL.
"""

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import AgentEnrollmentToken, DeepScanFinding, DeepScanRun, Device, User, WindowsAgent
from ..schemas import AgentEnrollmentTokenCreate, AgentEnrollmentTokenCreated, AgentEnrollmentTokenResponse

router = APIRouter(prefix="/api/agents", tags=["agents"])
_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "windows_agent"
_MAX_SOFTWARE_ITEMS = 2000


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
        token.revoked_at = datetime.utcnow()
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


class AgentReportRequest(BaseModel):
    sequence: int = Field(ge=1)
    hostname: str = Field(min_length=1, max_length=255)
    primary_mac: str = Field(min_length=12, max_length=32)
    os_info: Optional[str] = Field(default=None, max_length=255)
    kernel_version: Optional[str] = Field(default=None, max_length=255)
    ip_addresses: list[str] = Field(default_factory=list, max_length=64)
    software: list[dict[str, Any]] = Field(default_factory=list, max_length=_MAX_SOFTWARE_ITEMS)


def _active_token(raw_token: str, db: Session) -> AgentEnrollmentToken:
    token = db.query(AgentEnrollmentToken).filter(AgentEnrollmentToken.token_hash == _sha256(raw_token)).first()
    if not token or token.revoked_at is not None or (token.expires_at and token.expires_at <= datetime.utcnow()):
        raise HTTPException(status_code=401, detail="Invalid, expired, or revoked enrollment token")
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
            device_class="Windows Server", is_registered=True, is_online=True,
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
    device = _find_or_create_device(payload, db)
    agent = db.query(WindowsAgent).filter(WindowsAgent.device_id == device.id).first()
    agent_id = secrets.token_urlsafe(18)
    agent_secret = secrets.token_urlsafe(32)
    if agent is None:
        agent = WindowsAgent(
            agent_id=agent_id, device_id=device.id, enrollment_token_id=token.id,
            secret_hash=_sha256(f"{agent_id}.{agent_secret}"),
        )
        db.add(agent)
    else:
        agent.agent_id = agent_id
        agent.enrollment_token_id = token.id
        agent.secret_hash = _sha256(f"{agent_id}.{agent_secret}")
        agent.last_sequence = 0
        agent.revoked_at = None
    token.last_used_at = datetime.utcnow()
    db.commit()
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


@router.post("/report")
def report_agent_inventory(
    payload: AgentReportRequest,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    agent = _authenticated_agent(authorization, db)
    if payload.sequence <= agent.last_sequence:
        raise HTTPException(status_code=409, detail="Stale or replayed agent report")
    device = _find_or_create_device(payload, db)
    if device.id != agent.device_id:
        raise HTTPException(status_code=409, detail="Agent identity does not match the reported device")
    run = DeepScanRun(
        device_id=device.id, profile="windows_agent", status="done", triggered_by="agent",
        finished_at=datetime.utcnow(), summary_json=json.dumps({"software_count": len(payload.software), "transport": "outbound_agent"}),
    )
    db.add(run)
    db.flush()
    findings = [
        DeepScanFinding(device_id=device.id, run_id=run.id, finding_type="os", key="operating_system",
                        value_json=json.dumps({"name": payload.os_info, "kernel": payload.kernel_version}), source="lanlens_agent"),
        DeepScanFinding(device_id=device.id, run_id=run.id, finding_type="software", key="installed_software",
                        value_json=json.dumps(payload.software), source="lanlens_agent"),
    ]
    db.add_all(findings)
    agent.last_sequence = payload.sequence
    agent.last_seen_at = datetime.utcnow()
    db.commit()
    return {"status": "accepted", "device_id": device.id, "run_id": run.id}


@router.get("/windows/install.ps1", response_class=PlainTextResponse)
def windows_install_script() -> PlainTextResponse:
    return FileResponse(_ASSET_DIR / "install.ps1", media_type="text/plain; charset=utf-8")


@router.get("/windows/LanLensAgent.cs", response_class=PlainTextResponse)
def windows_agent_source() -> PlainTextResponse:
    return FileResponse(_ASSET_DIR / "LanLensAgent.cs", media_type="text/plain; charset=utf-8")
