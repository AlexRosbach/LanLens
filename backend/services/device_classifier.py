"""
Heuristic device classification based on MAC vendor string, hostname, and open ports.
Returns one of the standard device classes.
"""

VENDOR_RULES = [
    # Networking gear
    (["cisco", "ubiquiti", "mikrotik", "netgear", "zyxel", "tp-link", "d-link", "juniper", "aruba", "ruckus"], "Router"),
    (["netgear switch", "hp procurve", "extreme networks", "brocade", "dell networking", "cisco catalyst"], "Switch"),
    # Access Points (checked before generic Router to be more specific)
    (["cambium", "meraki", "aerohive", "xirrus", "meru"], "AP"),
    # Firewalls
    (["palo alto", "fortinet", "sonicwall", "check point", "sophos", "watchguard", "netgate", "barracuda"], "Firewall"),
    # Servers / NAS
    (["synology", "qnap", "buffalo", "western digital"], "NAS"),
    (["dell emc", "hewlett packard enterprise", "supermicro", "ibm", "lenovo system x"], "Server"),
    # Workstations / PCs
    (["apple", "intel corporate", "dell", "hewlett packard", "lenovo", "acer", "asus", "msi"], "Workstation"),
    # Mobile devices
    (["samsung mobile", "huawei device", "oneplus", "oppo", "vivo", "motorola mobility", "sony mobile",
      "lg mobile", "xiaomi communications", "realme"], "Mobile"),
    # IP Cameras / Surveillance
    (["axis", "dahua", "hikvision", "hanwha", "bosch security", "vivotek", "foscam", "reolink",
      "amcrest", "swann", "geovision"], "Camera"),
    # Smart TVs / Media Devices
    (["samsung smart tv", "lg smart tv", "vizio", "tcl", "roku", "fire tv", "apple tv"], "TV"),
    # VoIP
    (["polycom", "yealink", "grandstream", "snom", "avaya", "mitel", "cisco voip", "aastra"], "VoIP"),
    # IoT / Embedded
    (["raspberry pi", "espressif", "arduino", "particle", "nordic semiconductor", "texas instruments",
      "amazon", "google", "philips", "belkin", "ring", "nest", "xiaomi", "shelly", "tuya"], "IoT"),
    # Printers
    (["lexmark", "xerox", "ricoh", "brother", "canon", "epson", "konica", "sharp"], "Printer"),
    # VMs / Hypervisors
    (["vmware", "virtualbox", "parallels", "xensource", "proxmox"], "VM"),
]

PORT_CLASS_HINTS = {
    9100: "Printer",    # JetDirect
    515: "Printer",     # LPD
    631: "Printer",     # IPP
    5060: "VoIP",       # SIP
    5061: "VoIP",       # SIP TLS
    1720: "VoIP",       # H.323
    554: "Camera",      # RTSP
    8554: "Camera",     # RTSP alternative
    3389: "Workstation",
    22: None,           # Too generic
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
        ("firewall", "Firewall"), ("fw-", "Firewall"), ("pfsense", "Firewall"), ("fortigate", "Firewall"),
        ("iphone", "Mobile"), ("android", "Mobile"), ("pixel", "Mobile"), ("galaxy", "Mobile"),
        ("mobile", "Mobile"), ("phone", "VoIP"), ("voip", "VoIP"), ("sip-", "VoIP"),
        ("camera", "Camera"), ("cam-", "Camera"), ("ipcam", "Camera"), ("nvr", "Camera"),
        ("-tv", "TV"), ("smarttv", "TV"), ("appletv", "TV"), ("chromecast", "TV"),
        ("-ap-", "AP"), ("accesspoint", "AP"), ("wap-", "AP"), ("uap", "AP"),
    ]:
        if kw in hostname_lower:
            return device_class

    return "Unknown"
