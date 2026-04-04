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
    label = Column(String(255), nullable=True)
    device_class = Column(String(64), default="Unknown")
    vendor = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    is_registered = Column(Boolean, default=False)
    is_online = Column(Boolean, default=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    port_scans = relationship("PortScan", back_populates="device", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="device")


class PortScan(Base):
    __tablename__ = "port_scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    open_ports = Column(Text, default="[]")  # JSON array
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
    scan_type = Column(String(32), default="arp")  # arp / full / scheduled
    devices_found = Column(Integer, default=0)
    devices_new = Column(Integer, default=0)
    devices_offline = Column(Integer, default=0)
    status = Column(String(16), default="running")  # running / done / error
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
    event_type = Column(String(32), nullable=False)  # new_device / device_online / device_offline
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
