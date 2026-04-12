import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Setting, User
from ..schemas import (
    AllSettings,
    DhcpSettings,
    MessageResponse,
    PortScanSettings,
    ScanRangeSettings,
    ScanScheduleSettings,
    ServerUrlSettings,
    TelegramSettings,
)
from ..services.notification import send_test_message, send_update_notification
from ..services.scheduler import update_interval
from ..services.scanner import _detect_host_network, _network_host_bounds

router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTING_KEYS = [
    "dhcp_start", "dhcp_end", "scan_start", "scan_end", "scan_interval_minutes",
    "port_scan_range",
    "telegram_bot_token", "telegram_chat_id", "telegram_enabled", "notify_telegram_update",
    "network_interface", "notify_on_device_online", "notify_on_device_offline",
    "server_url",
]


def _get(db: Session, key: str, default: Any = None) -> Any:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else default


def _set(db: Session, key: str, value: str):
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
        row.updated_at = datetime.utcnow()
    else:
        db.add(Setting(key=key, value=value, updated_at=datetime.utcnow()))


async def _fetch_latest_release_info() -> tuple[str, str]:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                "https://api.github.com/repos/AlexRosbach/LanLens/releases/latest",
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "lanlens-update-check",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if res.status_code != 200:
            raise HTTPException(status_code=502, detail="Could not fetch release info")
        data = res.json()
        latest = data.get("tag_name", "").lstrip("v")
        release_url = data.get("html_url", "https://github.com/AlexRosbach/LanLens/releases/latest")
        return latest, release_url
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"GitHub API error: {e}")


