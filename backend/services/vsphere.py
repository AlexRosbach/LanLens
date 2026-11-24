"""Read-only vCenter 7+ discovery using the existing DNS-pinned TLS transport."""
from __future__ import annotations

import asyncio
import base64
from collections import Counter, defaultdict
from datetime import datetime
import ipaddress
import json
import re
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import Device, DeviceHostRelationship, DeviceIgnoreRule, Segment, VsphereInventoryObject
from .mac_vendor import normalize_mac
from .notification import request_json_via_validated_url
from .scanner import _matching_ignore_rules

MAX_HOSTS = 100
MAX_VMS = 500
MAX_DISKS = 128
VI_PATH = "/sdk/vim25/8.0.1.0"
VISIBLE_FIELDS = ("host_id", "cluster_id", "datacenter_id", "power_state", "macs", "ips",
                  "guest_os", "instance_uuid", "bios_uuid", "cpu_count", "memory_size_mib", "disks")


def visible_fields(row):
    if row and row.visible_fields_json:
        try:
            values = json.loads(row.visible_fields_json)
            if isinstance(values, list):
                return [key for key in VISIBLE_FIELDS if key in values]
        except (ValueError, TypeError):
            pass
    return list(VISIBLE_FIELDS)

ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class VsphereError(RuntimeError):
    pass


def validate_endpoint(value: str) -> str:
    try:
        p = urlsplit(value.strip())
        if (p.scheme != "https" or not p.hostname or p.username or p.password
                or p.path not in ("", "/") or p.query or p.fragment):
            raise ValueError
        _ = p.port
        return "https://" + p.netloc
    except ValueError:
        raise VsphereError("Use a valid vCenter HTTPS origin without credentials, path, query or fragment") from None


def _resource_id(value):
    if isinstance(value, str) and ID_PATTERN.fullmatch(value):
        return value
    raise VsphereError("vCenter returned an invalid inventory identifier")


def _text(value, maximum=255):
    return value.strip()[:maximum] if isinstance(value, str) else ""


def _mac(value):
    if not isinstance(value, str):
        return None
    mac = normalize_mac(value.strip())
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
        return None
    if mac == "00:00:00:00:00:00" or int(mac[:2], 16) & 1:
        return None
    return mac


def _ip(value):
    try:
        address = ipaddress.ip_address(value)
        if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
            return None
        return str(address)
    except (ValueError, TypeError):
        return None


def _uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _disk_uuid(value):
    # VMware also returns spaced hexadecimal VMDK UUIDs.
    if isinstance(value, str):
        return _uuid(value.replace(" ", ""))
    return None


def disk_inventory(rest_disks, vi_config):
    """Match disk devices by VM-scoped hardware key, never by UUID alone."""
    if not isinstance(rest_disks, dict):
        rest_disks = {}
    hardware = vi_config.get("hardware", {}) if isinstance(vi_config, dict) else {}
    devices = hardware.get("device", []) if isinstance(hardware, dict) else []
    vi_disks = {}
    for device in devices if isinstance(devices, list) else []:
        if isinstance(device, dict) and device.get("_typeName") == "VirtualDisk":
            key = str(device.get("key", ""))
            if ID_PATTERN.fullmatch(key):
                vi_disks[key] = device
    result = []
    for key in list(dict.fromkeys([*rest_disks, *vi_disks]))[:MAX_DISKS]:
        if not isinstance(key, str) or not ID_PATTERN.fullmatch(key):
            continue
        rest = rest_disks.get(key, {})
        vi = vi_disks.get(key, {})
        if not isinstance(rest, dict):
            rest = {}
        rb = rest.get("backing") or {}
        vb = vi.get("backing") or {}
        if not isinstance(rb, dict):
            rb = {}
        if not isinstance(vb, dict):
            vb = {}
        info = vi.get("deviceInfo") or {}
        capacity = rest.get("capacity", vi.get("capacityInBytes"))
        if capacity is None and type(vi.get("capacityInKB")) is int:
            capacity = vi["capacityInKB"] * 1024
        filename = _text(rb.get("vmdk_file") or vb.get("fileName"), 1024)
        result.append({"disk_id": key, "uuid": _disk_uuid(vb.get("uuid") or rb.get("uuid")),
                       "label": _text(rest.get("label") or (info.get("label") if isinstance(info, dict) else None)),
                       "capacity_bytes": capacity if type(capacity) is int and capacity >= 0 else None,
                       "backing_file": filename,
                       "datastore": filename[1:].split("]", 1)[0] if filename.startswith("[") and "]" in filename else None})
    return result


