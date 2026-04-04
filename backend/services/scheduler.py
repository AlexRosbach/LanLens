"""
Background scan scheduler using APScheduler.
Runs periodic ARP scans at a configurable interval.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_job_id = "network_scan"
DEFAULT_INTERVAL_MINUTES = 5


async def _scan_job():
    from .scanner import run_scan
    await run_scan(scan_type="scheduled")


def start_scheduler(interval_minutes: int = DEFAULT_INTERVAL_MINUTES):
    if not _scheduler.running:
        _scheduler.start()
        logger.info("Scheduler started")

    _add_or_reschedule_job(interval_minutes)


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


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
