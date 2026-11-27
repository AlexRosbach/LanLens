"""Persist only explicitly selected, non-secret VMware operation diagnostics."""
import json
import logging

from ..models import VsphereDebugLog

logger = logging.getLogger(__name__)
MAX_LOGS = 2000


def log_vsphere(db, mode, level, message, details=None, device_id=None):
    # Call only at transaction boundaries, outside inventory mutations.
    # Never pass raw HTTP bodies, headers, credentials, URLs or exception text.
    logger.log(getattr(logging, level.upper(), logging.INFO), "VMware %s: %s %s",
               mode, message, json.dumps(details or {}, sort_keys=True))
    try:
        db.add(VsphereDebugLog(mode=mode, level=level, message=message,
                               details_json=json.dumps(details or {}, sort_keys=True),
                               device_id=device_id))
        db.flush()
        cutoff = db.query(VsphereDebugLog.id).order_by(VsphereDebugLog.id.desc()).offset(MAX_LOGS - 1).limit(1).scalar()
        if cutoff is not None:
            db.query(VsphereDebugLog).filter(VsphereDebugLog.id < cutoff).delete(synchronize_session=False)
        db.commit()
        if level == "error" and message not in {"vCenter API request rejected", "vCenter HTTPS request failed"}:
            from .diagnostic_notifications import queue_diagnostic
            queue_diagnostic(db, "system_error", "vsphere_" + mode, f"VMware / vSphere: {message}\nOperation: {mode}\n" + json.dumps(details or {}, sort_keys=True), device_id)
    except Exception:
        db.rollback()
        logger.warning("VMware diagnostic persistence failed")
