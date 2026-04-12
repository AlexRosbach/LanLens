"""CMDB ID generation helper."""
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def generate_cmdb_id(db: Session, prefix: str = "DEV", digits: int = 4) -> str:
    """Generate the next available CMDB ID with the given prefix and zero-padded digits.

    Format: {PREFIX}-{0000}  e.g. DEV-0001, CMDB-00042
    Finds the highest existing number with this prefix and returns prefix-(max+1).
    """
    from ..models import Device

    pattern = f"{prefix}-"
    # Fetch all existing CMDB IDs that start with our prefix
    rows = (
        db.query(Device.cmdb_id)
        .filter(Device.cmdb_id.like(f"{pattern}%"))
        .all()
    )

    max_num = 0
    for (cid,) in rows:
        if cid and cid.startswith(pattern):
            try:
                num = int(cid[len(pattern):])
                if num > max_num:
                    max_num = num
            except (ValueError, TypeError):
                pass

    next_num = max_num + 1
    cmdb_id = f"{prefix}-{next_num:0{digits}d}"
    logger.debug("Generated CMDB ID: %s (next=%d, prefix=%s, digits=%d)", cmdb_id, next_num, prefix, digits)
    return cmdb_id


def get_cmdb_settings(db: Session) -> tuple[str, int]:
    """Return (prefix, digits) from settings, with defaults."""
    from ..models import Setting

    def _get(key: str, default: str) -> str:
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row and row.value else default

    prefix = _get("cmdb_id_prefix", "DEV").strip().upper() or "DEV"
    try:
        digits = int(_get("cmdb_id_digits", "4"))
        digits = max(1, min(digits, 10))
    except (ValueError, TypeError):
        digits = 4
    return prefix, digits
