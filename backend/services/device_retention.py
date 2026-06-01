"""Archive and purge stale discovered devices according to retention settings."""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Device, DeviceChangeEvent
from .settings_helpers import get_setting_value

DEFAULT_ARCHIVE_AFTER_DAYS = 0
DEFAULT_DELETE_ARCHIVED_AFTER_DAYS = 0


def _int_setting(db: Session, key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(get_setting_value(db, key, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def get_device_retention_settings(db: Session) -> dict[str, int]:
    return {
        "device_archive_after_days": _int_setting(
            db,
            "device_archive_after_days",
            DEFAULT_ARCHIVE_AFTER_DAYS,
            0,
            3650,
        ),
        "device_delete_archived_after_days": _int_setting(
            db,
            "device_delete_archived_after_days",
            DEFAULT_DELETE_ARCHIVED_AFTER_DAYS,
            0,
            3650,
        ),
    }


def apply_device_retention(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.utcnow()
    settings = get_device_retention_settings(db)
    archived = 0
    deleted = 0

    archive_after_days = settings["device_archive_after_days"]
    if archive_after_days > 0:
        archive_cutoff = now - timedelta(days=archive_after_days)
        stale_devices = (
            db.query(Device)
            .filter(Device.is_archived == False)
            .filter(Device.last_seen <= archive_cutoff)
            .all()
        )
        for device in stale_devices:
            device.is_archived = True
            device.archived_at = now
            device.is_online = False
            db.add(DeviceChangeEvent(
                device_id=device.id,
                event_type="device_archived",
                field_name="is_archived",
                old_value="false",
                new_value="true",
                source="retention",
                message=f"Archived after {archive_after_days} days without discovery",
            ))
            archived += 1

    delete_after_days = settings["device_delete_archived_after_days"]
    if delete_after_days > 0:
        delete_cutoff = now - timedelta(days=delete_after_days)
        archived_devices = (
            db.query(Device)
            .filter(Device.is_archived == True)
            .filter(Device.archived_at.isnot(None))
            .filter(Device.archived_at <= delete_cutoff)
            .all()
        )
        for device in archived_devices:
            db.delete(device)
            deleted += 1

    return {"archived": archived, "deleted": deleted}
