#!/usr/bin/env bash
# LanLens outbound Linux inventory-agent installer. Run as root.
set -euo pipefail

SERVER_URL=""
ENROLLMENT_TOKEN=""
INTERVAL_MINUTES=60
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url) SERVER_URL="${2:-}"; shift 2 ;;
    --enrollment-token) ENROLLMENT_TOKEN="${2:-}"; shift 2 ;;
    --interval-minutes) INTERVAL_MINUTES="${2:-}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Run this installer as root." >&2; exit 1; }
[[ "$SERVER_URL" =~ ^https:// ]] || { echo "--server-url must use HTTPS." >&2; exit 1; }
[[ ${#ENROLLMENT_TOKEN} -ge 20 ]] || { echo "A valid --enrollment-token is required." >&2; exit 1; }
[[ "$INTERVAL_MINUTES" =~ ^[0-9]+$ && "$INTERVAL_MINUTES" -ge 5 && "$INTERVAL_MINUTES" -le 1440 ]] || { echo "--interval-minutes must be 5-1440." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required." >&2; exit 1; }

SERVER_URL="${SERVER_URL%/}"
INSTALL_DIR=/opt/lanlens-agent
CONFIG_DIR=/etc/lanlens-agent
umask 077
install -d -m 0755 "$INSTALL_DIR"
install -d -m 0700 "$CONFIG_DIR"
curl --fail --silent --show-error --proto '=https' "$SERVER_URL/api/agents/linux/lanlens-agent.py" -o "$INSTALL_DIR/lanlens-agent.py"
chmod 0755 "$INSTALL_DIR/lanlens-agent.py"

python3 - "$SERVER_URL" "$ENROLLMENT_TOKEN" "$INTERVAL_MINUTES" <<'PY'
import json, os, socket, subprocess, sys, urllib.request, tempfile
server, token, interval = sys.argv[1:]
def run(command):
    return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL).strip()
mac = ""
for name in os.listdir("/sys/class/net"):
    if name == "lo":
        continue
    try:
        candidate = open(f"/sys/class/net/{name}/address").read().strip()
        state = open(f"/sys/class/net/{name}/operstate").read().strip()
        if candidate != "00:00:00:00:00:00" and state in ("up", "unknown"):
            mac = candidate
            break
    except OSError:
        continue
if not mac:
    raise SystemExit("No active MAC address found.")
ips = run(["sh", "-c", "ip -o -4 addr show scope global | awk '{print $4}' | cut -d/ -f1"]).splitlines()
os_info = run(["sh", "-c", ". /etc/os-release 2>/dev/null; echo \"${PRETTY_NAME:-Linux}\""]) or "Linux"
payload = {"token": token, "hostname": socket.gethostname(), "primary_mac": mac, "os_info": os_info, "kernel_version": run(["uname", "-r"]), "ip_addresses": ips, "platform": "linux"}
request = urllib.request.Request(server + "/api/agents/enroll", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(request, timeout=30) as response:
    enrolled = json.load(response)
config = {"server_url": server, "agent_id": enrolled["agent_id"], "agent_secret": enrolled["agent_secret"], "interval_minutes": int(interval), "sequence": 0, "platform": "linux"}
fd, path = tempfile.mkstemp(dir="/etc/lanlens-agent")
try:
    with os.fdopen(fd, "w") as target:
        json.dump(config, target)
        target.flush()
        os.fsync(target.fileno())
    os.replace(path, "/etc/lanlens-agent/agent.json")
finally:
    if os.path.exists(path):
        os.unlink(path)
PY

cat >/etc/systemd/system/lanlens-agent.service <<'UNIT'
[Unit]
Description=LanLens Outbound Linux Inventory Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/lanlens-agent/lanlens-agent.py
Restart=always
RestartSec=15
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/etc/lanlens-agent
UMask=0077
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable lanlens-agent.service
systemctl restart lanlens-agent.service
echo "LanLens Linux Agent was installed, enrolled and started."
