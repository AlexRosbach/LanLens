from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, unique=True)
    password_hash = Column(String(256), nullable=False)
    force_password_change = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    device_views = relationship("DeviceView", back_populates="user", cascade="all, delete-orphan")


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mac_address = Column(String(17), nullable=False, unique=True)
    ip_address = Column(String(45), nullable=True)
    hostname = Column(String(255), nullable=True)

    # ── Identification ─────────────────────────────────────────────────────────
    label = Column(String(255), nullable=True)           # short display name
    device_class = Column(String(64), default="Unknown") # Server/VM/IoT/…
    vendor = Column(String(255), nullable=True)          # from OUI lookup

    # ── Documentation fields ───────────────────────────────────────────────────
    purpose = Column(String(512), nullable=True)         # Zweck / Funktion
    description = Column(Text, nullable=True)            # ausführliche Beschreibung
    location = Column(String(255), nullable=True)        # physischer Standort
    responsible = Column(String(255), nullable=True)     # Verantwortlicher / Owner
    password_location = Column(String(512), nullable=True) # wo die Zugangsdaten liegen
    os_info = Column(String(255), nullable=True)         # Betriebssystem / Version
    asset_tag = Column(String(128), nullable=True)       # Inventarnummer / Asset-Tag
    notes = Column(Text, nullable=True)                  # freie Notizen

    # ── Discovery state ────────────────────────────────────────────────────────
    is_registered = Column(Boolean, default=False)
    cmdb_id = Column(String(64), nullable=True, unique=True, index=True)
    is_online = Column(Boolean, default=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    segment_id = Column(Integer, ForeignKey("segments.id", ondelete="SET NULL"), nullable=True)

    port_scans = relationship("PortScan", back_populates="device", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="device")
    services = relationship("Service", back_populates="device", cascade="all, delete-orphan",
                            order_by="Service.sort_order")
    segment = relationship("Segment", back_populates="devices", foreign_keys=[segment_id])
    device_views = relationship("DeviceView", back_populates="device", cascade="all, delete-orphan")
    deep_scan_config = relationship("DeviceDeepScanConfig", back_populates="device",
                                    uselist=False, cascade="all, delete-orphan")
    deep_scan_runs = relationship("DeepScanRun", back_populates="device", cascade="all, delete-orphan")
    deep_scan_findings = relationship("DeepScanFinding", back_populates="device",
                                      cascade="all, delete-orphan")


class Service(Base):
    """A service or application running on a device (e.g. Guacamole, N8N, Grafana)."""
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)

    # ── Identity ───────────────────────────────────────────────────────────────
    name = Column(String(255), nullable=False)           # display name
    service_type = Column(String(64), default="web")     # web/api/ssh/db/monitoring/other
    icon_key = Column(String(64), nullable=True)         # icon identifier for frontend

    # ── Connection ─────────────────────────────────────────────────────────────
    url = Column(String(2048), nullable=True)            # full URL or base URL
    port = Column(Integer, nullable=True)                # port override
    protocol = Column(String(16), default="https")       # http/https/ssh/tcp

    # ── Documentation ──────────────────────────────────────────────────────────
    description = Column(Text, nullable=True)
    version = Column(String(64), nullable=True)
    username_hint = Column(String(255), nullable=True)   # login username hint
    password_location = Column(String(512), nullable=True)
    notes = Column(Text, nullable=True)

    # ── Meta ───────────────────────────────────────────────────────────────────
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device = relationship("Device", back_populates="services")


class PortScan(Base):
    __tablename__ = "port_scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    open_ports = Column(Text, default="[]")
    ssh_available = Column(Boolean, default=False)
    rdp_available = Column(Boolean, default=False)
    http_available = Column(Boolean, default=False)
    https_available = Column(Boolean, default=False)

    device = relationship("Device", back_populates="port_scans")


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    scan_type = Column(String(32), default="arp")
    devices_found = Column(Integer, default=0)
    devices_new = Column(Integer, default=0)
    devices_offline = Column(Integer, default=0)
    status = Column(String(16), default="running")
    error_message = Column(Text, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(32), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    telegram_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="notifications")


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class DeviceView(Base):
    __tablename__ = "device_views"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_device_views_user_device"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    viewed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="device_views")
    device = relationship("Device", back_populates="device_views")


