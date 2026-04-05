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


# ── Services ──────────────────────────────────────────────────────────────────

SERVICE_TYPES = ["web", "api", "ssh", "rdp", "database", "monitoring", "storage", "automation", "other"]


class ServiceCreate(BaseModel):
    name: str
    service_type: str = "web"
    icon_key: Optional[str] = None
    url: Optional[str] = None
    port: Optional[int] = None
    protocol: str = "https"
    description: Optional[str] = None
    version: Optional[str] = None
    username_hint: Optional[str] = None
    password_location: Optional[str] = None
    notes: Optional[str] = None
    sort_order: int = 0


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    service_type: Optional[str] = None
    icon_key: Optional[str] = None
    url: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    username_hint: Optional[str] = None
    password_location: Optional[str] = None
    notes: Optional[str] = None
    sort_order: Optional[int] = None


class ServiceResponse(BaseModel):
    id: int
    device_id: int
    name: str
    service_type: str
    icon_key: Optional[str]
    url: Optional[str]
    port: Optional[int]
    protocol: str
    description: Optional[str]
    version: Optional[str]
    username_hint: Optional[str]
    password_location: Optional[str]
    notes: Optional[str]
    sort_order: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Devices ───────────────────────────────────────────────────────────────────

DEVICE_CLASSES = [
    "Server", "VM", "Workstation", "NAS",
    "Router", "Switch", "AP", "Firewall",
    "Mobile", "TV", "VoIP",
    "IoT", "Printer", "Camera",
    "Unknown",
]


class DeviceUpdate(BaseModel):
    # Identification
    label: Optional[str] = None
    device_class: Optional[str] = None
    is_registered: Optional[bool] = None
    segment_id: Optional[int] = None
    # Documentation
    purpose: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    responsible: Optional[str] = None
    password_location: Optional[str] = None
    os_info: Optional[str] = None
    asset_tag: Optional[str] = None
    notes: Optional[str] = None


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
    # Identification
    label: Optional[str]
    device_class: str
    vendor: Optional[str]
    # Segment
    segment_id: Optional[int] = None
    segment_name: Optional[str] = None
    segment_color: Optional[str] = None
    # DHCP
    is_dhcp: bool = False
    # Documentation
    purpose: Optional[str]
    description: Optional[str]
    location: Optional[str]
    responsible: Optional[str]
    password_location: Optional[str]
    os_info: Optional[str]
    asset_tag: Optional[str]
    notes: Optional[str]
    # State
    is_registered: bool
    is_online: bool
    first_seen: datetime
    last_seen: datetime
    # Relations
    latest_scan: Optional[PortScanResponse] = None
    services: List[ServiceResponse] = []

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
    notify_telegram_update: bool = False


class ServerUrlSettings(BaseModel):
    server_url: str


class AllSettings(BaseModel):
    dhcp_start: Optional[str] = "192.168.1.1"
    dhcp_end: Optional[str] = "192.168.1.254"
    scan_interval_minutes: int = 5
    telegram_bot_token: Optional[str] = ""
    telegram_chat_id: Optional[str] = ""
    telegram_enabled: bool = False
    notify_telegram_update: bool = False
    network_interface: Optional[str] = ""
    notify_on_device_online: bool = False
    notify_on_device_offline: bool = False
    server_url: Optional[str] = ""


# ── Notifications ─────────────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    id: int
    device_id: Optional[int]
    event_type: str
    message: str
    is_read: bool
    telegram_sent: bool
    created_at: datetime

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    message: str
    success: bool = True


# ── Segments ──────────────────────────────────────────────────────────────────

class SegmentCreate(BaseModel):
    name: str
    color: str = "#6366f1"
    ip_start: str
    ip_end: str
    description: Optional[str] = None


class SegmentUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    ip_start: Optional[str] = None
    ip_end: Optional[str] = None
    description: Optional[str] = None


class SegmentResponse(BaseModel):
    id: int
    name: str
    color: str
    ip_start: str
    ip_end: str
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
