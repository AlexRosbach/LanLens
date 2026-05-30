import json
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Setting, User
from ..version import APP_VERSION, BUILD_BRANCH, BUILD_CODE, BUILD_COMMIT, BUILD_CREATED
from ..schemas import (
    AllSettings,
    DhcpSettings,
    MessageResponse,
    PassiveDiscoverySettings,
    PortScanSettings,
    ScanRangeSettings,
    ScanScheduleSettings,
    ServerUrlSettings,
    SmtpSettings,
    TelegramSettings,
    UiSettings,
    WebhookSettings,
)
from ..services.notification import send_test_message, send_update_notification, send_webhook_test_message, validate_webhook_url
from ..services.https_config import apply_nginx_config, load_https_config, save_https_config
from ..services.passive_discovery_scheduler import update_passive_discovery_schedule
from ..services.scheduler import update_interval
from ..services.scanner import _detect_host_network, _network_host_bounds
from ..services.scan_targets import parse_additional_scan_targets
from ..services.settings_helpers import get_scan_interval_minutes

router = APIRouter(prefix="/api/settings", tags=["settings"])

TOKEN_MASK = "••••••••"

SETTING_KEYS = [
    "dhcp_start", "dhcp_end", "scan_start", "scan_end", "scan_additional_targets", "scan_interval_minutes",
    "passive_discovery_background_enabled", "passive_discovery_interval_minutes", "passive_discovery_capture_seconds",
    "port_scan_range",
    "telegram_bot_token", "telegram_chat_id", "telegram_enabled", "notify_telegram_update",
    "network_interface", "notify_on_device_online", "notify_on_device_offline", "notify_on_new_device",
    "webhook_url", "webhook_enabled",
    "server_url",
    "cmdb_id_prefix", "cmdb_id_digits",
    "advanced_view_enabled", "show_cmdb_integrations", "show_services_nav", "show_dhcp_monitor_nav",
    "show_plugin_api", "show_passive_discovery", "show_mdns_discovery", "show_ssdp_discovery",
    "show_tls_checks", "show_ping_history", "show_build_info",
]


def _get(db: Session, key: str, default: Any = None) -> Any:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else default


def _mask_secret(value: str) -> str:
    return TOKEN_MASK if value else ""


