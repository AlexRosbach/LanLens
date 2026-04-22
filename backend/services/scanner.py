"""
Network scanner: ARP broadcast scan using scapy.
Discovers all devices on the local network and updates the database.
Requires NET_RAW capability (Docker: cap_add: [NET_RAW, NET_ADMIN]).
"""
import asyncio
import ipaddress
import json
import logging
import socket
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Device, Notification, ScanRun, Setting
from .device_classifier import classify_device
from .mac_vendor import lookup_vendor, normalize_mac
from .notification import send_telegram_for_notification

logger = logging.getLogger(__name__)

_scan_running = False
_scan_lock = asyncio.Lock()

# DNS lookup timeout in seconds (prevents hanging on slow reverse DNS)
_DNS_TIMEOUT = 2


def is_scan_running() -> bool:
    return _scan_running


DEFAULT_SCAN_START = "192.168.1.1"
DEFAULT_SCAN_END = "192.168.1.254"
MIN_OFFLINE_GRACE_MINUTES = 15
MISSED_SCAN_MULTIPLIER = 3


def _get_setting_row(db: Session, key: str) -> Optional[Setting]:
    return db.query(Setting).filter(Setting.key == key).first()


def _arp_scan(targets: List[str]) -> List[Tuple[str, str]]:
    """Perform ARP scan over one or more target CIDRs/ranges."""
    try:
        from scapy.layers.l2 import ARP, Ether
        from scapy.sendrecv import srp

        results: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for target in targets:
            packet = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=target)
            answered, _ = srp(packet, timeout=3, verbose=False)
            for _, rcv in answered:
                item = (rcv.psrc, rcv.hwsrc)
                if item not in seen:
                    seen.add(item)
                    results.append(item)

        return results
    except Exception as e:
        logger.error(f"ARP scan failed: {e}")
        return []


def _get_hostname(ip: str) -> Optional[str]:
    """Reverse DNS lookup with timeout to prevent hanging."""
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(_DNS_TIMEOUT)
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)


def _detect_host_network() -> Optional[ipaddress.IPv4Network]:
    """Detect the host's primary IPv4 network by inspecting active interfaces."""
    try:
        import netifaces

        for iface in netifaces.interfaces():
            if iface == "lo":
                continue
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET not in addrs:
                continue
            for addr_info in addrs[netifaces.AF_INET]:
                ip = addr_info.get("addr")
                netmask = addr_info.get("netmask")
                if not ip or not netmask or ip.startswith("127."):
                    continue
                try:
                    network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                    logger.info(f"Detected host network: {network} on interface {iface}")
                    return network
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"Host network detection failed: {e}")
    return None


def _network_host_bounds(network: ipaddress.IPv4Network) -> tuple[str, str]:
    if network.num_addresses <= 2:
        return str(network.network_address), str(network.broadcast_address)
    start = ipaddress.IPv4Address(int(network.network_address) + 1)
    end = ipaddress.IPv4Address(int(network.broadcast_address) - 1)
    return str(start), str(end)


def _summarize_range(start: str, end: str) -> List[str]:
    start_ip = ipaddress.IPv4Address(start)
    end_ip = ipaddress.IPv4Address(end)
    if int(start_ip) > int(end_ip):
        raise ValueError("scan_start must be less than or equal to scan_end")
    return [str(net) for net in ipaddress.summarize_address_range(start_ip, end_ip)]


def _get_offline_grace_period(db: Session) -> timedelta:
    interval_row = _get_setting_row(db, "scan_interval_minutes")
    try:
        interval_minutes = int(interval_row.value) if interval_row and interval_row.value else 5
    except (TypeError, ValueError):
        interval_minutes = 5

    grace_minutes = max(MIN_OFFLINE_GRACE_MINUTES, interval_minutes * MISSED_SCAN_MULTIPLIER)
    return timedelta(minutes=grace_minutes)


def _derive_scan_targets(db: Session) -> tuple[List[str], str, str, str]:
    start_row = _get_setting_row(db, "scan_start")
    end_row = _get_setting_row(db, "scan_end")

    if start_row and end_row and start_row.value and end_row.value:
        try:
            targets = _summarize_range(start_row.value, end_row.value)
            return targets, start_row.value, end_row.value, "configured"
        except Exception as e:
            logger.warning(f"Configured scan range invalid, ignoring it: {e}")

    if start_row and start_row.value and not end_row:
        try:
            ipaddress.IPv4Address(start_row.value)
            network = ipaddress.IPv4Network(f"{start_row.value}/24", strict=False)
            start, end = _network_host_bounds(network)
            return [str(network)], start, end, "configured-start-/24"
        except Exception as e:
            logger.warning(f"Configured scan_start is invalid, ignoring it: {e}")

    detected = _detect_host_network()
    if detected:
        start, end = _network_host_bounds(detected)
        return [str(detected)], start, end, "auto-detected"

    fallback_targets = _summarize_range(DEFAULT_SCAN_START, DEFAULT_SCAN_END)
    logger.warning(
        "No valid configured scan range and auto-detection failed, falling back to 192.168.1.1-192.168.1.254"
    )
    return fallback_targets, DEFAULT_SCAN_START, DEFAULT_SCAN_END, "fallback"


