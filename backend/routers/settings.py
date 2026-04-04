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
    ScanScheduleSettings,
    TelegramSettings,
)
from ..services.notification import send_test_message
from ..services.scheduler import update_interval

router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTING_KEYS = [
    "dhcp_start", "dhcp_end", "scan_interval_minutes",
    "telegram_bot_token", "telegram_chat_id", "telegram_enabled",
    "network_interface", "notify_on_device_online", "notify_on_device_offline",
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


@router.get("", response_model=AllSettings)
def get_settings(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    try:
        interval_minutes = int(_get(db, "scan_interval_minutes", "5") or "5")
    except (ValueError, TypeError):
        interval_minutes = 5

    return AllSettings(
        dhcp_start=_get(db, "dhcp_start", "192.168.1.1"),
        dhcp_end=_get(db, "dhcp_end", "192.168.1.254"),
        scan_interval_minutes=interval_minutes,
        telegram_bot_token=_get(db, "telegram_bot_token", ""),
        telegram_chat_id=_get(db, "telegram_chat_id", ""),
        telegram_enabled=_get(db, "telegram_enabled", "false") == "true",
        network_interface=_get(db, "network_interface", ""),
        notify_on_device_online=_get(db, "notify_on_device_online", "false") == "true",
        notify_on_device_offline=_get(db, "notify_on_device_offline", "false") == "true",
    )


@router.put("/dhcp", response_model=MessageResponse)
def update_dhcp(
    data: DhcpSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    import ipaddress
    try:
        ipaddress.IPv4Address(data.dhcp_start)
        ipaddress.IPv4Address(data.dhcp_end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid IP address: {e}")

    _set(db, "dhcp_start", data.dhcp_start)
    _set(db, "dhcp_end", data.dhcp_end)
    db.commit()
    return MessageResponse(message="DHCP range updated")


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


@router.put("/telegram", response_model=MessageResponse)
def update_telegram(
    data: TelegramSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _set(db, "telegram_bot_token", data.telegram_bot_token)
    _set(db, "telegram_chat_id", data.telegram_chat_id)
    _set(db, "telegram_enabled", "true" if data.telegram_enabled else "false")
    db.commit()
    return MessageResponse(message="Telegram settings updated")


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
