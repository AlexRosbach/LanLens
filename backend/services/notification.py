"""Notification delivery helpers for Telegram, webhook/Gotify and SMTP.

The webhook path deliberately validates targets server-side before sending.
Private LAN addresses are allowed because Gotify/self-hosted webhooks are a
common deployment pattern; loopback, link-local, multicast, reserved,
unspecified and cloud metadata endpoints are blocked.
"""
import asyncio
import ipaddress
import json
import logging
import ssl
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy.orm import Session

from ..models import Notification, Setting
from ..version import APP_VERSION

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
IP_ONLY_HOST_LABEL = "IP-only host"
MAX_WEBHOOK_ERROR_BODY_LOG_CHARS = 300
MAX_PINNED_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass
class PinnedHttpResponse:
    status_code: int
    text: str


def _blocked_webhook_address(address: str, label: str) -> tuple[bool, str]:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True, f"{label} resolved to an invalid address"

    # Normalize IPv4-mapped IPv6 first, otherwise ::ffff:127.0.0.1 can
    # evade IPv4 loopback/link-local checks on some Python versions.
    check_ip = ip.ipv4_mapped if getattr(ip, "ipv4_mapped", None) else ip
    if check_ip.is_loopback or check_ip.is_link_local or check_ip.is_multicast or check_ip.is_reserved or check_ip.is_unspecified:
        return True, f"{label} must not resolve to a loopback, link-local, multicast, reserved or unspecified address"
    if check_ip.version == 4 and check_ip == ipaddress.ip_address("169.254.169.254"):
        return True, f"{label} must not target cloud metadata endpoints"
    return False, ""


async def _resolve_webhook_addresses(webhook_url: str, label: str = "Webhook URL") -> tuple[Optional[object], set[str], Optional[str]]:
    parsed = urlparse((webhook_url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return None, set(), f"{label} must start with http:// or https://"
    if not parsed.hostname:
        return None, set(), f"{label} must include a host"

    hostname = parsed.hostname.strip().lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"}:
        return None, set(), f"{label} must not target localhost"

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (ValueError, TypeError):
        return None, set(), f"{label} has an invalid port"

    try:
        loop = asyncio.get_running_loop()
        resolved = await loop.getaddrinfo(
            hostname,
            port,
            type=0,
            proto=0,
        )
        addresses = {info[4][0] for info in resolved}
    except OSError:
        return None, set(), f"{label} host could not be resolved"

    if not addresses:
        return None, set(), f"{label} host could not be resolved"
    for address in addresses:
        blocked, reason = _blocked_webhook_address(address, label)
        if blocked:
            return None, set(), reason
    return parsed, addresses, None


async def validate_webhook_url(webhook_url: str, label: str = "Webhook URL") -> tuple[bool, str]:
    """Validate webhook/i-doit target URL and block unsafe SSRF targets."""
    _, _, error = await _resolve_webhook_addresses(webhook_url, label)
    return (False, error) if error else (True, "")


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


def _notification_suppressed(notification: Notification) -> bool:
    device = notification.device
    if not device:
        return False
    if getattr(device, "ignored", False) or getattr(device, "notifications_muted", False):
        return True
    maintenance_until = getattr(device, "maintenance_until", None)
    return bool(maintenance_until and maintenance_until > datetime.utcnow())


async def send_telegram_for_notification(db: Session, notification: Notification) -> bool:
    """Send a Telegram message for a specific Notification object."""
    if _notification_suppressed(notification):
        return True
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
    if _notification_suppressed(notification):
        return True
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


def _idna_hostname(hostname: str) -> str:
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return hostname


def _host_header(hostname: str, port: Optional[int], scheme: str) -> str:
    default_port = 443 if scheme == "https" else 80
    ascii_hostname = _idna_hostname(hostname)
    needs_brackets = ":" in ascii_hostname and not ascii_hostname.startswith("[")
    host = f"[{ascii_hostname}]" if needs_brackets else ascii_hostname
    return f"{host}:{port}" if port and port != default_port else host


def _request_target(path: str, query: str) -> str:
    safe_path = quote(path or "/", safe="/%:@!$&'()*+,;=")
    if not query:
        return safe_path
    safe_query = quote(query, safe="=&%:@!$'()*+,;/?")
    return f"{safe_path}?{safe_query}"



async def _read_pinned_response(reader: asyncio.StreamReader, timeout_seconds: float) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await asyncio.wait_for(reader.read(65536), timeout=timeout_seconds)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_PINNED_RESPONSE_BYTES:
            raise ValueError(f"Pinned HTTP response exceeds {MAX_PINNED_RESPONSE_BYTES} bytes")


def _decode_chunked_body(body: bytes) -> bytes:
    decoded = bytearray()
    remaining = body
    while remaining:
        line, sep, rest = remaining.partition(b"\r\n")
        if not sep:
            return body
        try:
            size = int(line.split(b";", 1)[0].strip(), 16)
        except ValueError:
            return body
        if size == 0:
            return bytes(decoded)
        chunk = rest[:size]
        decoded.extend(chunk)
        remaining = rest[size + 2:]
    return bytes(decoded)


async def _request_to_pinned_address(
    parsed,
    address: str,
    method: str = "GET",
    payload: Optional[dict] = None,
    headers: Optional[dict[str, str]] = None,
    timeout_seconds: float = 10.0,
) -> PinnedHttpResponse:
    """Send an HTTP request to a pre-validated IP while preserving Host/SNI.

    This avoids a second DNS lookup between validation and connect, closing the
    DNS-rebinding gap that would exist if a normal HTTP client received the
    original hostname.
    """
    hostname = parsed.hostname or ""
    ascii_hostname = _idna_hostname(hostname)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    ssl_context = ssl.create_default_context() if parsed.scheme == "https" else None
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            host=address,
            port=port,
            ssl=ssl_context,
            server_hostname=ascii_hostname if ssl_context else None,
        ),
        timeout=timeout_seconds,
    )
    try:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        target = _request_target(parsed.path or "/", parsed.query or "")
        header_lines = {
            "Host": _host_header(hostname, parsed.port, parsed.scheme),
            "User-Agent": f"LanLens/{APP_VERSION}",
            "Accept": "application/json, */*",
            "Connection": "close",
            **(headers or {}),
        }
        if payload is not None:
            header_lines.setdefault("Content-Type", "application/json")
            header_lines["Content-Length"] = str(len(body))
        request_head = f"{method.upper()} {target} HTTP/1.1\r\n" + "".join(
            f"{name}: {value}\r\n" for name, value in header_lines.items()
        ) + "\r\n"
        request = request_head.encode("iso-8859-1") + body
        writer.write(request)
        await asyncio.wait_for(writer.drain(), timeout=timeout_seconds)
        response = await _read_pinned_response(reader, timeout_seconds)
    finally:
        writer.close()
        await writer.wait_closed()

    head, _, response_body = response.partition(b"\r\n\r\n")
    status_line = head.splitlines()[0].decode("iso-8859-1", errors="replace") if head else ""
    parts = status_line.split(" ", 2)
    status_code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if b"transfer-encoding: chunked" in head.lower():
        response_body = _decode_chunked_body(response_body)
    return PinnedHttpResponse(status_code, response_body.decode("utf-8", errors="replace"))


