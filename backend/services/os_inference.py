"""Conservative OS-family inference from non-credentialed discovery evidence."""

from dataclasses import dataclass

from ..models import Device


@dataclass(frozen=True)
class OsFamilyInference:
    family: str
    confidence: str | None
    reasons: list[str]


WINDOWS_PORTS = {
    135: (2, "Microsoft RPC port 135 is open"),
    445: (2, "SMB port 445 is open"),
    3389: (3, "RDP port 3389 is open"),
    5985: (2, "WinRM port 5985 is open"),
    5986: (2, "WinRM HTTPS port 5986 is open"),
}

LINUX_PORTS = {
    22: (1, "SSH port 22 is open"),
    111: (2, "rpcbind port 111 is open"),
    2049: (2, "NFS port 2049 is open"),
}


def infer_os_family(device: Device, open_ports: list[int]) -> OsFamilyInference:
    """Estimate Linux/Windows without reading authoritative OS or deep-scan fields."""
    scores = {"Linux": 0, "Windows": 0}
    reasons: dict[str, list[str]] = {"Linux": [], "Windows": []}

    device_class = (device.device_class or "").lower()
    if "windows" in device_class:
        scores["Windows"] += 4
        reasons["Windows"].append(f"device class is {device.device_class}")
    if "linux" in device_class:
        scores["Linux"] += 4
        reasons["Linux"].append(f"device class is {device.device_class}")

    hostname = (device.hostname or "").lower()
    if hostname.startswith("win-") or hostname.startswith("windows-"):
        scores["Windows"] += 2
        reasons["Windows"].append("hostname has a Windows-style prefix")
    if any(token in hostname for token in ("ubuntu", "debian", "linux", "proxmox", "pve")):
        scores["Linux"] += 2
        reasons["Linux"].append("hostname contains a Linux-related name")

    vendor = (device.effective_vendor or "").lower()
    if "microsoft" in vendor:
        scores["Windows"] += 2
        reasons["Windows"].append("vendor contains Microsoft")

    for port in sorted(set(open_ports)):
        if port in WINDOWS_PORTS:
            weight, reason = WINDOWS_PORTS[port]
            scores["Windows"] += weight
            reasons["Windows"].append(reason)
        if port in LINUX_PORTS:
            weight, reason = LINUX_PORTS[port]
            scores["Linux"] += weight
            reasons["Linux"].append(reason)

    winner = "Linux" if scores["Linux"] > scores["Windows"] else "Windows"
    winner_score = scores[winner]
    runner_up_score = scores["Windows" if winner == "Linux" else "Linux"]
    if winner_score < 2 or winner_score == runner_up_score:
        return OsFamilyInference("Unknown", None, [])

    margin = winner_score - runner_up_score
    confidence = "high" if winner_score >= 5 and margin >= 3 else "medium" if winner_score >= 3 and margin >= 2 else "low"
    return OsFamilyInference(winner, confidence, reasons[winner])
