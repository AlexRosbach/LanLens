"""Periodic i-doit sync scheduler."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import joinedload

from ..database import SessionLocal
from ..models import Device
from .idoit import get_config, sync_device_to_idoit

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_job_id = "idoit_sync"


async def _sync_job() -> None:
    db = SessionLocal()
    try:
        cfg = get_config(db)
        if not cfg.enabled or not cfg.auto_sync_enabled:
            return
        devices = (
            db.query(Device)
            .options(joinedload(Device.idoit_sync))
            .filter(Device.is_registered == True)  # noqa: E712
            .all()
        )
        for device in devices:
            try:
                await sync_device_to_idoit(db, device, mode="auto", skip_unchanged=True)
            except Exception as exc:
                logger.warning("Automatic i-doit sync failed for device %s: %s", device.id, exc)
    finally:
        db.close()


def start_idoit_scheduler(interval_minutes: int = 60) -> None:
    interval = max(5, min(1440, int(interval_minutes or 60)))
    if not _scheduler.running:
        _scheduler.start()
        logger.info("i-doit sync scheduler started")
    update_idoit_interval(interval)


def update_idoit_interval(interval_minutes: int) -> None:
    interval = max(5, min(1440, int(interval_minutes or 60)))
    if _scheduler.get_job(_job_id):
        _scheduler.reschedule_job(_job_id, trigger=IntervalTrigger(minutes=interval))
        logger.info("Rescheduled i-doit sync job: every %s minutes", interval)
    else:
        _scheduler.add_job(_sync_job, trigger=IntervalTrigger(minutes=interval), id=_job_id, replace_existing=True)
        logger.info("Scheduled i-doit sync job: every %s minutes", interval)


def get_idoit_scheduler_status() -> dict[str, str | bool | None]:
    job = _scheduler.get_job(_job_id) if _scheduler.running else None
    return {
        "running": _scheduler.running,
        "next_run_at": job.next_run_time.isoformat() if job and job.next_run_time else None,
    }


def stop_idoit_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("i-doit sync scheduler stopped")