async def request_json_via_validated_url(
    url: str,
    method: str = "GET",
    payload: Optional[dict] = None,
    headers: Optional[dict[str, str]] = None,
    timeout_seconds: float = 10.0,
    label: str = "URL",
) -> PinnedHttpResponse:
    """Validate a URL with the SSRF guard, then request via a pinned IP."""
    parsed, addresses, error = await _resolve_webhook_addresses(url, label)
    if error or not parsed:
        raise ValueError(error or f"{label} is invalid")

    last_error = ""
    for address in sorted(addresses, key=lambda item: (":" in item, item)):
        try:
            return await _request_to_pinned_address(parsed, address, method, payload, headers, timeout_seconds)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Pinned request to %s via %s failed: %s", label, address, exc)
    raise RuntimeError(last_error or f"{label} request failed")


async def _send_webhook(webhook_url: str, payload: dict) -> bool:
    parsed, addresses, error = await _resolve_webhook_addresses(webhook_url)
    if error or not parsed:
        logger.warning(f"Rejected webhook URL: {error}")
        return False

    last_error = ""
    for address in sorted(addresses, key=lambda item: (":" in item, item)):
        try:
            response = await _request_to_pinned_address(parsed, address, "POST", payload)
            if 200 <= response.status_code < 300:
                return True
            error_body = (response.text or "")[:MAX_WEBHOOK_ERROR_BODY_LOG_CHARS]
            suffix = "…" if len(response.text or "") > MAX_WEBHOOK_ERROR_BODY_LOG_CHARS else ""
            last_error = f"Webhook target {address} returned {response.status_code}: {error_body}{suffix}"
            logger.warning(last_error)
        except Exception as e:
            last_error = f"Failed to send webhook notification via {address}: {e}"
            logger.error(last_error)
    if last_error:
        logger.warning("Webhook delivery failed for all resolved addresses: %s", last_error)
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
