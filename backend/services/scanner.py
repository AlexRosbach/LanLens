"""
Network scanner: ARP broadcast scan using scapy.
Discovers all devices on the local network and updates the database.
Requires NET_RAW capability (Docker: cap_add: [NET_RAW, NET_ADMIN]).
"""
import asyncio
import hashlib
import ipaddress
import logging
import re
import socket
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..database import SessionLocal
from ..models import Device, DeviceChangeEvent, DeviceIgnoreRule, DeviceIpHistory, DevicePingSample, Notification, ScanRun, Segment, Setting
from .device_classifier import classify_device
from .mac_vendor import lookup_vendor, normalize_mac
from .notification import send_telegram_for_notification, send_webhook_for_notification
from .scan_targets import parse_additional_scan_targets, routed_target_address_count
from .settings_helpers import get_scan_interval_minutes
from .device_retention import apply_device_retention

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
NOTIFICATION_RETRY_BACKOFF_MINUTES = 5
NOTIFICATION_RETRY_SETTING = "notification_delivery_last_failure_at"
PING_SAMPLE_RETENTION_PER_DEVICE = 500
PING_LATENCY_SAMPLE_LIMIT = 256
PING_MONITOR_SAMPLE_LIMIT = 512
NETWORK_CHANGE_NOTIFICATIONS_CACHE_KEY = "lanlens_notify_on_network_changes"


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
    if not targets:
        return results

    total_addresses = sum(routed_target_address_count(target) for target in targets)
    timeout_seconds = min(300, max(60, 30 + int(total_addresses * 0.05)))

    try:
        completed = subprocess.run(
            ["nmap", "-sn", "-n", "-oX", "-", *targets],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        logger.error("nmap ping scan failed: nmap binary is not installed")
        return results
    except subprocess.TimeoutExpired:
        logger.warning(f"nmap ping scan timed out after {timeout_seconds}s for {len(targets)} targets")
        return results
    except Exception as e:
        logger.error(f"nmap ping scan failed for routed targets: {e}")
        return results

    if completed.returncode not in (0, 1):
        logger.warning(f"nmap ping scan returned {completed.returncode}: {completed.stderr.strip()}")

    try:
        root = ET.fromstring(completed.stdout)
    except ET.ParseError as e:
        logger.warning(f"Could not parse nmap XML for routed targets: {e}")
        return results

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


def _ping_host(ip: str, timeout_seconds: int = 1) -> Optional[float]:
    """Return ICMP latency in ms, or None when the host does not answer."""
    try:
        completed = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout_seconds), ip],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 1,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    match = re.search(r"time[=<]([0-9.]+)\s*ms", completed.stdout)
    if not match:
        return None
    try:
        return round(float(match.group(1)), 2)
    except ValueError:
        return None


def record_ping_sample(
    db: Session,
    device_id: int,
    success: bool,
    latency_ms: Optional[float],
    source: str = "scan",
    checked_at: Optional[datetime] = None,
) -> None:
    db.add(DevicePingSample(
        device_id=device_id,
        checked_at=checked_at or datetime.utcnow(),
        success=success,
        latency_ms=latency_ms,
        source=source,
    ))
    db.flush()

    old_ids = [
        row.id for row in (
            db.query(DevicePingSample.id)
            .filter(DevicePingSample.device_id == device_id)
            .order_by(DevicePingSample.checked_at.desc(), DevicePingSample.id.desc())
            .offset(PING_SAMPLE_RETENTION_PER_DEVICE)
            .all()
        )
    ]
    if old_ids:
        db.query(DevicePingSample).filter(DevicePingSample.id.in_(old_ids)).delete(synchronize_session=False)


async def _measure_scan_latencies(results: List[DiscoveryResult]) -> Dict[str, Optional[float]]:
    """Measure ICMP latency for discovered hosts without blocking once per device."""
    unique_ips = sorted({result.ip for result in results if result.ip})[:PING_LATENCY_SAMPLE_LIMIT]
    loop = asyncio.get_running_loop()
    tasks = [loop.run_in_executor(None, _ping_host, ip, 1) for ip in unique_ips]
    values = await asyncio.gather(*tasks, return_exceptions=True)
    latencies: Dict[str, Optional[float]] = {}
    for ip, value in zip(unique_ips, values):
        latencies[ip] = value if isinstance(value, (int, float)) else None
    return latencies


