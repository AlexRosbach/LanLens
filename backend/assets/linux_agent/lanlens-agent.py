#!/usr/bin/env python3
"""Outbound Linux inventory agent for LanLens."""
import json
import os
import socket
import subprocess
import time
import tempfile
import shlex
import urllib.request

CONFIG = "/etc/lanlens-agent/agent.json"
MAX_OUTPUT = 128000


def run(command):
    try:
        result = subprocess.run(command, shell=True, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=30, check=False)
        return result.stdout[:MAX_OUTPUT].strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def primary_network():
    for name in os.listdir("/sys/class/net"):
        if name == "lo":
            continue
        try:
            mac = open(f"/sys/class/net/{name}/address").read().strip()
            state = open(f"/sys/class/net/{name}/operstate").read().strip()
            if mac != "00:00:00:00:00:00" and state in ("up", "unknown"):
                ips = run(f"ip -o -4 addr show dev {shlex.quote(name)} | awk '{{print $4}}' | cut -d/ -f1").splitlines()
                return mac, ips
        except OSError:
            continue
    return "", []


def software():
    command = "if command -v dpkg-query >/dev/null; then dpkg-query -W -f='${binary:Package}\\t${Version}\\t${Architecture}\\n' | head -n 2000; elif command -v rpm >/dev/null; then rpm -qa --qf '%{NAME}\\t%{VERSION}-%{RELEASE}\\t%{ARCH}\\n' | head -n 2000; elif command -v apk >/dev/null; then apk info -v | head -n 2000; fi"
    result = []
    for line in run(command).splitlines()[:2000]:
        values = line.split("\t")
        if not values or not values[0]:
            continue
        item = {"name": values[0]}
        if len(values) > 1:
            item["version"] = values[1]
        if len(values) > 2:
            item["architecture"] = values[2]
        result.append(item)
    return result


def findings():
    commands = [
        ("hardware", "vendor", "cat /sys/class/dmi/id/sys_vendor 2>/dev/null"),
        ("hardware", "model", "cat /sys/class/dmi/id/product_name 2>/dev/null"),
        ("hardware", "serial", "cat /sys/class/dmi/id/product_serial 2>/dev/null"),
        ("hardware", "cpu", "lscpu 2>/dev/null"),
        ("hardware", "memory", "free -h 2>/dev/null"),
        ("hardware", "disks", "lsblk -d -o NAME,SIZE,TYPE,MODEL 2>/dev/null"),
        ("os", "release", "cat /etc/os-release 2>/dev/null"),
        ("os", "kernel", "uname -r"),
        ("os", "hostname", "hostname -f 2>/dev/null || hostname"),
        ("os", "uptime", "uptime"),
        ("service", "systemd_units", "systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null"),
        ("container", "docker_containers", "docker ps --format '{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}' 2>/dev/null"),
        ("container", "podman_containers", "podman ps --format '{{json .}}' 2>/dev/null"),
        ("hypervisor", "kvm_vms", "virsh list --all 2>/dev/null"),
        ("hypervisor", "proxmox_qemu", "qm list 2>/dev/null"),
    ]
    result = []
    for finding_type, key, command in commands:
        value = run(command)
        if value:
            result.append({"finding_type": finding_type, "key": key, "value": value, "source": "lanlens_linux_agent"})
    return result


def report(config):
    mac, ips = primary_network()
    if not mac:
        return
    config["sequence"] = int(config.get("sequence", 0)) + 1
    # Persist before sending so a lost acknowledgement cannot replay on restart.
    fd, path = tempfile.mkstemp(dir=os.path.dirname(CONFIG))
    try:
        with os.fdopen(fd, "w") as target:
            json.dump(config, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(path, CONFIG)
    finally:
        if os.path.exists(path):
            os.unlink(path)
    os_info = run(". /etc/os-release 2>/dev/null; echo \"${PRETTY_NAME:-Linux}\"") or "Linux"
    payload = {"sequence": config["sequence"], "hostname": socket.gethostname(), "primary_mac": mac,
               "os_info": os_info, "kernel_version": run("uname -r"), "ip_addresses": ips,
               "software": software(), "findings": findings(), "platform": "linux"}
    request = urllib.request.Request(config["server_url"].rstrip("/") + "/api/agents/report",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + config["agent_id"] + "." + config["agent_secret"]}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if not 200 <= response.status < 300:
                return
    except OSError:
        return


with open(CONFIG) as source:
    config = json.load(source)
while True:
    report(config)
    time.sleep(max(5, min(int(config.get("interval_minutes", 60)), 1440)) * 60)