class VsphereClient:
    def __init__(self, endpoint, username, password, verify_tls=True, fields=None):
        self.endpoint = validate_endpoint(endpoint)
        self.username = username
        self.password = password
        self.verify_tls = verify_tls
        self.session = None
        self.fields = set(VISIBLE_FIELDS if fields is None else fields)
        self.vi_session = None
        self.vi_manager = None
        self.vcenter_uuid = None

    async def _request(self, method, path, login=False, optional=False):
        headers = {}
        if login:
            headers["Content-Length"] = "0"
            credentials = f"{self.username}:{self.password}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("ascii")
        elif self.session:
            headers["vmware-api-session-id"] = self.session
        try:
            response = await asyncio.wait_for(
                request_json_via_validated_url(self.endpoint + path, method=method,
                    headers=headers, timeout_seconds=12, label="vCenter HTTPS API", verify_tls=self.verify_tls),
                timeout=18,
            )
        except Exception:
            # Never pass exception text or HTTP response bodies containing credentials.
            raise VsphereError("vCenter connection failed. Check DNS, HTTPS certificate trust and connectivity.") from None
        if optional and response.status_code in (403, 404, 503):
            return None
        if not 200 <= response.status_code < 300:
            raise VsphereError(f"vCenter API returned HTTP {response.status_code}; check permissions and API version")
        if not response.text.strip():
            return None
        try:
            return json.loads(response.text)
        except ValueError:
            raise VsphereError("vCenter returned invalid JSON") from None

    async def login(self):
        token = await self._request("POST", "/api/session", login=True)
        if not isinstance(token, str) or not re.fullmatch(r"[!-~]{1,512}", token):
            raise VsphereError("vCenter did not return a valid session token")
        self.session = token

    async def logout(self):
        if self.session:
            try:
                await self._request("DELETE", "/api/session")
            except VsphereError:
                pass
            finally:
                self.session = None

    async def _vi_request(self, method, path, payload=None):
        headers = {"vmware-api-session-id": self.vi_session} if self.vi_session else {}
        try:
            response = await asyncio.wait_for(
                request_json_via_validated_url(self.endpoint + VI_PATH + path, method=method,
                    payload=payload, headers=headers, timeout_seconds=12, label="vCenter VI/JSON API",
                    verify_tls=self.verify_tls), timeout=18)
            if not 200 <= response.status_code < 300:
                return None, None
            data = json.loads(response.text) if response.text.strip() else None
            return data, response.vmware_session_id
        except Exception:
            return None, None

    async def vi_login(self):
        content, _ = await self._vi_request("GET", "/ServiceInstance/ServiceInstance/content")
        if not isinstance(content, dict):
            return False
        manager = content.get("sessionManager") or {}
        about = content.get("about") or {}
        if isinstance(about, dict):
            self.vcenter_uuid = _uuid(about.get("instanceUuid"))
        try:
            self.vi_manager = _resource_id(manager.get("value") if isinstance(manager, dict) else None)
        except VsphereError:
            return False
        _, token = await self._vi_request("POST", "/SessionManager/" + quote(self.vi_manager, safe="") + "/Login",
                                          {"userName": self.username, "password": self.password})
        if not isinstance(token, str) or not re.fullmatch(r"[!-~]{1,512}", token):
            return False
        self.vi_session = token
        return True

    async def vi_logout(self):
        if self.vi_session and self.vi_manager:
            try:
                await self._vi_request("POST", "/SessionManager/" + quote(self.vi_manager, safe="") + "/Logout", {})
            finally:
                self.vi_session = None

    async def hosts(self):
        data = await self._request("GET", "/api/vcenter/host")
        if not isinstance(data, list) or len(data) > MAX_HOSTS:
            raise VsphereError("Invalid or oversized host inventory (maximum 100 hosts)")
        return data

    async def test(self):
        await self.login()
        try:
            return {"ok": True, "host_count": len(await self.hosts())}
        finally:
            await self.logout()

    async def collect(self):
        # Ensure siblings stop before logging out when one request fails.
        async def gather_all(*coroutines):
            tasks = [asyncio.create_task(c) for c in coroutines]
            try:
                return await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        await self.login()
        try:
            hosts = {}
            for h in await self.hosts():
                if not isinstance(h, dict):
                    raise VsphereError("Invalid host inventory")
                hid = _resource_id(h.get("host"))
                hosts[hid] = {"kind": "host", "external_id": hid, "name": _text(h.get("name")) or hid,
                              "connection_state": _text(h.get("connection_state")),
                              "power_state": _text(h.get("power_state"))}
            # Global list catches unassigned VMs. Query per host to establish
            # placement; VM list summaries do not contain the host identifier.
            summary = await self._request("GET", "/api/vcenter/vm")
            if not isinstance(summary, list) or len(summary) > MAX_VMS:
                raise VsphereError("Invalid or oversized VM inventory (maximum 500 VMs)")
            semaphore = asyncio.Semaphore(6)

            async def get(path, optional=False):
                async with semaphore:
                    return await self._request("GET", path, optional=optional)

            async def placement(hid):
                data = await get("/api/vcenter/vm?" + urlencode({"hosts": hid}))
                if not isinstance(data, list) or len(data) > MAX_VMS:
                    raise VsphereError("Invalid host VM inventory")
                return hid, [_resource_id(v.get("vm")) for v in data if isinstance(v, dict)]

            warnings = []
            topology = {}

            async def topology_list(kind, query=""):
                data = await get("/api/vcenter/" + kind + query, optional=True)
                if data is None:
                    warnings.append("Topology unavailable: " + kind)
                    return []
                if not isinstance(data, list) or len(data) > MAX_HOSTS or any(not isinstance(x, dict) for x in data):
                    raise VsphereError("Invalid or oversized topology inventory")
                return data

            for kind in ("datacenter", "cluster"):
                for item in await topology_list(kind):
                    key = _resource_id(item.get(kind))
                    topology[(kind, key)] = {"kind": kind, "external_id": key, "name": _text(item.get("name")) or key}

            async def membership(kind, key):
                query = "?" + urlencode({kind + "s": key})
                members = await topology_list("host", query)
                clusters = await topology_list("cluster", query) if kind == "datacenter" else []
                return kind, key, members, clusters

            member_index = defaultdict(set)
            cluster_index = defaultdict(set)
            for kind, key, members, clusters in await gather_all(*(membership(k, v) for k, v in topology)):
                for member in members:
                    member_index[(_resource_id(member.get("host")), kind)].add(key)
                for cluster in clusters:
                    cluster_index[_resource_id(cluster.get("cluster"))].add(key)

            def unique(values):
                return next(iter(values)) if len(values) == 1 else None

            for (kind, key), item in topology.items():
                if kind == "cluster":
                    item["datacenter_id"] = unique(cluster_index[key])
            for hid, host in hosts.items():
                host["cluster_id"] = unique(member_index[(hid, "cluster")])
                host["datacenter_id"] = unique(member_index[(hid, "datacenter")])
            vi_ready = await self.vi_login() if "disks" in self.fields else False
            if not vi_ready and "disks" in self.fields:
                warnings.append("Disk backing UUIDs unavailable: VI/JSON requires vCenter 8.0 Update 1 or newer and read permissions")

            placements = defaultdict(set)
            for hid, ids in await gather_all(*(placement(hid) for hid in hosts)):
                for vid in ids:
                    placements[vid].add(hid)
            async def details(vm):
                if not isinstance(vm, dict):
                    raise VsphereError("Invalid VM inventory")
                vid = _resource_id(vm.get("vm"))
                path = "/api/vcenter/vm/" + quote(vid, safe="")
                detail = await get(path, optional=True)
                if not isinstance(detail, dict):
                    warnings.append("VM details unavailable: " + vid)
                    detail = {}
                identity = detail.get("identity") or {}
                if not isinstance(identity, dict):
                    identity = {}
                nics = detail.get("nics") or {}
                hardware_macs = sorted({m for nic in nics.values() if isinstance(nic, dict)
                                        if (m := _mac(nic.get("mac_address")))}) if isinstance(nics, dict) else []
                ips = set()
                guest_nets = await get(path + "/guest/networking/interfaces", optional=True)
                if isinstance(guest_nets, list):
                    for nic in guest_nets:
                        if not isinstance(nic, dict) or _mac(nic.get("mac_address")) not in hardware_macs:
                            continue
                        ip_info = nic.get("ip") or {}
                        for entry in ip_info.get("ip_addresses", []) if isinstance(ip_info, dict) else []:
                            if isinstance(entry, dict) and (addr := _ip(entry.get("ip_address"))):
                                ips.add(addr)
                placement_ids = placements.get(vid, set())
                host_id = unique(placement_ids)
                host = hosts.get(host_id, {})
                disks = []
                if "disks" in self.fields:
                    vi_config = None
                    if vi_ready:
                        async with semaphore:
                            vi_config, _ = await self._vi_request("GET", "/VirtualMachine/" + quote(vid, safe="") + "/config")
                        if not isinstance(vi_config, dict):
                            warnings.append("Disk UUID metadata unavailable: " + vid)
                    disks = disk_inventory(detail.get("disks"), vi_config)
                return {"kind": "vm", "external_id": vid, "name": _text(vm.get("name")) or vid,
                        "instance_uuid": _uuid(identity.get("instance_uuid")),
                        "bios_uuid": _uuid(identity.get("bios_uuid")),
                        "host_id": host_id, "cluster_id": host.get("cluster_id"), "datacenter_id": host.get("datacenter_id"),
                        "vcenter_uuid": self.vcenter_uuid, "disks": disks,
                        "power_state": _text(vm.get("power_state")), "guest_os": _text(detail.get("guest_os")),
                        "macs": hardware_macs, "ips": sorted(ips, key=lambda v: (":" in v, v)),
                        "cpu_count": vm.get("cpu_count") if isinstance(vm.get("cpu_count"), int) else None,
                        "memory_size_mib": vm.get("memory_size_mib") if isinstance(vm.get("memory_size_mib"), int) else None}

            vms = await gather_all(*(details(vm) for vm in summary))
            if len({v["external_id"] for v in vms}) != len(vms):
                raise VsphereError("vCenter returned duplicate VM identifiers")
            return list(hosts.values()) + vms + list(topology.values()), warnings[:30]
        finally:
            try:
                await self.vi_logout()
            finally:
                await self.logout()


