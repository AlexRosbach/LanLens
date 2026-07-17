"""First-run network discovery bootstrap."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Device, ScanRun, Setting
from .scanner import _detect_host_network, _network_host_bounds

logger = logging.getLogger(__name__)

BOOTSTRAP_STATUS_KEY = "initial_scan_bootstrap_status"
BOOTSTRAP_NETWORK_KEY = "initial_scan_bootstrap_network"


def _setting_value(db: Session, key: str) -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row and row.value else ""


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
        row.updated_at = datetime.utcnow()
        return
    db.add(Setting(key=key, value=value, updated_at=datetime.utcnow()))


def _has_configured_scan_range(db: Session) -> bool:
    return bool(_setting_value(db, "scan_start") and _setting_value(db, "scan_end"))


def should_bootstrap_initial_scan(db: Session) -> bool:
    """Return True only for a genuinely fresh install without scan history."""
    if _has_configured_scan_range(db):
        return False
    if db.query(Device.id).limit(1).first():
        return False
    if db.query(ScanRun.id).limit(1).first():
        return False
    return True


def prepare_initial_scan_bootstrap(db: Session) -> bool:
    """Persist the detected first-run scan target and report whether to scan now."""
    if not should_bootstrap_initial_scan(db):
        return False

    try:
        network = _detect_host_network()
    except Exception as exc:
        logger.warning("Initial network detection failed: %s", exc)
        _set_setting(db, BOOTSTRAP_STATUS_KEY, "detect_failed")
        db.commit()
        return False

    if not network:
        logger.warning("Initial network detection did not find a usable IPv4 subnet")
        _set_setting(db, BOOTSTRAP_STATUS_KEY, "detect_failed")
        db.commit()
        return False

    start, end = _network_host_bounds(network)
    _set_setting(db, "scan_start", start)
    _set_setting(db, "scan_end", end)
    _set_setting(db, BOOTSTRAP_NETWORK_KEY, str(network))
    _set_setting(db, BOOTSTRAP_STATUS_KEY, "scheduled")
    db.commit()
    logger.info("Prepared initial scan for detected host network %s (%s - %s)", network, start, end)
    return True
