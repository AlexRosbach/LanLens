"""
Per-device port scanner using nmap.
Performs a fast SYN scan of the top 1000 ports.
Requires nmap to be installed in the container.
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

INTERESTING_PORTS = {
    22: "ssh",
    80: "http",
    443: "https",
    3389: "rdp",
    8080: "http-alt",
    8443: "https-alt",
    5900: "vnc",
    23: "telnet",
    21: "ftp",
    25: "smtp",
    3306: "mysql",
    5432: "postgres",
    6379: "redis",
    27017: "mongodb",
}


def scan_ports(ip_address: str) -> Optional[Dict]:
    """
    Scan a single IP address with nmap.
    Returns a dict with open_ports list and protocol flags, or None on error.
    """
    try:
        import nmap

        nm = nmap.PortScanner()
        # -sS SYN scan (fast), -T4 aggressive timing, --top-ports 1000
        # Falls back to -sT if no raw socket (non-root)
        try:
            nm.scan(ip_address, arguments="-sS -T4 --top-ports 1000")
        except nmap.PortScannerError:
            nm.scan(ip_address, arguments="-sT -T4 --top-ports 1000")

        open_ports = []
        ssh_available = False
        rdp_available = False
        http_available = False
        https_available = False

        if ip_address not in nm.all_hosts():
            return {
                "open_ports": [],
                "ssh_available": False,
                "rdp_available": False,
                "http_available": False,
                "https_available": False,
            }

        host_data = nm[ip_address]
        for proto in host_data.all_protocols():
            ports = host_data[proto].keys()
            for port in sorted(ports):
                port_info = host_data[proto][port]
                if port_info["state"] == "open":
                    service_name = port_info.get("name", INTERESTING_PORTS.get(port, "unknown"))
                    open_ports.append({
                        "port": port,
                        "protocol": proto,
                        "service": service_name,
                        "state": "open",
                    })

                    if port == 22:
                        ssh_available = True
                    elif port == 3389:
                        rdp_available = True
                    elif port == 80:
                        http_available = True
                    elif port == 443:
                        https_available = True

        return {
            "open_ports": open_ports,
            "ssh_available": ssh_available,
            "rdp_available": rdp_available,
            "http_available": http_available,
            "https_available": https_available,
        }

    except Exception as e:
        logger.error(f"Port scan failed for {ip_address}: {e}")
        return None


async def scan_ports_async(ip_address: str) -> Optional[Dict]:
    """Non-blocking wrapper for scan_ports."""
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(None, scan_ports, ip_address)
