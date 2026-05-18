import hashlib
import re
import secrets
import shlex
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, DeviceChangeEvent, ScanNode, Segment, Setting, User
from ..services.device_classifier import classify_device
from ..services.mac_vendor import lookup_vendor, normalize_mac
from ..services.scanner import _find_matching_segment, _is_ip_only_identifier, _pseudo_mac_for_ip, record_device_ip_history

router = APIRouter(prefix="/api/scan-nodes", tags=["scan-nodes"])

SCAN_NODE_IMAGE = "alexrosbach/lanlens-scan-node:dev"


class ScanNodeCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    site: Optional[str] = Field(default="", max_length=128)
    segment_label: Optional[str] = Field(default="", max_length=128)


class ScanNodeHost(BaseModel):
    ip: str
    mac: Optional[str] = None
    hostname: Optional[str] = None


class ScanNodeIngest(BaseModel):
    version: Optional[str] = None
    hosts: list[ScanNodeHost] = Field(default_factory=list, max_length=4096)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _node_response(node: ScanNode) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "site": node.site or "",
        "segment_label": node.segment_label or "",
        "enabled": node.enabled,
        "status": node.status,
        "last_seen": node.last_seen,
        "last_ip": node.last_ip,
        "version": node.version,
        "last_error": node.last_error,
        "created_at": node.created_at,
    }


def _central_url(db: Session) -> str:
    row = db.query(Setting).filter(Setting.key == "server_url").first()
    return (row.value if row and row.value else "https://lanlens.example.com").rstrip("/")


def _install_command(db: Session, node: ScanNode, token: str) -> str:
    central_url = _central_url(db)
    container_suffix = re.sub(r"[^a-zA-Z0-9_.-]+", "-", node.name).strip("-") or str(node.id)
    parts = [
        "docker", "run", "-d",
        "--name", f"lanlens-scan-node-{container_suffix}",
        "--restart", "unless-stopped",
        "--network", "host",
        "--cap-add", "NET_RAW",
        "--cap-add", "NET_ADMIN",
        "-e", f"LANLENS_CENTRAL_URL={central_url}",
        "-e", f"LANLENS_NODE_TOKEN={token}",
        "-e", f"LANLENS_NODE_NAME={node.name}",
        SCAN_NODE_IMAGE,
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _extract_token(authorization: Optional[str], node_token: Optional[str]) -> str:
    if node_token:
        return node_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


@router.get("")
def list_scan_nodes(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    nodes = db.query(ScanNode).order_by(ScanNode.name.asc()).all()
    return [_node_response(node) for node in nodes]


@router.post("")
def create_scan_node(payload: ScanNodeCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    name = payload.name.strip()
    if db.query(ScanNode).filter(ScanNode.name == name).first():
        raise HTTPException(status_code=409, detail="Scan node name already exists")
    token = secrets.token_urlsafe(32)
    node = ScanNode(
        name=name,
        site=(payload.site or "").strip(),
        segment_label=(payload.segment_label or "").strip(),
        token_hash=_hash_token(token),
        status="pending",
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return {**_node_response(node), "token": token, "install_command": _install_command(db, node, token)}


@router.post("/{node_id}/rotate-token")
def rotate_scan_node_token(node_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    node = db.query(ScanNode).filter(ScanNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Scan node not found")
    token = secrets.token_urlsafe(32)
    node.token_hash = _hash_token(token)
    node.status = "pending"
    node.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(node)
    return {**_node_response(node), "token": token, "install_command": _install_command(db, node, token)}


@router.delete("/{node_id}")
def delete_scan_node(node_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    node = db.query(ScanNode).filter(ScanNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Scan node not found")
    db.delete(node)
    db.commit()
    return {"message": "Scan node deleted"}


@router.post("/ingest")
def ingest_scan_node_results(
    payload: ScanNodeIngest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_lanlens_node_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    token = _extract_token(authorization, x_lanlens_node_token)
    if not token:
        raise HTTPException(status_code=401, detail="Missing scan node token")
    node = db.query(ScanNode).filter(ScanNode.token_hash == _hash_token(token)).first()
    if not node or not node.enabled:
        raise HTTPException(status_code=403, detail="Invalid or disabled scan node token")

    now = datetime.utcnow()
    segments = db.query(Segment).all()
    devices_seen = 0
    devices_new = 0

    for host in payload.hosts:
        ip = host.ip.strip()
        if not ip:
            continue
        mac = normalize_mac(host.mac) if host.mac else None
        existing = db.query(Device).filter(Device.mac_address == mac).first() if mac else None
        if existing is None:
            existing = db.query(Device).filter(Device.ip_address == ip).first()
        mac_or_identifier = mac or (existing.mac_address if existing else _pseudo_mac_for_ip(ip))

        if mac and existing and _is_ip_only_identifier(existing.mac_address):
            existing.mac_address = mac
            mac_or_identifier = mac

        hostname = (host.hostname or "").strip() or None
        vendor = lookup_vendor(mac) if mac else None
        segment = _find_matching_segment(segments, ip)

        if existing is None:
            existing = Device(
                mac_address=mac_or_identifier,
                ip_address=ip,
                hostname=hostname,
                vendor=vendor,
                device_class=classify_device(vendor or "", hostname or ""),
                is_online=True,
                first_seen=now,
                last_seen=now,
                segment_id=segment.id if segment else None,
            )
            db.add(existing)
            db.flush()
            db.add(DeviceChangeEvent(
                device_id=existing.id,
                event_type="device_discovered",
                source="scan_node",
                message=f"Discovered by scan node {node.name} at {ip}",
            ))
            devices_new += 1
        else:
            if existing.ip_address != ip:
                db.add(DeviceChangeEvent(device_id=existing.id, event_type="field_changed", field_name="ip_address", old_value=existing.ip_address, new_value=ip, source="scan_node"))
                existing.ip_address = ip
            if hostname and existing.hostname != hostname:
                existing.hostname = hostname
            if vendor and existing.vendor != vendor:
                existing.vendor = vendor
            if segment and existing.segment_id != segment.id:
                existing.segment_id = segment.id
            existing.is_online = True
            existing.last_seen = now

        record_device_ip_history(db, existing, ip, now)
        devices_seen += 1

    node.status = "online"
    node.last_seen = now
    node.last_ip = request.client.host if request.client else None
    node.version = payload.version or node.version
    node.last_error = None
    node.updated_at = now
    db.commit()
    return {"status": "ok", "node_id": node.id, "devices_seen": devices_seen, "devices_new": devices_new}
