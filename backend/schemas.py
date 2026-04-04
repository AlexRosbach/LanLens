from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    force_password_change: bool


class UserResponse(BaseModel):
    id: int
    username: str
    force_password_change: bool
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


# ── Devices ───────────────────────────────────────────────────────────────────

DEVICE_CLASSES = [
    "Server", "VM", "IoT", "Router", "Switch",
    "Workstation", "NAS", "Printer", "Unknown",
]


class DeviceBase(BaseModel):
    label: Optional[str] = None
    device_class: Optional[str] = "Unknown"
    notes: Optional[str] = None


class DeviceUpdate(DeviceBase):
    is_registered: Optional[bool] = None


class PortInfo(BaseModel):
    port: int
    protocol: str
    service: str
    state: str


class PortScanResponse(BaseModel):
    id: int
    scanned_at: datetime
    open_ports: List[PortInfo]
    ssh_available: bool
    rdp_available: bool
    http_available: bool
    https_available: bool

    class Config:
        from_attributes = True


class DeviceResponse(BaseModel):
    id: int
    mac_address: str
    ip_address: Optional[str]
    hostname: Optional[str]
    label: Optional[str]
    device_class: str
    vendor: Optional[str]
    notes: Optional[str]
    is_registered: bool
    is_online: bool
    first_seen: datetime
    last_seen: datetime
    latest_scan: Optional[PortScanResponse] = None

    class Config:
        from_attributes = True


class DeviceListResponse(BaseModel):
    items: List[DeviceResponse]
    total: int
    online: int
    offline: int
    unregistered: int


# ── Scan ──────────────────────────────────────────────────────────────────────

class ScanRunResponse(BaseModel):
    id: int
    started_at: datetime
    finished_at: Optional[datetime]
    scan_type: str
    devices_found: int
    devices_new: int
    devices_offline: int
    status: str
    error_message: Optional[str]

    class Config:
        from_attributes = True


class ScanStatusResponse(BaseModel):
    is_running: bool
    last_scan: Optional[ScanRunResponse]


# ── Settings ──────────────────────────────────────────────────────────────────

class DhcpSettings(BaseModel):
    dhcp_start: str
    dhcp_end: str


class ScanScheduleSettings(BaseModel):
    scan_interval_minutes: int


class TelegramSettings(BaseModel):
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_enabled: bool


class AllSettings(BaseModel):
    dhcp_start: Optional[str] = "192.168.1.1"
    dhcp_end: Optional[str] = "192.168.1.254"
    scan_interval_minutes: int = 5
    telegram_bot_token: Optional[str] = ""
    telegram_chat_id: Optional[str] = ""
    telegram_enabled: bool = False
    network_interface: Optional[str] = ""
    notify_on_device_online: bool = False
    notify_on_device_offline: bool = False


# ── Notifications ─────────────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    id: int
    device_id: Optional[int]
    event_type: str
    message: str
    is_read: bool
    telegram_sent: bool
    created_at: datetime
    device: Optional[DeviceResponse] = None

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    message: str
    success: bool = True
