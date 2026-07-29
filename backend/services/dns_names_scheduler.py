"""Periodic read-only AXFR zone synchronization."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..database import SessionLocal
from .dns_names import get_axfr_dns_config, synchronize_axfr_dns

logger = logging.getLogger(__name__)
_scheduler = AsyncIOScheduler()
_job_id = "axfr_dns_sync"


def _sync_once() -> None:
    db = SessionLocal()
    try:
        config = get_axfr_dns_config(db)
        if not config.dns_names_enabled or not config.enabled:
            return
        result = synchronize_axfr_dns(db, config)
        logger.info("AXFR sync associated %s names with %s devices", result["names"], result["devices"])
    except Exception as exc:
        logger.warning("AXFR synchronization failed: %s", exc)
        db.rollback()
        from .dns_names import _set_setting
        _set_setting(db, "axfr_dns_last_error", "Scheduled AXFR synchronization failed; verify the zone-transfer ACL and optional TSIG settings")
        db.commit()
    finally:
        db.close()


async def _sync_job() -> None:
    await asyncio.get_running_loop().run_in_executor(None, _sync_once)


def update_dns_names_schedule() -> None:
    db = SessionLocal()
    try:
        config = get_axfr_dns_config(db)
    finally:
        db.close()
    if not config.dns_names_enabled or not config.enabled:
        if _scheduler.get_job(_job_id):
            _scheduler.remove_job(_job_id)
        return
    interval = max(5, min(1440, config.interval_minutes))
    if _scheduler.get_job(_job_id):
        _scheduler.reschedule_job(_job_id, trigger=IntervalTrigger(minutes=interval))
    else:
        _scheduler.add_job(_sync_job, trigger=IntervalTrigger(minutes=interval), id=_job_id, replace_existing=True)


def start_dns_names_scheduler() -> None:
    if not _scheduler.running:
        _scheduler.start()
    update_dns_names_schedule()


def stop_dns_names_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
