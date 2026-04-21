"""
Per-device port scanner using nmap.
Supports configurable port ranges and single-port scans.
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


def normalize_port_spec(port_spec: Optional[str]) -> Optional[str]:
    spec = (port_spec or "").strip().lower()
    if not spec:
        return None
    if spec == "top:1000":
        return "top:1000"
    if spec.startswith("top:"):
        try:
            n = int(spec[4:])
        except ValueError:
            return None
        return f"top:{n}" if n >= 1 else None

    tokens = [token.strip() for token in spec.split(',') if token.strip()]
    if not tokens:
        return None

    normalized_tokens = []
    for token in tokens:
        if '-' in token:
            parts = token.split('-', 1)
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                return None
            start = int(parts[0])
            end = int(parts[1])
            if start < 1 or end > 65535 or start > end:
                return None
            normalized_tokens.append(f"{start}-{end}")
        else:
            if not token.isdigit():
                return None
            port = int(token)
            if port < 1 or port > 65535:
                return None
            normalized_tokens.append(str(port))

    return ','.join(normalized_tokens)


def _build_nmap_args(port_spec: Optional[str]) -> str:
    """Convert a port specification to nmap scan arguments.

    Supported formats:
      - None / "" / "top:1000"  →  --top-ports 1000  (default)
      - "top:N"                 →  --top-ports N
      - "1-65535"               →  -p 1-65535
      - "22,80,443"             →  -p 22,80,443
      - "1-1024,8080,8443"      →  -p 1-1024,8080,8443
    """
    normalized = normalize_port_spec(port_spec)
    if not normalized or normalized == "top:1000":
        return "-sS -T4 --top-ports 1000"
    if normalized.startswith("top:"):
        return f"-sS -T4 --top-ports {int(normalized[4:])}"
    return f"-sS -T4 -p {normalized}"


def scan_ports(ip_address: str, port_spec: Optional[str] = None) -> Optional[Dict]:
    """Scan a single IP address with nmap using the given port specification.

    Returns a dict with open_ports list and protocol flags, or None on error.
    """
    try:
        import nmap

        nm = nmap.PortScanner()
        args = _build_nmap_args(port_spec)
        try:
            nm.scan(ip_address, arguments=args)
        except nmap.PortScannerError:
            # Fallback to TCP connect scan if SYN requires raw sockets
            fallback = args.replace("-sS", "-sT")
            nm.scan(ip_address, arguments=fallback)

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


def scan_single_port(ip_address: str, port: int) -> Optional[Dict]:
    """Scan exactly one port on the target and return the result."""
    if port < 1 or port > 65535:
        return None
    return scan_ports(ip_address, port_spec=str(port))


async def scan_ports_async(ip_address: str, port_spec: Optional[str] = None) -> Optional[Dict]:
    """Non-blocking wrapper for scan_ports."""
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(None, scan_ports, ip_address, port_spec)


async def scan_single_port_async(ip_address: str, port: int) -> Optional[Dict]:
    """Non-blocking wrapper for scan_single_port."""
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(None, scan_single_port, ip_address, port)
