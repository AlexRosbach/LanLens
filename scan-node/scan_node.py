#!/usr/bin/env python3
"""Minimal LanLens Scan Node.

Runs inside a VLAN/site, discovers local hosts with nmap ping scan and reports
the normalized result set to the central LanLens instance. The node has no
inbound API; it only needs outbound HTTPS to Central.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


CENTRAL_URL = env("LANLENS_CENTRAL_URL").rstrip("/")
TOKEN = env("LANLENS_NODE_TOKEN")
NODE_NAME = env("LANLENS_NODE_NAME", "scan-node")
INTERVAL = max(30, int(env("LANLENS_SCAN_INTERVAL", "300") or "300"))
TARGETS = [item.strip() for item in env("LANLENS_SCAN_TARGETS").replace("\n", ",").split(",") if item.strip()]
VERSION = env("LANLENS_SCAN_NODE_VERSION", "dev")


def detect_targets() -> list[str]:
    if TARGETS:
        return TARGETS
    try:
        output = subprocess.check_output(["ip", "-o", "-f", "inet", "addr", "show", "scope", "global"], text=True)
    except Exception:
        return []
    targets: list[str] = []
    for line in output.splitlines():
        parts = line.split()
        if "inet" in parts:
            cidr = parts[parts.index("inet") + 1]
            if not cidr.startswith("127."):
                targets.append(cidr)
    return targets


def scan(targets: list[str]) -> list[dict]:
    if not targets:
        return []
    cmd = ["nmap", "-sn", "-oX", "-", *targets]
    output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=max(60, len(targets) * 60))
    root = ET.fromstring(output)
    hosts: list[dict] = []
    for host in root.findall("host"):
        status = host.find("status")
        if status is not None and status.get("state") != "up":
            continue
        item: dict[str, str] = {}
        for address in host.findall("address"):
            addr_type = address.get("addrtype")
            if addr_type == "ipv4":
                item["ip"] = address.get("addr", "")
            elif addr_type == "mac":
                item["mac"] = address.get("addr", "")
        hostnames = host.find("hostnames")
        if hostnames is not None:
            hostname = hostnames.find("hostname")
            if hostname is not None and hostname.get("name"):
                item["hostname"] = hostname.get("name")
        if item.get("ip"):
            hosts.append(item)
    return hosts


def report(hosts: list[dict]) -> None:
    payload = json.dumps({"version": VERSION, "hosts": hosts}).encode("utf-8")
    request = urllib.request.Request(
        f"{CENTRAL_URL}/api/scan-nodes/ingest",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def main() -> None:
    if not CENTRAL_URL or not TOKEN:
        raise SystemExit("LANLENS_CENTRAL_URL and LANLENS_NODE_TOKEN are required")
    print(f"LanLens Scan Node {NODE_NAME} starting; interval={INTERVAL}s", flush=True)
    while True:
        try:
            targets = detect_targets()
            hosts = scan(targets)
            report(hosts)
            print(f"reported {len(hosts)} hosts from {', '.join(targets) or 'no targets'}", flush=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, urllib.error.URLError, ET.ParseError) as exc:
            print(f"scan/report failed: {exc}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