async def monitor_known_device_pings(source: str = "monitor") -> int:
    """Record reachability samples for known devices, independent of discovery."""
    db = SessionLocal()
    try:
        devices = (
            db.query(Device)
            .filter(Device.ip_address.isnot(None), Device.ignored == False, Device.is_archived == False)
            .order_by(Device.id.asc())
            .limit(PING_MONITOR_SAMPLE_LIMIT)
            .all()
        )
        if not devices:
            return 0

        checked_at = datetime.utcnow()
        loop = asyncio.get_running_loop()
        tasks = [loop.run_in_executor(None, _ping_host, device.ip_address, 1) for device in devices]
        values = await asyncio.gather(*tasks, return_exceptions=True)

        recorded = 0
        for device, value in zip(devices, values):
            latency = value if isinstance(value, (int, float)) else None
            success = latency is not None
            previous_online = device.is_online
            device.is_online = success
            if success:
                device.last_seen = checked_at
                record_device_ip_history(db, device, device.ip_address, checked_at)
            if previous_online != success:
                _record_change(db, device.id, "online_state_changed", "is_online", previous_online, success, source)
            record_ping_sample(db, device.id, success, latency, source, checked_at)
            recorded += 1

        db.commit()
        return recorded
    except Exception:
        db.rollback()
        logger.exception("Ping monitor failed")
        return 0
    finally:
        db.close()


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
    # Do not mark a device offline just because one ARP/ping round missed it.
    # The grace window scales with the configured interval but never drops below
    # 15 minutes, which avoids noisy offline flapping on busy WLANs.
    interval_minutes = get_scan_interval_minutes(db)
    grace_minutes = max(MIN_OFFLINE_GRACE_MINUTES, interval_minutes * MISSED_SCAN_MULTIPLIER)
    return timedelta(minutes=grace_minutes)


def record_device_ip_history(db: Session, device: Device, ip: str, seen_at: Optional[datetime] = None) -> None:
    # Keep IP history up to date without duplicate rows. SQLite and MySQL have
    # different upsert syntaxes, so use dialect-specific paths and fall back to
    # a portable read/update path for other engines.
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


def _matches_segment_pattern(pattern: str, *, ip: str, segment: Optional[Segment]) -> bool:
    if segment and pattern in {str(segment.id).lower(), (segment.name or "").lower()}:
        return True
    try:
        ip_addr = ipaddress.IPv4Address(ip)
        if "/" in pattern:
            return ip_addr in ipaddress.IPv4Network(pattern, strict=False)
        if "-" in pattern:
            start, end = [part.strip() for part in pattern.split("-", 1)]
            return ipaddress.IPv4Address(start) <= ip_addr <= ipaddress.IPv4Address(end)
    except Exception:
        return False
    return False


def _find_matching_segment(segments: list[Segment], ip: str) -> Optional[Segment]:
    try:
        ip_int = int(ipaddress.IPv4Address(ip))
    except Exception:
        return None
    best: tuple[int, Segment] | None = None
    for segment in segments:
        try:
            start = int(ipaddress.IPv4Address(segment.ip_start))
            end = int(ipaddress.IPv4Address(segment.ip_end))
        except Exception:
            continue
        if start <= ip_int <= end:
            span = end - start
            if best is None or span < best[0]:
                best = (span, segment)
    return best[1] if best else None


def _matching_segment(db: Session, ip: str) -> Optional[Segment]:
    return _find_matching_segment(db.query(Segment).all(), ip)


