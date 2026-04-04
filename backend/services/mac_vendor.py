"""
MAC address OUI vendor lookup.
Uses the manuf library which bundles the IEEE OUI database offline.
Falls back to 'Unknown' on any failure — no network calls during runtime.
"""
import logging

logger = logging.getLogger(__name__)

_parser = None


def _get_parser():
    global _parser
    if _parser is None:
        try:
            import manuf
            _parser = manuf.MacParser()
        except Exception as e:
            logger.warning(f"Could not load manuf MAC parser: {e}")
    return _parser


def lookup_vendor(mac: str) -> str:
    """Return vendor name for a MAC address, or 'Unknown'."""
    parser = _get_parser()
    if parser is None:
        return "Unknown"
    try:
        result = parser.get_manuf(mac)
        return result if result else "Unknown"
    except Exception:
        return "Unknown"


def normalize_mac(mac: str) -> str:
    """Normalize MAC to uppercase colon-separated format XX:XX:XX:XX:XX:XX."""
    mac = mac.upper().replace("-", ":").replace(".", ":")
    parts = mac.split(":")
    if len(parts) == 1 and len(mac) == 12:
        parts = [mac[i:i+2] for i in range(0, 12, 2)]
    return ":".join(parts)