def _parse_version_tuple(version: str) -> tuple[int, ...] | None:
    match = re.match(r"^v?(\d+(?:\.\d+)*)", (version or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _is_newer_version(latest_version: str, current_version: str) -> bool:
    latest = _parse_version_tuple(latest_version)
    current = _parse_version_tuple(current_version)
    if latest is None or current is None:
        return bool(latest_version) and latest_version != current_version

    max_len = max(len(latest), len(current))
    latest_padded = latest + (0,) * (max_len - len(latest))
    current_padded = current + (0,) * (max_len - len(current))
    return latest_padded > current_padded


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
    interval_minutes = get_scan_interval_minutes(db)
    https_config = load_https_config()

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
        scan_additional_targets=_get(db, "scan_additional_targets", "") or "",
        scan_interval_minutes=interval_minutes,
        passive_discovery_background_enabled=_get(db, "passive_discovery_background_enabled", "false") == "true",
        passive_discovery_interval_minutes=int(_get(db, "passive_discovery_interval_minutes", "15") or "15"),
        passive_discovery_capture_seconds=int(_get(db, "passive_discovery_capture_seconds", "30") or "30"),
        port_scan_range=_get(db, "port_scan_range", "top:1000") or "top:1000",
        telegram_bot_token=_mask_secret(_get(db, "telegram_bot_token", "")),
        telegram_chat_id=_get(db, "telegram_chat_id", ""),
        telegram_enabled=_get(db, "telegram_enabled", "false") == "true",
        notify_telegram_update=_get(db, "notify_telegram_update", "false") == "true",
        network_interface=_get(db, "network_interface", ""),
        notify_on_device_online=_get(db, "notify_on_device_online", "false") == "true",
        notify_on_device_offline=_get(db, "notify_on_device_offline", "false") == "true",
        notify_on_new_device=_get(db, "notify_on_new_device", "true") != "false",
        server_url=_get(db, "server_url", ""),
        smtp_host=_get(db, "smtp_host", ""),
        smtp_port=int(_get(db, "smtp_port", "587") or "587"),
        smtp_username=_get(db, "smtp_username", ""),
        smtp_password=_get(db, "smtp_password", ""),
        smtp_from_email=_get(db, "smtp_from_email", ""),
        smtp_to_email=_get(db, "smtp_to_email", ""),
        smtp_enabled=_get(db, "smtp_enabled", "false") == "true",
        smtp_use_tls=_get(db, "smtp_use_tls", "true") != "false",
        webhook_url=_mask_secret(_get(db, "webhook_url", "")),
        webhook_url_configured=bool(_get(db, "webhook_url", "")),
        webhook_enabled=_get(db, "webhook_enabled", "false") == "true",
        cmdb_id_prefix=_get(db, "cmdb_id_prefix", "DEV") or "DEV",
        cmdb_id_digits=int(_get(db, "cmdb_id_digits", "4") or "4"),
        advanced_view_enabled=_get(db, "advanced_view_enabled", "false") == "true",
        show_cmdb_integrations=_get(db, "show_cmdb_integrations", "false") == "true",
        show_services_nav=_get(db, "show_services_nav", "false") == "true",
        show_dhcp_monitor_nav=_get(db, "show_dhcp_monitor_nav", "false") == "true",
        show_plugin_api=_get(db, "show_plugin_api", "false") == "true",
        show_passive_discovery=_get(db, "show_passive_discovery", "false") == "true",
        show_mdns_discovery=_get(db, "show_mdns_discovery", "false") == "true",
        show_ssdp_discovery=_get(db, "show_ssdp_discovery", "false") == "true",
        show_tls_checks=_get(db, "show_tls_checks", "false") == "true",
        show_ping_history=_get(db, "show_ping_history", "false") == "true",
        show_build_info=_get(db, "show_build_info", "false") == "true",
        app_version=APP_VERSION,
        build_code=BUILD_CODE,
        build_commit=BUILD_COMMIT,
        build_branch=BUILD_BRANCH,
        build_created=BUILD_CREATED,
        https_enabled=https_config["enabled"] is True,
        https_configured=https_config["configured"] is True,
        https_port=int(https_config["port"] or 7765),
        https_redirect_http=https_config["redirect_http"] is True,
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

    try:
        additional_targets = "\n".join(parse_additional_scan_targets(data.scan_additional_targets or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _set(db, "scan_start", data.scan_start)
    _set(db, "scan_end", data.scan_end)
    _set(db, "scan_additional_targets", additional_targets)
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


@router.put("/passive-discovery", response_model=MessageResponse)
def update_passive_discovery(
    data: PassiveDiscoverySettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    interval = max(1, min(1440, int(data.passive_discovery_interval_minutes or 15)))
    seconds = max(3, min(120, int(data.passive_discovery_capture_seconds or 30)))
    _set(db, "passive_discovery_background_enabled", "true" if data.passive_discovery_background_enabled else "false")
    _set(db, "passive_discovery_interval_minutes", str(interval))
    _set(db, "passive_discovery_capture_seconds", str(seconds))
    db.commit()
    update_passive_discovery_schedule()
    return MessageResponse(message="Passive discovery schedule updated")


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

    # Validate format: "top:N" (N must be a positive integer) or digit/comma/hyphen list
    if spec.startswith("top:"):
        top_n = spec[4:]
        if not top_n.isdigit() or int(top_n) < 1:
            raise HTTPException(
                status_code=400,
                detail="Invalid port_scan_range: 'top:N' requires N to be a positive integer (e.g. 'top:1000').",
            )
    else:
        sanitised = "".join(c for c in spec if c.isdigit() or c in ",-")
        if not sanitised:
            raise HTTPException(
                status_code=400,
                detail="Invalid port_scan_range. Use 'top:N', a range like '1-65535', or a list like '22,80,443'.",
            )

        for chunk in sanitised.split(","):
            if not chunk:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid port_scan_range. Empty list items are not allowed.",
                )
            if "-" in chunk:
                parts = chunk.split("-")
                if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid port_scan_range. Ranges must look like 'start-end'.",
                    )
                start, end = int(parts[0]), int(parts[1])
                if start < 1 or end > 65535 or start > end:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid port_scan_range. Ports must be between 1 and 65535.",
                    )
            else:
                if not chunk.isdigit() or not 1 <= int(chunk) <= 65535:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid port_scan_range. Ports must be between 1 and 65535.",
                    )

        # Store the sanitised value so what's saved matches what gets scanned
        spec = sanitised

    _set(db, "port_scan_range", spec)
    db.commit()
    return MessageResponse(message="Port scan settings updated")


@router.put("/telegram", response_model=MessageResponse)
def update_telegram(
    data: TelegramSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    incoming_token = (data.telegram_bot_token or "").strip()
    if incoming_token == "":
        _set(db, "telegram_bot_token", "")
    elif incoming_token != TOKEN_MASK:
        _set(db, "telegram_bot_token", incoming_token)

    _set(db, "telegram_chat_id", data.telegram_chat_id)
    _set(db, "telegram_enabled", "true" if data.telegram_enabled else "false")
    _set(db, "notify_telegram_update", "true" if data.notify_telegram_update else "false")
    _set(db, "notify_on_new_device", "true" if data.notify_on_new_device else "false")
    db.commit()
    return MessageResponse(message="Telegram settings updated")


@router.put("/ui", response_model=MessageResponse)
def update_ui_settings(
    data: UiSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _set(db, "advanced_view_enabled", "true" if data.advanced_view_enabled else "false")
    _set(db, "show_cmdb_integrations", "true" if data.show_cmdb_integrations else "false")
    _set(db, "show_services_nav", "true" if data.show_services_nav else "false")
    _set(db, "show_dhcp_monitor_nav", "true" if data.show_dhcp_monitor_nav else "false")
    _set(db, "show_plugin_api", "true" if data.show_plugin_api else "false")
    _set(db, "show_passive_discovery", "true" if data.show_passive_discovery else "false")
    _set(db, "show_mdns_discovery", "true" if data.show_mdns_discovery else "false")
    _set(db, "show_ssdp_discovery", "true" if data.show_ssdp_discovery else "false")
    _set(db, "show_tls_checks", "true" if data.show_tls_checks else "false")
    _set(db, "show_ping_history", "true" if data.show_ping_history else "false")
    _set(db, "show_build_info", "true" if data.show_build_info else "false")
    db.commit()
    return MessageResponse(message="UI settings updated")


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


@router.put("/https", response_model=MessageResponse)
async def update_https_settings(
    enabled: bool = Form(False),
    https_port: int = Form(7765),
    redirect_http: bool = Form(False),
    certificate: UploadFile | None = File(None),
    private_key: UploadFile | None = File(None),
    ca_chain: UploadFile | None = File(None),
    _: User = Depends(get_current_user),
):
    cert_bytes = await certificate.read() if certificate else None
    key_bytes = await private_key.read() if private_key else None
    chain_bytes = await ca_chain.read() if ca_chain else None

    try:
        save_https_config(
            enabled=enabled,
            port=https_port,
            redirect_http=redirect_http,
            certificate=cert_bytes,
            private_key=key_bytes,
            chain=chain_bytes,
        )
        apply_nginx_config()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HTTPS settings saved, but nginx reload failed: {e}")
    return MessageResponse(message="HTTPS settings updated")


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


@router.put("/smtp", response_model=MessageResponse)
def update_smtp(
    data: SmtpSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _set(db, "smtp_host", data.smtp_host)
    _set(db, "smtp_port", str(data.smtp_port))
    _set(db, "smtp_username", data.smtp_username)
    _set(db, "smtp_password", data.smtp_password)
    _set(db, "smtp_from_email", data.smtp_from_email)
    _set(db, "smtp_to_email", data.smtp_to_email)
    _set(db, "smtp_enabled", "true" if data.smtp_enabled else "false")
    _set(db, "smtp_use_tls", "true" if data.smtp_use_tls else "false")
    db.commit()
    return MessageResponse(message="SMTP settings updated")


@router.put("/webhook", response_model=MessageResponse)
async def update_webhook(
    data: WebhookSettings,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    current_url = _get(db, "webhook_url", "") or ""
    url = data.webhook_url.strip()
    if url == TOKEN_MASK:
        url = current_url
    if data.webhook_enabled and not url:
        raise HTTPException(status_code=400, detail="Webhook URL is required when webhook notifications are enabled")
    if url:
        valid, reason = await validate_webhook_url(url)
        if not valid:
            raise HTTPException(status_code=400, detail=reason)
    _set(db, "webhook_url", url)
    _set(db, "webhook_enabled", "true" if data.webhook_enabled else "false")
    db.commit()
    return MessageResponse(message="Webhook settings updated")


@router.post("/webhook/test", response_model=MessageResponse)
async def test_webhook(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    webhook_url = _get(db, "webhook_url", "")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Webhook not configured")

    success = await send_webhook_test_message(webhook_url)
    if success:
        return MessageResponse(message="Test webhook sent successfully")
    raise HTTPException(status_code=502, detail="Failed to send test webhook — check the URL")


@router.post("/smtp/test", response_model=MessageResponse)
async def test_smtp(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from ..services.notification import send_smtp_test_message
    host = _get(db, "smtp_host", "")
    port = int(_get(db, "smtp_port", "587") or "587")
    username = _get(db, "smtp_username", "")
    password = _get(db, "smtp_password", "")
    from_email = _get(db, "smtp_from_email", "")
    to_email = _get(db, "smtp_to_email", "")
    use_tls = _get(db, "smtp_use_tls", "true") != "false"

    if not host or not from_email or not to_email:
        raise HTTPException(status_code=400, detail="SMTP not fully configured")

    success = await send_smtp_test_message(host, port, username, password, from_email, to_email, use_tls)
    if success:
        return MessageResponse(message="Test email sent successfully")
    raise HTTPException(status_code=502, detail="Failed to send test email — check SMTP settings")


@router.put("/cmdb", response_model=MessageResponse)
def update_cmdb_settings(
    prefix: str,
    digits: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    prefix = prefix.strip().upper()[:20] or "DEV"
    digits = max(1, min(digits, 10))
    _set(db, "cmdb_id_prefix", prefix)
    _set(db, "cmdb_id_digits", str(digits))
    db.commit()
    return MessageResponse(message="CMDB settings updated")


@router.get("/update/check")
async def check_update(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):

    latest, release_url = await _fetch_latest_release_info()
    update_available = _is_newer_version(latest, APP_VERSION)
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

    latest, release_url = await _fetch_latest_release_info()

    if not _is_newer_version(latest, APP_VERSION):
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
