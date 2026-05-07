"""
Telegram notification service.
Sends messages to a configured Telegram bot chat.
"""
import asyncio
import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from ..models import Notification, Setting

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
IP_ONLY_HOST_LABEL = "IP-only host"


def validate_webhook_url(webhook_url: str) -> tuple[bool, str]:
    """Validate webhook URL and block common SSRF targets."""
    parsed = urlparse((webhook_url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False, "Webhook URL must start with http:// or https://"
    if not parsed.hostname:
        return False, "Webhook URL must include a host"

    hostname = parsed.hostname.strip().lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"}:
        return False, "Webhook URL must not target localhost"

    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror:
        return False, "Webhook URL host could not be resolved"

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False, "Webhook URL resolved to an invalid address"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "Webhook URL must not resolve to a private, local, link-local, multicast or reserved address"

    return True, ""


def _get_telegram_config(db: Session):
    def get(key: str) -> str:
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row else ""

    return {
        "enabled": get("telegram_enabled") == "true",
        "bot_token": get("telegram_bot_token"),
        "chat_id": get("telegram_chat_id"),
    }


def _get_webhook_config(db: Session):
    def get(key: str) -> str:
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row else ""

    return {
        "enabled": get("webhook_enabled") == "true",
        "url": get("webhook_url"),
    }


def _notification_title_and_message(notification: Notification) -> tuple[str, str]:
    device = notification.device
    if device:
        mac_label = IP_ONLY_HOST_LABEL if device.mac_address and device.mac_address.startswith("ip:") else device.mac_address
        title = "LanLens — New Device Detected"
        message = (
            f"New device detected\n\n"
            f"IP: {device.ip_address or 'unknown'}\n"
            f"MAC: {mac_label or '—'}\n"
            f"Vendor: {device.vendor or 'Unknown'}\n"
            f"Class: {device.device_class}\n"
            f"Hostname: {device.hostname or '—'}"
        )
        return title, message
    return "LanLens Notification", notification.message


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
        mac_label = IP_ONLY_HOST_LABEL if device.mac_address and device.mac_address.startswith("ip:") else device.mac_address
        text = (
            f"<b>LanLens — New Device Detected</b>\n\n"
            f"<b>IP:</b> {device.ip_address or 'unknown'}\n"
            f"<b>MAC:</b> <code>{mac_label or '—'}</code>\n"
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


async def send_webhook_for_notification(db: Session, notification: Notification) -> bool:
    """Send a generic JSON webhook, compatible with services like Gotify."""
    config = _get_webhook_config(db)
    if not config["enabled"] or not config["url"]:
        return False

    title, message = _notification_title_and_message(notification)
    payload = {
        "title": title,
        "message": message,
        "priority": 5,
        "event_type": notification.event_type,
        "device_id": notification.device_id,
        "source": "LanLens",
    }
    return await _send_webhook(config["url"], payload)


async def send_webhook_test_message(webhook_url: str) -> bool:
    """Send a test webhook payload."""
    payload = {
        "title": "LanLens — Test Notification",
        "message": "Webhook notifications are configured correctly.",
        "priority": 5,
        "event_type": "test",
        "source": "LanLens",
    }
    return await _send_webhook(webhook_url, payload)


async def _send_webhook(webhook_url: str, payload: dict) -> bool:
    valid, reason = validate_webhook_url(webhook_url)
    if not valid:
        logger.warning(f"Rejected webhook URL: {reason}")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.post(webhook_url, json=payload)
            if 200 <= response.status_code < 300:
                return True
            logger.warning(f"Webhook returned {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send webhook notification: {e}")
        return False


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


async def send_smtp_for_notification(db: Session, notification) -> bool:
    """Send an SMTP email for a notification event."""
    from email.mime.text import MIMEText

    def get(key: str) -> str:
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row else ""

    enabled = get("smtp_enabled") == "true"
    host = get("smtp_host")
    port_str = get("smtp_port") or "587"
    username = get("smtp_username")
    password = get("smtp_password")
    from_email = get("smtp_from_email")
    to_email = get("smtp_to_email")
    use_tls = get("smtp_use_tls") != "false"  # default true

    if not enabled or not host or not from_email or not to_email:
        return False

    try:
        port = int(port_str)
    except ValueError:
        port = 587

    device = getattr(notification, 'device', None)
    if device:
        subject = f"LanLens — New Device: {device.ip_address or device.mac_address}"
        body = (
            f"New device detected\n\n"
            f"IP: {device.ip_address or 'unknown'}\n"
            f"MAC: {device.mac_address}\n"
            f"Vendor: {device.vendor or 'Unknown'}\n"
            f"Class: {device.device_class}\n"
            f"Hostname: {device.hostname or '—'}"
        )
    else:
        subject = "LanLens Notification"
        body = notification.message if hasattr(notification, 'message') else str(notification)

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: _send_smtp(host, port, username, password, from_email, to_email, msg, use_tls))
        return True
    except Exception as e:
        logger.error(f"Failed to send SMTP notification: {e}")
        return False


def _send_smtp(host, port, username, password, from_email, to_email, msg, use_tls):
    import smtplib
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.sendmail(from_email, [to_email], msg.as_string())


async def send_smtp_test_message(host: str, port: int, username: str, password: str, from_email: str, to_email: str, use_tls: bool) -> bool:
    """Send a test SMTP email."""
    from email.mime.text import MIMEText
    msg = MIMEText("LanLens SMTP notifications are configured correctly.", "plain")
    msg["Subject"] = "LanLens — Test Email"
    msg["From"] = from_email
    msg["To"] = to_email
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: _send_smtp(host, port, username, password, from_email, to_email, msg, use_tls))
        return True
    except Exception as e:
        logger.error(f"SMTP test failed: {e}")
        return False
