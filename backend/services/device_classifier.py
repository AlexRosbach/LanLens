"""
Heuristic device classification based on MAC vendor string, hostname, and open ports.
Returns one of the standard device classes.

Keep this conservative: an unknown device is safer as "Unknown" than being
documented as a server just because a broad vendor or hostname fragment matched.
"""
import re

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
    (["apple"], "Apple Workstation"),
    (["intel corporate", "dell", "hewlett packard", "lenovo", "acer", "asus", "msi"], "Workstation"),
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

    # Hostname hints. Server detection deliberately requires a token-like match;
    # a loose "srv" substring caused false server documentation in i-doit.
    for pattern, device_class in [
        (r"printer", "Printer"), (r"nas", "NAS"), (r"router", "Router"),
        (r"switch", "Switch"), (r"(^|[-_.])srv([0-9-_.]|$)", "Server"), (r"(^|[-_.])server([0-9-_.]|$)", "Server"),
        (r"(^|[-_.])esx(i)?([0-9-_.]|$)", "Server"), (r"(^|[-_.])hyperv([0-9-_.]|$)", "Server"),
        (r"(^|[-_.])proxmox([0-9-_.]|$)", "Server"),
        (r"(^|[-_.])vm([0-9-_.]|$)", "VM"), (r"(^|[-_.])pi([0-9-_.]|$)", "IoT"),
        (r"firewall", "Firewall"), (r"(^|[-_.])fw[-_.]", "Firewall"), (r"pfsense", "Firewall"), (r"fortigate", "Firewall"),
        (r"iphone", "Mobile"), (r"android", "Mobile"), (r"pixel", "Mobile"), (r"galaxy", "Mobile"),
        (r"mobile", "Mobile"), (r"phone", "VoIP"), (r"voip", "VoIP"), (r"(^|[-_.])sip[-_.]", "VoIP"),
        (r"camera", "Camera"), (r"(^|[-_.])cam[-_.]", "Camera"), (r"ipcam", "Camera"), (r"(^|[-_.])nvr([0-9-_.]|$)", "Camera"),
        (r"[-_.]tv($|[-_.])", "TV"), (r"smarttv", "TV"), (r"appletv", "TV"), (r"chromecast", "TV"),
        (r"[-_.]ap[-_.]", "AP"), (r"accesspoint", "AP"), (r"(^|[-_.])wap[-_.]", "AP"), (r"(^|[-_.])uap([0-9-_.]|$)", "AP"),
    ]:
        if re.search(pattern, hostname_lower):
            return device_class

    return "Unknown"
