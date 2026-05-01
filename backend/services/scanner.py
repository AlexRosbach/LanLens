"""
Network scanner: ARP broadcast scan using scapy.
Discovers all devices on the local network and updates the database.
Requires NET_RAW capability (Docker: cap_add: [NET_RAW, NET_ADMIN]).
"""
import asyncio
import hashlib
import ipaddress
import json
import logging
import socket
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Device, DeviceIpHistory, Notification, ScanRun, Setting
from .device_classifier import classify_device
from .mac_vendor import lookup_vendor, normalize_mac
from .notification import send_telegram_for_notification
from .settings_helpers import get_scan_interval_minutes

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


@dataclass(frozen=True)
class DiscoveryResult:
    ip: str
    mac: Optional[str] = None


def _pseudo_mac_for_ip(ip: str) -> str:
    """Return a stable pseudo identifier for IP-only routed-scan results.

    The current device model requires a unique non-empty MAC-like identifier.
    Routed subnets often do not expose MAC addresses, so we keep those hosts
    trackable with a deterministic, clearly non-MAC `ip:` identifier.
    """
    return f"ip:{hashlib.sha1(ip.encode('utf-8')).hexdigest()[:14]}"


def _is_ip_only_identifier(value: Optional[str]) -> bool:
    return bool(value and value.startswith("ip:"))


def _arp_scan(targets: List[str]) -> List[DiscoveryResult]:
    """Perform ARP scan over one or more directly reachable target CIDRs/ranges."""
    try:
        from scapy.layers.l2 import ARP, Ether
        from scapy.sendrecv import srp

        results: list[DiscoveryResult] = []
        seen: set[tuple[str, str]] = set()

        for target in targets:
            packet = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=target)
            answered, _ = srp(packet, timeout=3, verbose=False)
            for _, rcv in answered:
                mac = normalize_mac(rcv.hwsrc)
                item = (rcv.psrc, mac)
                if item not in seen:
                    seen.add(item)
                    results.append(DiscoveryResult(ip=rcv.psrc, mac=mac))

        return results
    except Exception as e:
        logger.error(f"ARP scan failed: {e}")
        return []


def _nmap_ping_scan(targets: List[str]) -> List[DiscoveryResult]:
    """Discover hosts in routed networks using nmap ping scan.

    nmap may return MAC addresses for local L2 targets, but routed subnets
    usually only provide IP/hostname reachability.
    """
    results: list[DiscoveryResult] = []
    seen_ips: set[str] = set()

    for target in targets:
        try:
            completed = subprocess.run(
                ["nmap", "-sn", "-n", "-oX", "-", target],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            logger.error("nmap ping scan failed: nmap binary is not installed")
            return results
        except subprocess.TimeoutExpired:
            logger.warning(f"nmap ping scan timed out for {target}")
            continue
        except Exception as e:
            logger.error(f"nmap ping scan failed for {target}: {e}")
            continue

        if completed.returncode not in (0, 1):
            logger.warning(f"nmap ping scan returned {completed.returncode} for {target}: {completed.stderr.strip()}")

        try:
            root = ET.fromstring(completed.stdout)
        except ET.ParseError as e:
            logger.warning(f"Could not parse nmap XML for {target}: {e}")
            continue

        for host in root.findall("host"):
            status = host.find("status")
            if status is not None and status.attrib.get("state") != "up":
                continue

            ip = None
            mac = None
            for address in host.findall("address"):
                addr_type = address.attrib.get("addrtype")
                if addr_type == "ipv4":
                    ip = address.attrib.get("addr")
                elif addr_type == "mac":
                    raw_mac = address.attrib.get("addr")
                    mac = normalize_mac(raw_mac) if raw_mac else None

            if ip and ip not in seen_ips:
                seen_ips.add(ip)
                results.append(DiscoveryResult(ip=ip, mac=mac))

    return results


def _validate_nmap_target(raw_target: str) -> str:
    target = raw_target.strip()
    if not target:
        raise ValueError("empty scan target")

    if "/" not in target:
        try:
            return str(ipaddress.IPv4Address(target))
        except ValueError:
            pass

    try:
        return str(ipaddress.IPv4Network(target, strict=False))
    except ValueError as e:
        raise ValueError(f"Invalid scan target '{target}'. Use an IPv4 address or CIDR, e.g. 192.168.10.0/24") from e


def _parse_additional_scan_targets(value: Optional[str]) -> List[str]:
    if not value:
        return []

    targets: list[str] = []
    for part in value.replace("\n", ",").split(","):
        part = part.strip()
        if not part:
            continue
        target = _validate_nmap_target(part)
        if target not in targets:
            targets.append(target)
    return targets


def _dedupe_discovery_results(results: List[DiscoveryResult]) -> List[DiscoveryResult]:
    """Deduplicate discoveries by IP, preferring entries with real MAC addresses."""
    by_ip: dict[str, DiscoveryResult] = {}
    for result in results:
        existing = by_ip.get(result.ip)
        if existing is None or (not existing.mac and result.mac):
            by_ip[result.ip] = result
    return list(by_ip.values())


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
    interval_minutes = get_scan_interval_minutes(db)
    grace_minutes = max(MIN_OFFLINE_GRACE_MINUTES, interval_minutes * MISSED_SCAN_MULTIPLIER)
    return timedelta(minutes=grace_minutes)


def record_device_ip_history(db: Session, device: Device, ip: str, seen_at: Optional[datetime] = None) -> None:
    if not ip:
        return

    observed_at = seen_at or datetime.utcnow()
    values = {
        "device_id": device.id,
        "ip_address": ip,
        "first_seen": observed_at,
        "last_seen": observed_at,
        "seen_count": 1,
    }
    dialect = db.bind.dialect.name if db.bind is not None else ""

    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(DeviceIpHistory).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["device_id", "ip_address"],
            set_={
                "last_seen": observed_at,
                "seen_count": DeviceIpHistory.seen_count + 1,
            },
        )
        db.execute(stmt)
        return

    if dialect in {"mysql", "mariadb"}:
        from sqlalchemy.dialects.mysql import insert as mysql_insert

        stmt = mysql_insert(DeviceIpHistory).values(**values)
        stmt = stmt.on_duplicate_key_update(
            last_seen=observed_at,
            seen_count=DeviceIpHistory.seen_count + 1,
        )
        db.execute(stmt)
        return

    existing = (
        db.query(DeviceIpHistory)
        .filter(DeviceIpHistory.device_id == device.id, DeviceIpHistory.ip_address == ip)
        .first()
    )
    if existing:
        existing.last_seen = observed_at
        existing.seen_count = (existing.seen_count or 0) + 1
    else:
        db.add(DeviceIpHistory(**values))