class Segment(Base):
    __tablename__ = "segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    color = Column(String(16), default="#6366f1")
    ip_start = Column(String(45), nullable=False)
    ip_end = Column(String(45), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    devices = relationship("Device", back_populates="segment", foreign_keys="Device.segment_id")


# ── Deep Scan ─────────────────────────────────────────────────────────────────

class Credential(Base):
    """Encrypted credential for SSH or WinRM deep scan access."""
    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    credential_type = Column(String(32), nullable=False)   # linux_ssh / windows_winrm
    auth_method = Column(String(16), default="password", nullable=False)  # password / key
    username = Column(String(128), nullable=False)
    encrypted_secret = Column(Text, nullable=False)         # Fernet token, never plaintext
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deep_scan_configs = relationship("DeviceDeepScanConfig", back_populates="credential")
    deep_scan_runs = relationship("DeepScanRun", back_populates="credential")
    auto_scan_rules = relationship("AutoScanRule", back_populates="credential", cascade="all, delete-orphan")


class DeviceDeepScanConfig(Base):
    """Per-device deep scan configuration (one row per device)."""
    __tablename__ = "device_deep_scan_config"

    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, default=False, nullable=False)
    credential_id = Column(Integer, ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)
    scan_profile = Column(String(64), default="os_services", nullable=False)
    auto_scan_enabled = Column(Boolean, default=False, nullable=False)
    interval_minutes = Column(Integer, default=60, nullable=False)
    last_scan_at = Column(DateTime, nullable=True)

    device = relationship("Device", back_populates="deep_scan_config")
    credential = relationship("Credential", back_populates="deep_scan_configs")


class DeepScanRun(Base):
    """Audit trail of every deep scan execution."""
    __tablename__ = "deep_scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    credential_id = Column(Integer, ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)
    profile = Column(String(64), nullable=False)
    status = Column(String(16), default="running", nullable=False)  # running/done/error/skipped
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    summary_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(16), default="manual", nullable=False)  # manual/scheduled

    device = relationship("Device", back_populates="deep_scan_runs")
    credential = relationship("Credential", back_populates="deep_scan_runs")
    findings = relationship("DeepScanFinding", back_populates="run", cascade="all, delete-orphan")


class DeepScanFinding(Base):
    """Single structured finding from a deep scan run."""
    __tablename__ = "deep_scan_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(Integer, ForeignKey("deep_scan_runs.id", ondelete="CASCADE"), nullable=False)
    finding_type = Column(String(32), nullable=False)  # hardware/os/service/container/hypervisor/vm_guest/audit
    key = Column(String(256), nullable=False)
    value_json = Column(Text, nullable=True)
    source = Column(String(64), nullable=True)          # e.g. "lscpu", "virsh list"
    observed_at = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="deep_scan_findings")
    run = relationship("DeepScanRun", back_populates="findings")


class AutoScanRule(Base):
    """Global rule: auto-scan all devices of a given class with a specific credential/profile."""
    __tablename__ = "auto_scan_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    device_class = Column(String(64), nullable=True)        # None = all classes
    credential_id = Column(Integer, ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False)
    scan_profile = Column(String(64), default="os_services", nullable=False)
    interval_minutes = Column(Integer, default=720, nullable=False)  # default 12 h
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    credential = relationship("Credential", back_populates="auto_scan_rules")


class DeviceHostRelationship(Base):
    """VM-to-host relationship discovered via hypervisor scan."""
    __tablename__ = "device_host_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    child_device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    host_device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    relationship_type = Column(String(32), default="vm_on_host", nullable=False)
    match_source = Column(String(16), nullable=True)    # mac / ip / hypervisor_id
    vm_identifier = Column(String(256), nullable=True)  # VM name or UUID from hypervisor
    observed_at = Column(DateTime, default=datetime.utcnow)
    last_confirmed_at = Column(DateTime, default=datetime.utcnow)

    child_device = relationship("Device", foreign_keys=[child_device_id])
    host_device = relationship("Device", foreign_keys=[host_device_id])