def reconcile_inventory(db: Session, connection_id: int, objects: list[dict], now: datetime):
    """Use real NIC MACs only; never overwrite operator data or infer network reachability."""
    existing = db.query(Device).all()
    mac_index = defaultdict(list)
    ip_index = defaultdict(list)
    for d in existing:
        if m := _mac(d.mac_address):
            mac_index[m].append(d)
        if d.ip_address:
            ip_index[d.ip_address].append(d)
    old = {(r.kind, r.external_id): r for r in db.query(VsphereInventoryObject)
           .filter_by(connection_id=connection_id).all()}
    # Mark previous observations stale without deleting inventory or devices.
    for row in old.values():
        row.match_status = "stale"
    vm_mac_counts = Counter(m for item in objects if item["kind"] == "vm" for m in set(item.get("macs", [])))
    vm_uuid_counts = Counter(item.get("instance_uuid") for item in objects if item["kind"] == "vm" and item.get("instance_uuid"))
    vm_ip_counts = Counter(ip for item in objects if item["kind"] == "vm" for ip in set(item.get("ips", [])))
    rules = db.query(DeviceIgnoreRule).filter(DeviceIgnoreRule.enabled.is_(True)).all()
    segments = db.query(Segment).all()
    host_matches = {}
    claimed = set()
    counts = Counter()

    def record(item, device, status):
        key = (item["kind"], item["external_id"])
        row = old.get(key)
        if row is None:
            row = VsphereInventoryObject(connection_id=connection_id, kind=key[0], external_id=key[1])
            db.add(row)
        row.name = item["name"]
        if device:
            row.device_id = device.id
        elif not (item.get("instance_uuid") and row.instance_uuid == item.get("instance_uuid")):
            row.device_id = None
        row.instance_uuid = item.get("instance_uuid")
        row.metadata_json = json.dumps(item, ensure_ascii=False)
        row.match_status = status
        row.observed_at = now
        counts[status] += 1

    for item in objects:
        if item["kind"] in ("cluster", "datacenter"):
            record(item, None, "unmatched")

    for item in objects:
        if item["kind"] != "host":
            continue
        name = item["name"].casefold().rstrip(".")
        matches = [d for d in existing if name and name in (
            (d.hostname or "").casefold().rstrip("."), (d.ip_address or "").casefold())]
        d = matches[0] if len(matches) == 1 else None
        status = "ambiguous" if len(matches) > 1 else "unmatched"
        if d and not d.ignored and not d.is_archived:
            host_matches[item["external_id"]] = d
            claimed.add(d.id)
            status = "existing"
        elif d:
            status = "ignored"
            d = None
        record(item, d, status)

    for item in objects:
        if item["kind"] != "vm":
            continue
        macs = [m for m in item.get("macs", []) if _mac(m) == m]
        ips = item.get("ips", [])
        uid = item.get("instance_uuid")
        matches = {d.id: d for mac in macs for d in mac_index.get(mac, [])}
        previous = old.get(("vm", item["external_id"]))
        # A reused MoRef must not inherit the previous VM's device association.
        prior_id = previous.device_id if previous and uid and previous.instance_uuid == uid else None
        d = None
        status = "no_mac"
        if (any(vm_mac_counts[m] > 1 for m in macs) or len(matches) > 1
                or (uid and vm_uuid_counts[uid] > 1)
                or (prior_id and matches and prior_id not in matches)):
            status = "ambiguous"
        elif matches:
            candidate = next(iter(matches.values()))
            if candidate.id in claimed:
                status = "ambiguous"
            elif candidate.ignored or candidate.is_archived:
                status = "ignored"
            else:
                d, status = candidate, "existing"
        elif prior_id:
            # A stable VM with a changed NIC must not create a second device.
            status = "ambiguous"
        elif macs:
            if any(ip_index.get(ip) or vm_ip_counts[ip] > 1 for ip in ips):
                status = "ambiguous"
            elif any(_matching_ignore_rules(db, ip=ip, mac=mac, hostname=item["name"], device_class="VM",
                                           rules=rules, segments=segments)
                     for mac in macs for ip in (ips or [""])):
                status = "ignored"
            else:
                d = Device(mac_address=macs[0], hostname=item["name"], ip_address=ips[0] if ips else None,
                           os_info=item.get("guest_os") or None, device_class="VM", is_registered=False,
                           is_online=False, first_seen=now, last_seen=now)
                db.add(d)
                db.flush()
                mac_index[macs[0]].append(d)
                for ip in ips:
                    ip_index[ip].append(d)
                status = "created"
        if d:
            claimed.add(d.id)
            host = host_matches.get(item.get("host_id"))
            if host and host.id != d.id:
                relationship = db.query(DeviceHostRelationship).filter_by(
                    child_device_id=d.id, host_device_id=host.id, relationship_type="vm_on_host").first()
                identifier = "vsphere:" + (uid or item["external_id"])
                if relationship is None:
                    relationship = db.query(DeviceHostRelationship).filter_by(
                        child_device_id=d.id, match_source="vsphere", vm_identifier=identifier).first()
                    if relationship:
                        relationship.host_device_id = host.id
                        relationship.last_confirmed_at = now
                    else:
                        db.add(DeviceHostRelationship(child_device_id=d.id, host_device_id=host.id,
                            relationship_type="vm_on_host", match_source="vsphere", vm_identifier=identifier,
                            observed_at=now, last_confirmed_at=now))
                elif relationship.match_source == "vsphere":
                    relationship.last_confirmed_at = now
        record(item, d, status)
    db.flush()
    return dict(counts)
