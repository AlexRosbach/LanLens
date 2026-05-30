"""Scheduler for optional background multicast discovery captures."""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..database import SessionLocal
from .passive_discovery import capture_passive_discovery
from .plugin_registry import list_plugins
from .settings_helpers import get_setting_value

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_job_id = "passive_discovery_capture"
DEFAULT_INTERVAL_MINUTES = 15
DEFAULT_CAPTURE_SECONDS = 30


def _int_setting(raw_value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw_value or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def get_passive_discovery_schedule(db) -> dict[str, int | bool]:
    return {
        "enabled": get_setting_value(db, "passive_discovery_background_enabled", "false") == "true",
        "interval_minutes": _int_setting(
            get_setting_value(db, "passive_discovery_interval_minutes", str(DEFAULT_INTERVAL_MINUTES)),
            DEFAULT_INTERVAL_MINUTES,
            1,
            1440,
        ),
        "capture_seconds": _int_setting(
            get_setting_value(db, "passive_discovery_capture_seconds", str(DEFAULT_CAPTURE_SECONDS)),
            DEFAULT_CAPTURE_SECONDS,
            3,
            120,
        ),
    }


def _enabled_protocols(db) -> set[str]:
    plugins = {plugin["key"]: plugin for plugin in list_plugins(db)}
    if not plugins.get("passive-discovery", {}).get("enabled"):
        return set()

    protocols: set[str] = {"multicast"}
    if plugins.get("mdns-discovery", {}).get("enabled"):
        protocols.add("mdns")
    if plugins.get("ssdp-discovery", {}).get("enabled"):
        protocols.add("ssdp")
    return protocols


async def _capture_job() -> None:
    db = SessionLocal()
    try:
        schedule = get_passive_discovery_schedule(db)
        if not schedule["enabled"]:
            return
        protocols = _enabled_protocols(db)
        if not protocols:
            logger.info("Passive discovery background capture skipped; module disabled")
            return
        seconds = int(schedule["capture_seconds"])
    finally:
        db.close()

    loop = asyncio.get_running_loop()
    stored = await loop.run_in_executor(None, capture_passive_discovery, seconds, 250, protocols, False)
    logger.info("Passive discovery background capture stored %s observations", stored)


def start_passive_discovery_scheduler() -> None:
    if not _scheduler.running:
        _scheduler.start()
        logger.info("Passive discovery scheduler started")
    update_passive_discovery_schedule()


def update_passive_discovery_schedule() -> None:
    db = SessionLocal()
    try:
        schedule = get_passive_discovery_schedule(db)
    finally:
        db.close()

    interval = int(schedule["interval_minutes"])
    if not schedule["enabled"]:
        if _scheduler.get_job(_job_id):
            _scheduler.remove_job(_job_id)
            logger.info("Passive discovery background capture disabled")
        return

    if _scheduler.get_job(_job_id):
        _scheduler.reschedule_job(_job_id, trigger=IntervalTrigger(minutes=interval))
        logger.info("Rescheduled passive discovery capture: every %s minutes", interval)
    else:
        _scheduler.add_job(_capture_job, trigger=IntervalTrigger(minutes=interval), id=_job_id, replace_existing=True)
        logger.info("Scheduled passive discovery capture: every %s minutes", interval)


def stop_passive_discovery_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Passive discovery scheduler stopped")
