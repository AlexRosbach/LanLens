"""Validation helpers for routed network discovery targets."""
import ipaddress
from typing import Optional

MAX_ROUTED_SCAN_TARGETS = 32
MAX_ROUTED_SCAN_HOSTS = 4096


def routed_target_address_count(target: str) -> int:
    """Return the number of IPv4 addresses covered by a canonical target."""
    return 1 if "/" not in target else ipaddress.IPv4Network(target, strict=False).num_addresses


def validate_nmap_target(raw_target: str) -> str:
    """Validate and canonicalize a routed nmap ping-scan target."""
    target = raw_target.strip()
    if not target:
        raise ValueError("empty scan target")

    if "/" not in target:
        try:
            return str(ipaddress.IPv4Address(target))
        except ValueError:
            pass

    try:
        network = ipaddress.IPv4Network(target, strict=False)
        if network.num_addresses > MAX_ROUTED_SCAN_HOSTS:
            raise ValueError(
                f"Scan target '{target}' is too large. "
                f"Use a smaller IPv4 CIDR with at most {MAX_ROUTED_SCAN_HOSTS} addresses."
            )
        return str(network)
    except ValueError as e:
        if "too large" in str(e):
            raise
        raise ValueError(f"Invalid scan target '{target}'. Use an IPv4 address or CIDR, e.g. 192.168.10.0/24") from e


def parse_additional_scan_targets(value: Optional[str]) -> list[str]:
    """Parse, validate, canonicalize, and de-duplicate configured routed scan targets."""
    if not value:
        return []

    targets: list[str] = []
    total_addresses = 0
    for part in value.replace("\n", ",").split(","):
        part = part.strip()
        if not part:
            continue
        target = validate_nmap_target(part)
        if target not in targets:
            if len(targets) >= MAX_ROUTED_SCAN_TARGETS:
                raise ValueError(f"Too many routed scan targets. Maximum is {MAX_ROUTED_SCAN_TARGETS}.")
            total_addresses += routed_target_address_count(target)
            if total_addresses > MAX_ROUTED_SCAN_HOSTS:
                raise ValueError(
                    f"Routed scan target set is too large. Maximum total size is {MAX_ROUTED_SCAN_HOSTS} addresses."
                )
            targets.append(target)
    return targets
