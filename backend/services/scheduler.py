"""
Background scan scheduler using APScheduler.
Runs periodic ARP scans at a configurable interval.
"""
import logging
import ipaddress

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..database import SessionLocal
from .settings_helpers import get_setting_value, is_advanced_feature_enabled, is_advanced_view_enabled

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_job_id = "network_scan"
_ping_job_id = "ping_monitor"
_port_scan_job_id = "port_scan"
_snmp_poll_job_id = "snmp_poll"
_retention_job_id = "device_retention"
DEFAULT_INTERVAL_MINUTES = 5
DEFAULT_PING_MONITOR_INTERVAL_MINUTES = 5
DEFAULT_PORT_SCAN_INTERVAL_MINUTES = 60
DEFAULT_SNMP_POLL_INTERVAL_MINUTES = 60
PORT_SCAN_DEVICE_LIMIT = 100


async def _scan_job():
    from .scanner import run_scan
    await run_scan(scan_type="scheduled")


async def _ping_monitor_job():
    from .scanner import monitor_known_device_pings
    recorded = await monitor_known_device_pings()
    logger.info("Ping monitor recorded %s reachability samples", recorded)


async def _port_scan_job():
    from ..models import Device
    from ..routers.devices import _do_port_scan

    db = SessionLocal()
    try:
        port_spec = get_setting_value(db, "port_scan_range", "top:1000") or "top:1000"
        devices = (
            db.query(Device)
            .filter(Device.ip_address.isnot(None), Device.ignored == False, Device.is_archived == False)
            .order_by(Device.id.asc())
            .limit(PORT_SCAN_DEVICE_LIMIT)
            .all()
        )
        targets: list[tuple[int, str]] = []
        for device in devices:
            ip = str(device.ip_address or "")
            try:
                ipaddress.IPv4Address(ip)
            except ValueError:
                continue
            targets.append((device.id, ip))
    finally:
        db.close()

    scanned = 0
    for device_id, ip in targets:
        await _do_port_scan(device_id, ip, port_spec)
        scanned += 1

    logger.info("Port scan monitor scanned %s devices", scanned)


async def _snmp_poll_job():
    from ..models import SnmpSwitch
    from .snmp import poll_switch

    db = SessionLocal()
    polled = 0
    failed = 0
    try:
        switches = (
            db.query(SnmpSwitch)
            .filter(SnmpSwitch.enabled == True, SnmpSwitch.profile_id.isnot(None))
            .order_by(SnmpSwitch.id.asc())
            .all()
        )
        for switch in switches:
            try:
                poll_switch(db, switch)
                db.commit()
                polled += 1
            except Exception as exc:
                db.rollback()
                switch = db.query(SnmpSwitch).filter(SnmpSwitch.id == switch.id).first()
                if switch:
                    from datetime import datetime

                    switch.last_error = str(exc)
                    switch.last_poll_at = datetime.utcnow()
                    db.commit()
                failed += 1
                logger.warning("Scheduled SNMP poll failed for %s: %s", switch.host if switch else "unknown", exc)
    finally:
        db.close()

    logger.info("SNMP poll monitor polled %s switches (%s failed)", polled, failed)


async def _device_retention_job():
    from .device_retention import apply_device_retention
    db = SessionLocal()
    try:
        result = apply_device_retention(db)
        db.commit()
        logger.info("Device retention archived %s devices and deleted %s archived devices", result["archived"], result["deleted"])
    except Exception as exc:
        db.rollback()
        logger.warning("Device retention failed: %s", exc)
    finally:
        db.close()


