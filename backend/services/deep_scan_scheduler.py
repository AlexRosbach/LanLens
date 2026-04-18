"""
Scheduler for automatic deep scans.

Runs a poll job every 60 seconds that checks which devices are due
for an auto-scan based on their configured interval.

Mirrors the structure of services/scheduler.py.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_JOB_ID = "deep_scan_poll"
_POLL_INTERVAL_SECONDS = 60


async def _deep_scan_poll_job() -> None:
    from .deep_scanner import poll_auto_scans
    await poll_auto_scans()


def start_deep_scan_scheduler() -> None:
    """Start the deep scan auto-poll scheduler."""
    if not _scheduler.running:
        _scheduler.start()
    _scheduler.add_job(
        _deep_scan_poll_job,
        trigger=IntervalTrigger(seconds=_POLL_INTERVAL_SECONDS),
        id=_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Deep scan auto-poll scheduler started (interval: %ds)", _POLL_INTERVAL_SECONDS)


def stop_deep_scan_scheduler() -> None:
    """Stop the deep scan auto-poll scheduler."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Deep scan auto-poll scheduler stopped")
