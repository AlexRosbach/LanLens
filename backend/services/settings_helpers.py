"""Shared helpers for parsing persisted application settings."""
from sqlalchemy.orm import Session

from ..models import Setting

DEFAULT_SCAN_INTERVAL_MINUTES = 5


def get_setting_value(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else default


def get_scan_interval_minutes(db: Session) -> int:
    """Return the configured scan interval, using the shared fallback behavior."""
    raw_value = get_setting_value(db, "scan_interval_minutes", str(DEFAULT_SCAN_INTERVAL_MINUTES))
    try:
        interval = int(raw_value or DEFAULT_SCAN_INTERVAL_MINUTES)
    except (TypeError, ValueError):
        return DEFAULT_SCAN_INTERVAL_MINUTES
    return max(1, interval)


def is_advanced_feature_enabled(db: Session, key: str) -> bool:
    """Return true only when the advanced view and the requested feature are enabled."""
    return (
        get_setting_value(db, "advanced_view_enabled", "false") == "true"
        and get_setting_value(db, key, "false") == "true"
    )