def _int_setting(raw_value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw_value or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def get_ping_monitor_schedule(db) -> dict[str, int | bool]:
    return {
        "enabled": (
            get_setting_value(db, "ping_monitor_enabled", "false") == "true"
            and is_advanced_feature_enabled(db, "show_ping_history")
        ),
        "interval_minutes": _int_setting(
            get_setting_value(db, "ping_monitor_interval_minutes", str(DEFAULT_PING_MONITOR_INTERVAL_MINUTES)),
            DEFAULT_PING_MONITOR_INTERVAL_MINUTES,
            1,
            1440,
        ),
    }


def get_port_scan_schedule(db) -> dict[str, int | bool]:
    return {
        "enabled": (
            get_setting_value(db, "port_scan_background_enabled", "false") == "true"
            and is_advanced_view_enabled(db)
        ),
        "interval_minutes": _int_setting(
            get_setting_value(db, "port_scan_interval_minutes", str(DEFAULT_PORT_SCAN_INTERVAL_MINUTES)),
            DEFAULT_PORT_SCAN_INTERVAL_MINUTES,
            1,
            1440,
        ),
    }


def get_snmp_poll_schedule(db) -> dict[str, int | bool]:
    return {
        "enabled": (
            get_setting_value(db, "snmp_poll_enabled", "false") == "true"
            and is_advanced_view_enabled(db)
        ),
        "interval_minutes": _int_setting(
            get_setting_value(db, "snmp_poll_interval_minutes", str(DEFAULT_SNMP_POLL_INTERVAL_MINUTES)),
            DEFAULT_SNMP_POLL_INTERVAL_MINUTES,
            1,
            1440,
        ),
    }


def start_scheduler(interval_minutes: int = DEFAULT_INTERVAL_MINUTES):
    if not _scheduler.running:
        _scheduler.start()
        logger.info("Scheduler started")

    _add_or_reschedule_job(interval_minutes)
    update_ping_monitor_schedule()
    update_port_scan_schedule()
    update_snmp_poll_schedule()
    _add_retention_job()


def _add_or_reschedule_job(interval_minutes: int):
    if _scheduler.get_job(_job_id):
        _scheduler.reschedule_job(
            _job_id,
            trigger=IntervalTrigger(minutes=interval_minutes),
        )
        logger.info(f"Rescheduled scan job: every {interval_minutes} minutes")
    else:
        _scheduler.add_job(
            _scan_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id=_job_id,
            replace_existing=True,
        )
        logger.info(f"Scheduled scan job: every {interval_minutes} minutes")


def update_interval(interval_minutes: int):
    _add_or_reschedule_job(interval_minutes)


def update_ping_monitor_schedule():
    db = SessionLocal()
    try:
        schedule = get_ping_monitor_schedule(db)
    finally:
        db.close()

    if not schedule["enabled"]:
        if _scheduler.get_job(_ping_job_id):
            _scheduler.remove_job(_ping_job_id)
            logger.info("Ping monitor disabled")
        return

    interval = int(schedule["interval_minutes"])
    if _scheduler.get_job(_ping_job_id):
        _scheduler.reschedule_job(_ping_job_id, trigger=IntervalTrigger(minutes=interval))
        logger.info("Rescheduled ping monitor: every %s minutes", interval)
    else:
        _scheduler.add_job(_ping_monitor_job, trigger=IntervalTrigger(minutes=interval), id=_ping_job_id, replace_existing=True)
        logger.info("Scheduled ping monitor: every %s minutes", interval)


def update_port_scan_schedule():
    db = SessionLocal()
    try:
        schedule = get_port_scan_schedule(db)
    finally:
        db.close()

    if not schedule["enabled"]:
        if _scheduler.get_job(_port_scan_job_id):
            _scheduler.remove_job(_port_scan_job_id)
            logger.info("Port scan monitor disabled")
        return

    interval = int(schedule["interval_minutes"])
    if _scheduler.get_job(_port_scan_job_id):
        _scheduler.reschedule_job(_port_scan_job_id, trigger=IntervalTrigger(minutes=interval))
        logger.info("Rescheduled port scan monitor: every %s minutes", interval)
    else:
        _scheduler.add_job(_port_scan_job, trigger=IntervalTrigger(minutes=interval), id=_port_scan_job_id, replace_existing=True)
        logger.info("Scheduled port scan monitor: every %s minutes", interval)


def update_snmp_poll_schedule():
    db = SessionLocal()
    try:
        schedule = get_snmp_poll_schedule(db)
    finally:
        db.close()

    if not schedule["enabled"]:
        if _scheduler.get_job(_snmp_poll_job_id):
            _scheduler.remove_job(_snmp_poll_job_id)
            logger.info("SNMP poll monitor disabled")
        return

    interval = int(schedule["interval_minutes"])
    if _scheduler.get_job(_snmp_poll_job_id):
        _scheduler.reschedule_job(_snmp_poll_job_id, trigger=IntervalTrigger(minutes=interval))
        logger.info("Rescheduled SNMP poll monitor: every %s minutes", interval)
    else:
        _scheduler.add_job(_snmp_poll_job, trigger=IntervalTrigger(minutes=interval), id=_snmp_poll_job_id, replace_existing=True)
        logger.info("Scheduled SNMP poll monitor: every %s minutes", interval)


def _add_retention_job():
    if not _scheduler.get_job(_retention_job_id):
        _scheduler.add_job(
            _device_retention_job,
            trigger=IntervalTrigger(hours=24),
            id=_retention_job_id,
            replace_existing=True,
        )
        logger.info("Scheduled device retention: every 24 hours")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