async def run_scan(scan_type: str = "scheduled") -> Optional[ScanRun]:
    global _scan_running

    async with _scan_lock:
        if _scan_running:
            logger.info("Scan already running, skipping.")
            return None
        _scan_running = True

    db = SessionLocal()
    scan_run = ScanRun(scan_type=scan_type, started_at=datetime.utcnow(), status="running")
    db.add(scan_run)
    db.commit()

    try:
        scan_targets, effective_start, effective_end, source = _derive_scan_targets(db)
        logger.info(
            f"Starting ARP scan using {source} range {effective_start} - {effective_end} "
            f"via targets: {', '.join(scan_targets)}"
        )

        results = await asyncio.get_event_loop().run_in_executor(None, _arp_scan, scan_targets)
        logger.info(f"ARP scan found {len(results)} hosts")

        # Pre-load all known devices to avoid N+1 queries
        existing_devices: Dict[str, Device] = {
            d.mac_address: d for d in db.query(Device).all()
        }

        found_macs = set()
        devices_new = 0

        for ip, mac in results:
            mac_normalized = normalize_mac(mac)
            found_macs.add(mac_normalized)

            vendor = lookup_vendor(mac_normalized)
            hostname = await asyncio.get_event_loop().run_in_executor(None, _get_hostname, ip)

            existing = existing_devices.get(mac_normalized)

            if existing is None:
                # New device
                device_class = classify_device(vendor, hostname or "")
                new_device = Device(
                    mac_address=mac_normalized,
                    ip_address=ip,
                    hostname=hostname,
                    vendor=vendor,
                    device_class=device_class,
                    is_online=True,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
                db.add(new_device)
                db.flush()
                existing_devices[mac_normalized] = new_device
                devices_new += 1

                notification = Notification(
                    device_id=new_device.id,
                    event_type="new_device",
                    message=(
                        f"New device detected: {vendor or 'Unknown vendor'} "
                        f"at {ip} ({mac_normalized})"
                    ),
                )
                db.add(notification)
                logger.info(f"New device: {mac_normalized} ({ip}) - {vendor}")
            else:
                existing.ip_address = ip
                existing.is_online = True
                existing.last_seen = datetime.utcnow()
                if hostname:
                    existing.hostname = hostname

        # Mark absent devices as offline only after a grace period.
        # A single missed ARP reply should not immediately flip stable devices offline.
        devices_offline = 0
        offline_cutoff = datetime.utcnow() - _get_offline_grace_period(db)
        for mac_addr, device in existing_devices.items():
            if mac_addr in found_macs or not device.is_online:
                continue
            if device.last_seen and device.last_seen > offline_cutoff:
                continue
            device.is_online = False
            devices_offline += 1

        scan_run.devices_found = len(found_macs)
        scan_run.devices_new = devices_new
        scan_run.devices_offline = devices_offline
        scan_run.finished_at = datetime.utcnow()
        scan_run.status = "done"
        db.commit()

        if devices_new > 0:
            await _send_telegram_notifications(db)

        logger.info(
            f"Scan complete: {len(found_macs)} found, "
            f"{devices_new} new, {devices_offline} went offline"
        )
        return scan_run

    except Exception as e:
        logger.exception(f"Scan error: {e}")
        scan_run.status = "error"
        scan_run.error_message = str(e)
        scan_run.finished_at = datetime.utcnow()
        try:
            db.commit()
        except Exception:
            db.rollback()
        return scan_run

    finally:
        db.close()
        _scan_running = False


async def _send_telegram_notifications(db: Session) -> None:
    """Send Telegram messages for unsent new-device notifications."""
    unsent = (
        db.query(Notification)
        .filter(
            Notification.event_type == "new_device",
            Notification.telegram_sent == False,
        )
        .all()
    )

    for notif in unsent:
        success = await send_telegram_for_notification(db, notif)
        if success:
            notif.telegram_sent = True

    db.commit()
