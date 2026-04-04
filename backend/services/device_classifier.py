"""
Heuristic device classification based on MAC vendor string, hostname, and open ports.
Returns one of the standard device classes.
"""

VENDOR_RULES = [
    # Networking gear
    (["cisco", "ubiquiti", "mikrotik", "netgear", "zyxel", "tp-link", "d-link", "juniper", "aruba", "ruckus"], "Router"),
    (["netgear switch", "hp procurve", "extreme networks", "brocade", "dell networking", "cisco catalyst"], "Switch"),
    # Servers / NAS
    (["synology", "qnap", "buffalo", "western digital"], "NAS"),
    (["dell emc", "hewlett packard enterprise", "supermicro", "ibm", "lenovo system x"], "Server"),
    # Workstations / PCs
    (["apple", "intel corporate", "dell", "hewlett packard", "lenovo", "acer", "asus", "msi"], "Workstation"),
    # IoT / Embedded
    (["raspberry pi", "espressif", "arduino", "particle", "nordic semiconductor", "texas instruments",
      "amazon", "google", "philips", "belkin", "ring", "nest", "xiaomi", "shelly", "tuya"], "IoT"),
    # Printers
    (["lexmark", "xerox", "ricoh", "brother", "canon", "epson", "konica", "sharp"], "Printer"),
    # VMs / Hypervisors
    (["vmware", "virtualbox", "parallels", "xensource", "proxmox"], "VM"),
]

PORT_CLASS_HINTS = {
    9100: "Printer",   # JetDirect
    515: "Printer",    # LPD
    631: "Printer",    # IPP
    3389: "Workstation",
    22: None,          # Too generic
}


def classify_device(vendor: str, hostname: str = "", open_ports: list = None) -> str:
    """
    Determine device class from available signals.
    Priority: port hints > vendor match > hostname match > Unknown
    """
    if open_ports is None:
        open_ports = []

    port_numbers = [p.get("port") if isinstance(p, dict) else p for p in open_ports]

    # Port-based hints (high confidence)
    for port, device_class in PORT_CLASS_HINTS.items():
        if port in port_numbers and device_class:
            return device_class

    vendor_lower = (vendor or "").lower()
    hostname_lower = (hostname or "").lower()

    for keywords, device_class in VENDOR_RULES:
        for kw in keywords:
            if kw in vendor_lower:
                return device_class

    # Hostname hints
    for kw, device_class in [
        ("printer", "Printer"), ("nas", "NAS"), ("router", "Router"),
        ("switch", "Switch"), ("srv", "Server"), ("server", "Server"),
        ("vm", "VM"), ("pi", "IoT"),
    ]:
        if kw in hostname_lower:
            return device_class

    return "Unknown"