def _matches_ignore_rule(rule: DeviceIgnoreRule, *, ip: str, mac: str, hostname: Optional[str], device_class: Optional[str], segment: Optional[Segment]) -> bool:
    pattern = (rule.pattern or "").strip().lower()
    if not pattern:
        return False
    if rule.rule_type == "mac":
        return pattern == (mac or "").lower()
    if rule.rule_type == "ip":
        return pattern == (ip or "").lower()
    if rule.rule_type == "hostname":
        return pattern in (hostname or "").lower()
    if rule.rule_type == "device_class":
        return pattern in (device_class or "").lower()
    if rule.rule_type == "segment":
        return _matches_segment_pattern(pattern, ip=ip, segment=segment)
    return False


def _matching_ignore_rules(
    db: Session,
    *,
    ip: str,
    mac: str,
    hostname: Optional[str],
    device_class: Optional[str],
    segments: Optional[list[Segment]] = None,
    rules: Optional[list[DeviceIgnoreRule]] = None,
) -> list[DeviceIgnoreRule]:
    segment_rows = segments if segments is not None else db.query(Segment).all()
    rule_rows = rules if rules is not None else db.query(DeviceIgnoreRule).filter(DeviceIgnoreRule.enabled == True).all()
    segment = _find_matching_segment(segment_rows, ip)
    return [rule for rule in rule_rows if _matches_ignore_rule(rule, ip=ip, mac=mac, hostname=hostname, device_class=device_class, segment=segment)]


def _network_change_notifications_enabled(db: Session) -> bool:
    if NETWORK_CHANGE_NOTIFICATIONS_CACHE_KEY in db.info:
        return bool(db.info[NETWORK_CHANGE_NOTIFICATIONS_CACHE_KEY])
    row = db.query(Setting).filter(Setting.key == "notify_on_network_changes").first()
    enabled = bool(row and row.value == "true")
    db.info[NETWORK_CHANGE_NOTIFICATIONS_CACHE_KEY] = enabled
    return enabled


def _network_change_notification_message(event_type: str, field_name: Optional[str], old_value, new_value) -> str:
    label = event_type.replace("_", " ")
    if field_name:
        return f"Network change: {label} ({field_name}: {old_value if old_value is not None else '—'} -> {new_value if new_value is not None else '—'})"
    return f"Network change: {label}"


def _record_change(db: Session, device_id: int, event_type: str, field_name: Optional[str], old_value, new_value, source: str) -> None:
    if old_value == new_value:
        return
    db.add(DeviceChangeEvent(
        device_id=device_id,
        event_type=event_type,
        field_name=field_name,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        source=source,
    ))
    if _network_change_notifications_enabled(db):
        db.add(Notification(
            device_id=device_id,
            event_type="network_change",
            message=_network_change_notification_message(event_type, field_name, old_value, new_value),
        ))


def _record_mac_drift_for_ip(db: Session, device: Device, ip: str, observed_mac: str, source: str) -> None:
    previous_mac = normalize_mac(device.mac_address) if device.mac_address else None
    current_mac = normalize_mac(observed_mac) if observed_mac else None
    if not previous_mac or not current_mac or previous_mac == current_mac or _is_ip_only_identifier(previous_mac):
        return
    recent_duplicate = (
        db.query(DeviceChangeEvent)
        .filter(
            DeviceChangeEvent.device_id == device.id,
            DeviceChangeEvent.event_type == "mac_drift_detected",
            DeviceChangeEvent.field_name == "mac_address",
            DeviceChangeEvent.old_value == previous_mac,
            DeviceChangeEvent.new_value == current_mac,
        )
        .first()
    )
    if recent_duplicate:
        return
    message = f"MAC drift detected for {ip}: {previous_mac} -> {current_mac}"
    db.add(DeviceChangeEvent(
        device_id=device.id,
        event_type="mac_drift_detected",
        field_name="mac_address",
        old_value=previous_mac,
        new_value=current_mac,
        source=source,
        message=message,
    ))
    if _network_change_notifications_enabled(db):
        db.add(Notification(
            device_id=device.id,
            event_type="network_change",
            message=f"Network security: {message}",
        ))


