from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
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
    is_online = Column(Boolean, default=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    port_scans = relationship("PortScan", back_populates="device", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="device")
    services = relationship("Service", back_populates="device", cascade="all, delete-orphan",
                            order_by="Service.sort_order")


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


class Segment(Base):
    __tablename__ = "segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    color = Column(String(16), default="#6366f1")
    ip_start = Column(String(45), nullable=False)
    ip_end = Column(String(45), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
