"""Safe diagnostic alerts, independent of discovery scheduling."""
import logging
import queue
from datetime import datetime, timedelta

from ..models import Notification, Setting
from ..version import BUILD_COMMIT

logger = logging.getLogger(__name__)
_pending = queue.Queue(maxsize=256)
REPEAT_MINUTES = 60


def queue_diagnostic(db, event_type, subtype, message, device_id=None):
    """Call after committing business state. Alert failure must not fail a sync."""
    try:
        setting = db.get(Setting, "notify_on_" + event_type)
        if not setting or setting.value != "true":
            return False
        cutoff = datetime.utcnow() - timedelta(minutes=REPEAT_MINUTES)
        existing = db.query(Notification.id).filter(
            Notification.event_type == event_type,
            Notification.event_subtype == subtype,
            Notification.device_id == device_id,
            Notification.message == message,
            Notification.created_at >= cutoff,
        ).first()
        if existing:
            return False
        db.add(Notification(event_type=event_type, event_subtype=subtype, device_id=device_id, message=message))
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.warning("Diagnostic notification could not be persisted")
        return False


def application_failure_message(device_id, device_name, mode, object_id, failures, total):
    lines = [f"i-doit: {len(failures)} application assignment(s) not synchronized",
             f"Device: {device_name} (#{device_id})", f"Mode: {mode}", f"i-doit object: {object_id}",
             f"Detected applications: {total}", f"Build: {BUILD_COMMIT}", "", "Affected applications:"]
    for item in sorted(failures, key=lambda x: (x["title"].casefold(), x["version"], x["reason"])):
        version = f' — {item["version"]}' if item["version"] else ""
        lines.append(f'- {item["title"]}{version} [{item["reason"]}]')
    return "\n".join(lines)


class SystemErrorHandler(logging.Handler):
    """Capture safe metadata, not arbitrary log messages, credentials or tracebacks."""
    def emit(self, record):
        if record.levelno < logging.ERROR or not record.name.startswith("backend."):
            return
        if record.name in {"backend.services.notification", __name__, "backend.services.vsphere_debug"}:
            return
        try:
            exc = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else "Error"
            message = (f"LanLens backend error\nComponent: {record.name}\n"
                       f"Location: {record.filename}:{record.lineno} ({record.funcName})\n"
                       f"Exception: {exc}\nBuild: {BUILD_COMMIT}\nSee backend logs for the full diagnostic.")
            _pending.put_nowait(message)
        except queue.Full:
            pass


system_error_handler = SystemErrorHandler(level=logging.ERROR)


def flush_system_errors(db):
    for _ in range(256):
        try:
            message = _pending.get_nowait()
        except queue.Empty:
            break
        queue_diagnostic(db, "system_error", "backend_log", message)