def _derive_scan_targets(db: Session) -> tuple[List[str], List[str], str, str, str]:
    # Primary scan range is ARP/L2. Additional routed targets use nmap ping scan
    # because MAC addresses are usually unavailable beyond the local broadcast
    # domain. Return effective bounds/source so scan logs explain what happened.
    start_row = _get_setting_row(db, "scan_start")
    end_row = _get_setting_row(db, "scan_end")
    additional_targets_row = _get_setting_row(db, "scan_additional_targets")
    additional_targets_value = additional_targets_row.value if additional_targets_row else ""
    try:
        routed_targets = parse_additional_scan_targets(additional_targets_value)
    except ValueError as e:
        logger.warning(f"Configured routed scan targets are invalid, ignoring them for this scan: {e}")
        routed_targets = []

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
        latency_by_ip = await _measure_scan_latencies(results)
        logger.info(f"Network scan found {len(results)} hosts")

        # Pre-load all known devices to avoid N+1 queries
        all_devices = db.query(Device).all()
        existing_devices: Dict[str, Device] = {
            d.mac_address: d for d in all_devices if d.mac_address
        }
        existing_devices_by_ip: Dict[str, Device] = {
            d.ip_address: d for d in all_devices if d.ip_address
        }

        enabled_ignore_rules = db.query(DeviceIgnoreRule).filter(DeviceIgnoreRule.enabled == True).all()
        segment_rows = db.query(Segment).all()
        notify_new_devices_row = db.query(Setting).filter(Setting.key == "notify_on_new_device").first()
        notify_new_devices = not notify_new_devices_row or notify_new_devices_row.value != "false"

        found_macs = set()
        devices_new = 0

        for result in results:
            ip = result.ip
            existing = existing_devices.get(result.mac) if result.mac else None
            ip_matched_existing = existing_devices_by_ip.get(ip)
            if existing is None and ip_matched_existing is not None and (
                not result.mac or _is_ip_only_identifier(ip_matched_existing.mac_address)
            ):
                existing = ip_matched_existing
            elif existing is None and ip_matched_existing is not None and result.mac:
                _record_mac_drift_for_ip(db, ip_matched_existing, ip, result.mac, "scan")
            mac_normalized = result.mac or (existing.mac_address if existing and existing.mac_address else _pseudo_mac_for_ip(ip))
            if result.mac and existing and _is_ip_only_identifier(existing.mac_address):
                existing_devices.pop(existing.mac_address, None)
                existing.mac_address = result.mac
                existing_devices[result.mac] = existing
            found_macs.add(mac_normalized)

            vendor = None if _is_ip_only_identifier(mac_normalized) else lookup_vendor(mac_normalized)
            hostname = await asyncio.get_event_loop().run_in_executor(None, _get_hostname, ip)

            if existing is None:
                existing = existing_devices.get(mac_normalized)

            seen_at = datetime.utcnow()
            if existing is None:
                # New device
                device_class = classify_device(vendor, hostname or "")
                ignore_matches = _matching_ignore_rules(
                    db,
                    ip=ip,
                    mac=mac_normalized,
                    hostname=hostname,
                    device_class=device_class,
                    segments=segment_rows,
                    rules=enabled_ignore_rules,
                )
                if any(rule.ignore_discovery for rule in ignore_matches):
                    logger.info("Ignored discovery by rule: %s (%s)", mac_normalized, ip)
                    continue
                new_device = Device(
                    mac_address=mac_normalized,
                    ip_address=ip,
                    hostname=hostname,
                    vendor=vendor,
                    device_class=device_class,
                    ignored=False,
                    notifications_muted=any(rule.mute_notifications for rule in ignore_matches),
                    is_online=True,
                    first_seen=seen_at,
                    last_seen=seen_at,
                )
                db.add(new_device)
                db.flush()
                db.add(DeviceChangeEvent(device_id=new_device.id, event_type="device_discovered", source="scan", message=f"Discovered at {ip}"))
                record_device_ip_history(db, new_device, ip, seen_at)
                record_ping_sample(db, new_device.id, True, latency_by_ip.get(ip), "scan", seen_at)
                existing_devices[mac_normalized] = new_device
                existing_devices_by_ip[ip] = new_device
                devices_new += 1

                if notify_new_devices and not new_device.notifications_muted and not new_device.ignored:
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
                previous_ip = existing.ip_address
                previous_online = existing.is_online
                previous_hostname = existing.hostname
                was_archived = bool(existing.is_archived)
                existing.ip_address = ip
                existing.is_online = True
                existing.is_archived = False
                existing.archived_at = None
                existing.last_seen = seen_at
                _record_change(db, existing.id, "ip_changed", "ip_address", previous_ip, ip, "scan")
                _record_change(db, existing.id, "online_state_changed", "is_online", previous_online, True, "scan")
                if was_archived:
                    _record_change(db, existing.id, "device_unarchived", "is_archived", True, False, "scan")
                record_device_ip_history(db, existing, ip, seen_at)
                record_ping_sample(db, existing.id, True, latency_by_ip.get(ip), "scan", seen_at)
                if hostname:
                    existing.hostname = hostname
                    _record_change(db, existing.id, "hostname_changed", "hostname", previous_hostname, hostname, "scan")

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
            previous_online = device.is_online
            device.is_online = False
            record_ping_sample(db, device.id, False, None, "scan", scan_reference_time)
            _record_change(db, device.id, "online_state_changed", "is_online", previous_online, False, "scan")
            devices_offline += 1

        scan_run.devices_found = len(found_macs)
        scan_run.devices_new = devices_new
        scan_run.devices_offline = devices_offline
        scan_run.finished_at = datetime.utcnow()
        scan_run.status = "done"
        retention_result = apply_device_retention(db, scan_reference_time)
        db.commit()

        # Retry pending deliveries after every completed scan. This lets
        # transient webhook/Telegram failures recover even when no new device is
        # discovered in the next run.
        await _send_notification_deliveries(db)

        logger.info(
            f"Scan complete: {len(found_macs)} found, "
            f"{devices_new} new, {devices_offline} went offline, "
            f"{retention_result['archived']} archived, {retention_result['deleted']} deleted"
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


async def _send_notification_deliveries(db: Session) -> None:
    """Send configured external deliveries for unsent new-device notifications.

    Only query rows for channels that are currently enabled. Otherwise disabled
    channels leave *_sent=false forever and old notifications would be scanned
    again after every discovery run.
    """
    def get_setting(key: str) -> str:
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row and row.value is not None else ""

    telegram_configured = (
        get_setting("telegram_enabled") == "true"
        and bool(get_setting("telegram_bot_token"))
        and bool(get_setting("telegram_chat_id"))
    )
    webhook_configured = get_setting("webhook_enabled") == "true" and bool(get_setting("webhook_url"))

    if not telegram_configured and not webhook_configured:
        return

    pending_filters = []
    if telegram_configured:
        pending_filters.append(Notification.telegram_sent == False)
    if webhook_configured:
        pending_filters.append(Notification.webhook_sent == False)

    unsent = (
        db.query(Notification)
        .options(joinedload(Notification.device))
        .filter(Notification.event_type.in_(("new_device", "network_change")), or_(*pending_filters))
        .all()
    )
    if not unsent:
        return

    retry_row = db.query(Setting).filter(Setting.key == NOTIFICATION_RETRY_SETTING).first()
    if retry_row and retry_row.value:
        try:
            last_failure = datetime.fromisoformat(retry_row.value)
            if datetime.utcnow() - last_failure < timedelta(minutes=NOTIFICATION_RETRY_BACKOFF_MINUTES):
                return
        except ValueError:
            pass

    had_failure = False
    for notif in unsent:
        if telegram_configured and not notif.telegram_sent:
            if await send_telegram_for_notification(db, notif):
                notif.telegram_sent = True
            else:
                had_failure = True
        if webhook_configured and not notif.webhook_sent:
            if await send_webhook_for_notification(db, notif):
                notif.webhook_sent = True
            else:
                had_failure = True

    if had_failure:
        failure_at = datetime.utcnow().isoformat()
        if retry_row:
            retry_row.value = failure_at
        else:
            db.add(Setting(key=NOTIFICATION_RETRY_SETTING, value=failure_at))
    elif retry_row:
        retry_row.value = ""

    db.commit()
