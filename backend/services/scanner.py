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
from datetime import datetime
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


def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else default


def _arp_scan(network_range: str) -> List[Tuple[str, str]]:
    """Perform ARP scan and return list of (ip, mac) tuples."""
    try:
        from scapy.layers.l2 import ARP, Ether
        from scapy.sendrecv import srp

        packet = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=network_range)
        answered, _ = srp(packet, timeout=3, verbose=False)
        return [(rcv.psrc, rcv.hwsrc) for _, rcv in answered]
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


def _detect_host_network() -> Optional[str]:
    """Detect the host's primary IPv4 network by inspecting active interfaces."""
    try:
        import netifaces
        for iface in netifaces.interfaces():
            if iface == 'lo':
                continue
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET not in addrs:
                continue
            for addr_info in addrs[netifaces.AF_INET]:
                ip = addr_info.get('addr')
                netmask = addr_info.get('netmask')
                if not ip or not netmask or ip.startswith('127.'):
                    continue
                try:
                    network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                    logger.info(f"Detected host network: {network} on interface {iface}")
                    return str(network)
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"Host network detection failed: {e}")
    return None


def _derive_network_range(db: Session) -> str:
    dhcp_start = _get_setting(db, "dhcp_start", "")

    # If dhcp_start is explicitly set and valid, use it
    if dhcp_start and dhcp_start != "192.168.1.1":
        try:
            ipaddress.IPv4Address(dhcp_start)
            network = ipaddress.IPv4Network(f"{dhcp_start}/24", strict=False)
            logger.info(f"Using configured scan range: {network}")
            return str(network)
        except Exception:
            pass

    # Otherwise, try to auto-detect the host network
    detected = _detect_host_network()
    if detected:
        logger.info(f"Using auto-detected scan range: {detected}")
        return detected

    # Last resort: fall back to 192.168.1.0/24
    logger.warning("No scan range configured and auto-detection failed, falling back to 192.168.1.0/24")
    return "192.168.1.0/24"


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
        network_range = _derive_network_range(db)
        logger.info(f"Starting ARP scan on {network_range}")

        results = await asyncio.get_event_loop().run_in_executor(None, _arp_scan, network_range)
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

        # Mark absent devices as offline
        devices_offline = 0
        for mac_addr, device in existing_devices.items():
            if mac_addr not in found_macs and device.is_online:
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