@router.get("", response_model=AllSettings)
def get_settings(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    try:
        interval_minutes = int(_get(db, "scan_interval_minutes", "5") or "5")
    except (ValueError, TypeError):
        interval_minutes = 5

    dhcp_start = _get(db, "dhcp_start", "192.168.1.1")
    dhcp_end = _get(db, "dhcp_end", "192.168.1.254")

    scan_start_row = db.query(Setting).filter(Setting.key == "scan_start").first()
    scan_end_row = db.query(Setting).filter(Setting.key == "scan_end").first()

    if scan_start_row and scan_end_row and scan_start_row.value and scan_end_row.value:
        effective_scan_start = scan_start_row.value
        effective_scan_end = scan_end_row.value
    else:
        detected_network = _detect_host_network()
        if detected_network:
            effective_scan_start, effective_scan_end = _network_host_bounds(detected_network)
        else:
            effective_scan_start = "192.168.1.1"
            effective_scan_end = "192.168.1.254"

    return AllSettings(
        dhcp_start=dhcp_start,
        dhcp_end=dhcp_end,
        scan_start=effective_scan_start,
        scan_end=effective_scan_end,
        scan_interval_minutes=interval_minutes,
        port_scan_range=_get(db, "port_scan_range", "top:1000") or "top:1000",
        telegram_bot_token=_get(db, "telegram_bot_token", ""),
        telegram_chat_id=_get(db, "telegram_chat_id", ""),
        telegram_enabled=_get(db, "telegram_enabled", "false") == "true",
        notify_telegram_update=_get(db, "notify_telegram_update", "false") == "true",
        network_interface=_get(db, "network_interface", ""),
        notify_on_device_online=_get(db, "notify_on_device_online", "false") == "true",
        notify_on_device_offline=_get(db, "notify_on_device_offline", "false") == "true",
        server_url=_get(db, "server_url", ""),
    )


@router.put("/dhcp", response_model=MessageResponse)
def update_dhcp(
    data: DhcpSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    import ipaddress
    try:
        start_ip = ipaddress.IPv4Address(data.dhcp_start)
        end_ip = ipaddress.IPv4Address(data.dhcp_end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid IP address: {e}")

    if int(start_ip) > int(end_ip):
        raise HTTPException(status_code=400, detail="DHCP start must be less than or equal to DHCP end")

    _set(db, "dhcp_start", data.dhcp_start)
    _set(db, "dhcp_end", data.dhcp_end)
    db.commit()
    return MessageResponse(message="DHCP range updated")


@router.put("/scan-range", response_model=MessageResponse)
def update_scan_range(
    data: ScanRangeSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    import ipaddress
    try:
        start_ip = ipaddress.IPv4Address(data.scan_start)
        end_ip = ipaddress.IPv4Address(data.scan_end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid IP address: {e}")

    if int(start_ip) > int(end_ip):
        raise HTTPException(status_code=400, detail="Scan start must be less than or equal to scan end")

    _set(db, "scan_start", data.scan_start)
    _set(db, "scan_end", data.scan_end)
    db.commit()
    return MessageResponse(message="Scan range updated")


@router.put("/scan-schedule", response_model=MessageResponse)
def update_scan_schedule(
    data: ScanScheduleSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if data.scan_interval_minutes < 1:
        raise HTTPException(status_code=400, detail="Interval must be at least 1 minute")
    _set(db, "scan_interval_minutes", str(data.scan_interval_minutes))
    db.commit()
    update_interval(data.scan_interval_minutes)
    return MessageResponse(message="Scan schedule updated")


@router.put("/port-scan", response_model=MessageResponse)
def update_port_scan_settings(
    data: PortScanSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Update the global port scan range used for all device scans."""
    spec = data.port_scan_range.strip()
    if not spec:
        raise HTTPException(status_code=400, detail="port_scan_range must not be empty")

    # Validate format: allow "top:N", digits, commas, hyphens only
    if not spec.startswith("top:"):
        sanitised = "".join(c for c in spec if c.isdigit() or c in ",-")
        if not sanitised:
            raise HTTPException(
                status_code=400,
                detail="Invalid port_scan_range. Use 'top:N', a range like '1-65535', or a list like '22,80,443'.",
            )

    _set(db, "port_scan_range", spec)
    db.commit()
    return MessageResponse(message="Port scan settings updated")


@router.put("/telegram", response_model=MessageResponse)
def update_telegram(
    data: TelegramSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _set(db, "telegram_bot_token", data.telegram_bot_token)
    _set(db, "telegram_chat_id", data.telegram_chat_id)
    _set(db, "telegram_enabled", "true" if data.telegram_enabled else "false")
    _set(db, "notify_telegram_update", "true" if data.notify_telegram_update else "false")
    db.commit()
    return MessageResponse(message="Telegram settings updated")


@router.put("/server-url", response_model=MessageResponse)
def update_server_url(
    data: ServerUrlSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    url = data.server_url.rstrip("/")
    _set(db, "server_url", url)
    db.commit()
    return MessageResponse(message="Server URL updated")


@router.post("/telegram/test", response_model=MessageResponse)
async def test_telegram(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    token = _get(db, "telegram_bot_token", "")
    chat_id = _get(db, "telegram_chat_id", "")
    if not token or not chat_id:
        raise HTTPException(status_code=400, detail="Telegram not configured")

    success = await send_test_message(token, chat_id)
    if success:
        return MessageResponse(message="Test message sent successfully")
    raise HTTPException(status_code=502, detail="Failed to send test message — check token and chat ID")


@router.get("/update/check")
async def check_update(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from ..main import APP_VERSION

    latest, release_url = await _fetch_latest_release_info()
    update_available = latest != "" and latest != APP_VERSION
    return {
        "current_version": APP_VERSION,
        "latest_version": latest,
        "release_url": release_url,
        "update_available": update_available,
    }


@router.post("/telegram/notify-update", response_model=MessageResponse)
async def notify_update_available(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Called when a new GitHub release is detected — sends a Telegram message if enabled."""
    from ..main import APP_VERSION

    latest, release_url = await _fetch_latest_release_info()

    if not latest or latest == APP_VERSION:
        return MessageResponse(message="Notification skipped (no newer update available)", success=False)

    already_notified_version = _get(db, "last_update_notified_version", "")
    if already_notified_version == latest:
        return MessageResponse(message="Notification skipped (already sent for this version)", success=False)

    sent = await send_update_notification(db, APP_VERSION, latest, release_url)
    if sent:
        _set(db, "last_update_notified_version", latest)
        db.commit()
        return MessageResponse(message="Update notification sent")
    return MessageResponse(message="Notification skipped (disabled or not configured)", success=False)
