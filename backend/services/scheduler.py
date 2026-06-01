"""
Background scan scheduler using APScheduler.
Runs periodic ARP scans at a configurable interval.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..database import SessionLocal
from .settings_helpers import get_setting_value, is_advanced_feature_enabled

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_job_id = "network_scan"
_ping_job_id = "ping_monitor"
_retention_job_id = "device_retention"
DEFAULT_INTERVAL_MINUTES = 5
DEFAULT_PING_MONITOR_INTERVAL_MINUTES = 5


async def _scan_job():
    from .scanner import run_scan
    await run_scan(scan_type="scheduled")


async def _ping_monitor_job():
    from .scanner import monitor_known_device_pings
    recorded = await monitor_known_device_pings()
    logger.info("Ping monitor recorded %s reachability samples", recorded)


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


def start_scheduler(interval_minutes: int = DEFAULT_INTERVAL_MINUTES):
    if not _scheduler.running:
        _scheduler.start()
        logger.info("Scheduler started")

    _add_or_reschedule_job(interval_minutes)
    update_ping_monitor_schedule()
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
