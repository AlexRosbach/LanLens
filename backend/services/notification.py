"""
Telegram notification service.
Sends messages to a configured Telegram bot chat.
"""
import logging
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from ..models import Notification, Setting

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _get_telegram_config(db: Session):
    def get(key: str) -> str:
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row else ""

    return {
        "enabled": get("telegram_enabled") == "true",
        "bot_token": get("telegram_bot_token"),
        "chat_id": get("telegram_chat_id"),
    }


async def send_telegram_for_notification(db: Session, notification: Notification) -> bool:
    """Send a Telegram message for a specific Notification object."""
    config = _get_telegram_config(db)
    if not config["enabled"] or not config["bot_token"] or not config["chat_id"]:
        return False

    server_url_row = db.query(Setting).filter(Setting.key == "server_url").first()
    server_url = (server_url_row.value or "").rstrip("/") if server_url_row else ""

    device = notification.device
    if device:
        link_line = ""
        if server_url and device.id:
            link_line = f'\n\n<a href="{server_url}/devices/{device.id}">Open in LanLens →</a>'
        text = (
            f"<b>LanLens — New Device Detected</b>\n\n"
            f"<b>IP:</b> {device.ip_address or 'unknown'}\n"
            f"<b>MAC:</b> <code>{device.mac_address}</code>\n"
            f"<b>Vendor:</b> {device.vendor or 'Unknown'}\n"
            f"<b>Class:</b> {device.device_class}\n"
            f"<b>Hostname:</b> {device.hostname or '—'}"
            f"{link_line}"
        )
    else:
        text = f"<b>LanLens Notification</b>\n\n{notification.message}"

    return await _send_message(config["bot_token"], config["chat_id"], text)


async def send_update_notification(db: Session, current_version: str, latest_version: str, release_url: str) -> bool:
    """Send a Telegram message when a new LanLens version is available."""
    config = _get_telegram_config(db)
    if not config["enabled"] or not config["bot_token"] or not config["chat_id"]:
        return False

    notify_update_row = db.query(Setting).filter(Setting.key == "notify_telegram_update").first()
    if not notify_update_row or notify_update_row.value != "true":
        return False

    text = (
        f"<b>LanLens — Update Available</b>\n\n"
        f"Version <b>v{latest_version}</b> is available (current: v{current_version}).\n\n"
        f'<a href="{release_url}">View release notes →</a>'
    )
    return await _send_message(config["bot_token"], config["chat_id"], text)


async def send_test_message(bot_token: str, chat_id: str) -> bool:
    """Send a test message to verify Telegram configuration."""
    text = (
        "<b>LanLens — Test Notification</b>\n\n"
        "Telegram notifications are configured correctly."
    )
    return await _send_message(bot_token, chat_id, text)


async def _send_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = TELEGRAM_API.format(token=bot_token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                return True
            logger.warning(f"Telegram API returned {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False