def _derive_scan_targets(db: Session) -> tuple[List[str], List[str], str, str, str]:
    start_row = _get_setting_row(db, "scan_start")
    end_row = _get_setting_row(db, "scan_end")
    additional_targets_row = _get_setting_row(db, "scan_additional_targets")
    routed_targets = _parse_additional_scan_targets(additional_targets_row.value if additional_targets_row else "")

    if start_row and end_row and start_row.value and end_row.value:
        try:
            arp_targets = _summarize_range(start_row.value, end_row.value)
            return arp_targets, routed_targets, start_row.value, end_row.value, "configured"
        except Exception as e:
            logger.warning(f"Configured scan range invalid, ignoring it: {e}")

    if start_row and start_row.value and not end_row:
        try:
            ipaddress.IPv4Address(start_row.value)
            network = ipaddress.IPv4Network(f"{start_row.value}/24", strict=False)
            start, end = _network_host_bounds(network)
            return [str(network)], routed_targets, start, end, "configured-start-/24"
        except Exception as e:
            logger.warning(f"Configured scan_start is invalid, ignoring it: {e}")

    detected = _detect_host_network()
    if detected:
        start, end = _network_host_bounds(detected)
        return [str(detected)], routed_targets, start, end, "auto-detected"

    fallback_targets = _summarize_range(DEFAULT_SCAN_START, DEFAULT_SCAN_END)
    logger.warning(
        "No valid configured scan range and auto-detection failed, falling back to 192.168.1.1-192.168.1.254"
    )
    return fallback_targets, routed_targets, DEFAULT_SCAN_START, DEFAULT_SCAN_END, "fallback"


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
        scan_targets, routed_scan_targets, effective_start, effective_end, source = _derive_scan_targets(db)
        logger.info(
            f"Starting ARP scan using {source} range {effective_start} - {effective_end} "
            f"via ARP targets: {', '.join(scan_targets)}"
        )

        results = await asyncio.get_event_loop().run_in_executor(None, _arp_scan, scan_targets)
        if routed_scan_targets:
            logger.info(f"Starting routed nmap ping scan via targets: {', '.join(routed_scan_targets)}")
            routed_results = await asyncio.get_event_loop().run_in_executor(None, _nmap_ping_scan, routed_scan_targets)
            results.extend(routed_results)
        results = _dedupe_discovery_results(results)
        logger.info(f"Network scan found {len(results)} hosts")

        # Pre-load all known devices to avoid N+1 queries
        all_devices = db.query(Device).all()
        existing_devices: Dict[str, Device] = {
            d.mac_address: d for d in all_devices if d.mac_address
        }
        existing_devices_by_ip: Dict[str, Device] = {
            d.ip_address: d for d in all_devices if d.ip_address
        }

        found_macs = set()
        devices_new = 0

        for result in results:
            ip = result.ip
            existing = existing_devices.get(result.mac) if result.mac else existing_devices_by_ip.get(ip)
            mac_normalized = result.mac or (existing.mac_address if existing and existing.mac_address else _pseudo_mac_for_ip(ip))
            found_macs.add(mac_normalized)

            vendor = None if _is_ip_only_identifier(mac_normalized) else lookup_vendor(mac_normalized)
            hostname = await asyncio.get_event_loop().run_in_executor(None, _get_hostname, ip)

            if existing is None:
                existing = existing_devices.get(mac_normalized)

            seen_at = datetime.utcnow()

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
                    first_seen=seen_at,
                    last_seen=seen_at,
                )
                db.add(new_device)
                db.flush()
                record_device_ip_history(db, new_device, ip, seen_at)
                existing_devices[mac_normalized] = new_device
                existing_devices_by_ip[ip] = new_device
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
                existing.last_seen = seen_at
                record_device_ip_history(db, existing, ip, seen_at)
                if hostname:
                    existing.hostname = hostname

        # Mark absent devices as offline only after a grace period.
        # A single missed ARP reply should not immediately flip stable devices offline.
        devices_offline = 0
        scan_reference_time = scan_run.started_at or datetime.utcnow()
        offline_cutoff = scan_reference_time - _get_offline_grace_period(db)
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
