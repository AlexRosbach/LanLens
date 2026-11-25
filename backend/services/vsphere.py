"""vCenter discovery and optional annotation writeback via DNS-pinned TLS."""
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

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Device, DeviceHostRelationship, DeviceIgnoreRule, Segment, VsphereConnection, VsphereInventoryObject, IdoitDeviceSync
from .mac_vendor import normalize_mac
from .notification import request_json_via_validated_url
from .scanner import _matching_ignore_rules

MAX_HOSTS = 100
MAX_VMS = 5000
MAX_NETWORKS = 2000
MAX_DISKS = 128
VI_PATH = "/sdk/vim25/8.0.1.0"
IDOIT_VSPHERE_FIELDS = {"vsphere_" + name for name in (
    "instance_uuid", "bios_uuid", "vcenter_uuid", "host", "cluster", "datacenter",
    "power_state", "disk_uuids", "disk_inventory")}

VISIBLE_FIELDS = ("host_id", "cluster_id", "datacenter_id", "power_state", "macs", "ips",
                  "guest_os", "instance_uuid", "bios_uuid", "cpu_count", "memory_size_mib", "disks")


def attribute_mappings(row):
    try:
        raw = json.loads(row.attribute_mappings_json or "{}") if row else {}
        return {str(k): v for k, v in raw.items() if re.fullmatch(r"-?\d{1,10}", str(k)) and isinstance(v, str) and v.strip()} if isinstance(raw, dict) else {}
    except (ValueError, TypeError):
        return {}


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
    def __init__(self, endpoint, username, password, verify_tls=True, fields=None, attribute_keys=None):
        self.endpoint = validate_endpoint(endpoint)
        self.username = username
        self.password = password
        self.verify_tls = verify_tls
        self.session = None
        self.fields = set(VISIBLE_FIELDS if fields is None else fields)
        self.attribute_keys = {int(key) for key in (attribute_keys or [])}
        self.vi_session = None
        self.vi_manager = None
        self.custom_fields_manager = None
        self.vcenter_uuid = None
        self.diagnostic = None

    def _diagnose(self, level, message, **details):
        if self.diagnostic:
            self.diagnostic(level, message, details)

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
            self._diagnose("error", "vCenter HTTPS request failed", method=method, operation="session" if login else "inventory")
            # Never pass exception text or HTTP response bodies containing credentials.
            raise VsphereError("vCenter connection failed. Check DNS, HTTPS certificate trust and connectivity.") from None
        if optional and response.status_code in (403, 404, 503):
            return None
        if not 200 <= response.status_code < 300:
            self._diagnose("error", "vCenter API request rejected", method=method, status_code=response.status_code,
                           operation="session" if login else "inventory")
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
        self._diagnose("info", "vCenter REST session established")

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
        custom_manager = content.get("customFieldsManager") or {}
        if isinstance(custom_manager, dict) and isinstance(custom_manager.get("value"), str) and ID_PATTERN.fullmatch(custom_manager["value"]):
            self.custom_fields_manager = custom_manager["value"]
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

    async def _custom_fields(self):
        if not self.custom_fields_manager:
            raise VsphereError("CustomFieldsManager unavailable")
        path = "/CustomFieldsManager/" + quote(_resource_id(self.custom_fields_manager), safe="")
        fields, _ = await self._vi_request("GET", path + "/field")
        if not isinstance(fields, list):
            raise VsphereError("Could not read vCenter custom attributes; check permissions")
        return [{"key": f["key"], "name": f["name"]} for f in fields
                if isinstance(f, dict) and type(f.get("key")) is int
                and isinstance(f.get("name"), str) and f["name"]
                and f.get("managedObjectType") in (None, "", "VirtualMachine")]

    async def _read_vm_attributes(self, vm_id, selected):
        path = "/VirtualMachine/" + quote(_resource_id(vm_id), safe="")
        raw, _ = await self._vi_request("GET", path + "/customValue")
        if not isinstance(raw, list):
            raw, _ = await self._vi_request("GET", path + "/value")
        if not isinstance(raw, list):
            summary, _ = await self._vi_request("GET", path + "/summary")
            raw = summary.get("customValue") if isinstance(summary, dict) else None
        if not isinstance(raw, list):
            return None
        groups = defaultdict(list)
        for item in raw:
            if isinstance(item, dict) and type(item.get("key")) is int and item["key"] in selected and isinstance(item.get("value"), str):
                groups[item["key"]].append(item["value"][:2048])
        return {str(key): values[0] for key, values in groups.items() if len(values) == 1}

    async def list_custom_fields(self):
        try:
            if not await self.vi_login():
                raise VsphereError("Custom attributes require vCenter 8.0 Update 1 or newer")
            return await self._custom_fields()
        finally:
            await self.vi_logout()

    async def write_sysid_custom_field(self, vm_id, instance_uuid, sysid, key, vcenter_uuid=None):
        if not _uuid(instance_uuid) or type(key) is not int or not isinstance(sysid, str) or not ID_PATTERN.fullmatch(sysid):
            raise VsphereError("Invalid VM identity, field key or SYSID")
        vm_id = _resource_id(vm_id)
        path = "/VirtualMachine/" + quote(vm_id, safe="")
        try:
            if not await self.vi_login():
                raise VsphereError("Custom attribute writeback requires vCenter 8.0 Update 1 or newer")
            if vcenter_uuid and _uuid(vcenter_uuid) != self.vcenter_uuid:
                raise VsphereError("vCenter identity changed; writeback refused")
            config, _ = await self._vi_request("GET", path + "/config")
            if not isinstance(config, dict) or _uuid(config.get("instanceUuid")) != _uuid(instance_uuid):
                raise VsphereError("VM identity changed or could not be verified")
            if key not in {f["key"] for f in await self._custom_fields()}:
                raise VsphereError("Configured custom attribute is not available for VMs")
            values, _ = await self._vi_request("GET", path + "/customValue")
            if not isinstance(values, list):
                raise VsphereError("Could not read existing custom attributes")
            current = [v.get("value") for v in values if isinstance(v, dict) and v.get("key") == key]
            if current == [sysid]:
                return "unchanged"
            if any(v not in (None, "") for v in current):
                raise VsphereError("Target custom attribute already contains a different value; refusing overwrite")
            manager = "/CustomFieldsManager/" + quote(_resource_id(self.custom_fields_manager), safe="")
            await self._vi_request("POST", manager + "/SetField",
                                   {"entity": {"type": "VirtualMachine", "value": vm_id}, "key": key, "value": sysid})
            values, _ = await self._vi_request("GET", path + "/customValue")
            if not isinstance(values, list) or not any(isinstance(v, dict) and v.get("key") == key and v.get("value") == sysid for v in values):
                raise VsphereError("Custom attribute write could not be verified")
            return "updated"
        finally:
            await self.vi_logout()

    async def write_sysid_annotation(self, vm_id, instance_uuid, sysid):
        """Guard against reused VM references and concurrent annotation edits."""
        if not _uuid(instance_uuid):
            raise VsphereError("VM instance UUID unavailable; writeback refused")
        path = "/VirtualMachine/" + quote(_resource_id(vm_id), safe="")
        try:
            if not await self.vi_login():
                raise VsphereError("SYSID writeback requires vCenter 8.0 Update 1 or newer and appropriate permissions")
            config, _ = await self._vi_request("GET", path + "/config")
            if not isinstance(config, dict) or _uuid(config.get("instanceUuid")) != _uuid(instance_uuid):
                raise VsphereError("VM identity changed or could not be verified")
            version = config.get("changeVersion")
            old = config.get("annotation", "")
            if not isinstance(version, str) or not version or not isinstance(old, str):
                raise VsphereError("VM annotation or configuration version unavailable")
            new = sysid_annotation(old, sysid)
            if new == old:
                return "unchanged"
            task, _ = await self._vi_request("POST", path + "/ReconfigVM_Task",
                                              {"spec": {"changeVersion": version, "annotation": new}})
            if not isinstance(task, dict) or task.get("type") != "Task":
                raise VsphereError("VM annotation update rejected; check annotation permission")
            task_path = "/Task/" + quote(_resource_id(task.get("value")), safe="") + "/info"
            async def wait_for_task():
                while True:
                    info, _ = await self._vi_request("GET", task_path)
                    if not isinstance(info, dict) or info.get("state") not in ("queued", "running", "success", "error"):
                        raise VsphereError("VM annotation task result unavailable")
                    if info["state"] == "error":
                        raise VsphereError("VM annotation task failed")
                    if info["state"] == "success":
                        return
                    await asyncio.sleep(1)
            await asyncio.wait_for(wait_for_task(), timeout=25)
            return "updated"
        finally:
            await self.vi_logout()

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
            self._diagnose("info", "ESXi hosts collected", count=len(hosts))
            warnings = []
            try:
                summary = await self._request("GET", "/api/vcenter/vm")
            except VsphereError:
                summary = None
                warnings.append("Global VM listing unavailable; using host-scoped VM lists")
                self._diagnose("warning", "Global VM listing unavailable; trying host-scoped lists")
            if summary is not None and (not isinstance(summary, list) or len(summary) > MAX_VMS):
                raise VsphereError(f"Invalid or oversized VM inventory (maximum {MAX_VMS} VMs)")
            self._diagnose("info", "Global VM listing processed", count=len(summary or []))
            semaphore = asyncio.Semaphore(10)

            async def get(path, optional=False):
                async with semaphore:
                    return await self._request("GET", path, optional=optional)

            async def placement(hid):
                data = await get("/api/vcenter/vm?" + urlencode({"hosts": hid}))
                if not isinstance(data, list) or len(data) > MAX_VMS:
                    raise VsphereError("Invalid host VM inventory")
                return hid, data
            topology = {}

            async def topology_list(kind, query=""):
                data = await get("/api/vcenter/" + kind + query, optional=True)
                if data is None:
                    warnings.append("Topology unavailable: " + kind)
                    return []
                if not isinstance(data, list) or len(data) > (MAX_NETWORKS if kind == "network" else MAX_HOSTS) or any(not isinstance(x, dict) for x in data):
                    raise VsphereError("Invalid or oversized topology inventory")
                return data

            for kind in ("datacenter", "cluster", "network"):
                for item in await topology_list(kind):
                    key = _resource_id(item.get(kind))
                    topology[(kind, key)] = {"kind": kind, "external_id": key, "name": _text(item.get("name")) or key}
                    if kind == "network":
                        topology[(kind, key)]["network_type"] = _text(item.get("type"))

            self._diagnose("info", "Topology collected", **{kind: sum(k == kind for k, _ in topology) for kind in ("datacenter", "cluster", "network")})

            async def membership(kind, key):
                query = "?" + urlencode({kind + "s": key})
                members = await topology_list("host", query)
                clusters = await topology_list("cluster", query) if kind == "datacenter" else []
                return kind, key, members, clusters

            member_index = defaultdict(set)
            cluster_index = defaultdict(set)
            for kind, key, members, clusters in await gather_all(*(membership(k, v) for k, v in topology if k != "network")):
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
            vi_ready = await self.vi_login() if "disks" in self.fields or self.attribute_keys else False
            selected_attributes = set()
            if self.attribute_keys:
                if vi_ready:
                    try:
                        selected_attributes = self.attribute_keys & {field["key"] for field in await self._custom_fields()}
                    except VsphereError:
                        warnings.append("VM custom attribute definitions unavailable")
                    else:
                        if selected_attributes != self.attribute_keys:
                            warnings.append("One or more configured VM custom attributes are unavailable")
                else:
                    warnings.append("VM custom attributes require VI/JSON access")
            if not vi_ready and "disks" in self.fields:
                warnings.append("Disk backing UUIDs unavailable: VI/JSON requires vCenter 8.0 Update 1 or newer and read permissions")

            placements = defaultdict(set)
            vm_index = {}
            for vm in summary or []:
                if not isinstance(vm, dict):
                    raise VsphereError("Invalid VM inventory")
                vid = _resource_id(vm.get("vm"))
                if vid in vm_index:
                    raise VsphereError("vCenter returned duplicate VM identifiers")
                vm_index[vid] = vm
            for hid, host_vms in await gather_all(*(placement(hid) for hid in hosts)):
                for vm in host_vms:
                    if not isinstance(vm, dict):
                        raise VsphereError("Invalid host VM inventory")
                    vid = _resource_id(vm.get("vm"))
                    placements[vid].add(hid)
                    vm_index.setdefault(vid, vm)
            if len(vm_index) > MAX_VMS:
                raise VsphereError(f"VM inventory exceeds {MAX_VMS} VMs")
            summary = list(vm_index.values())
            self._diagnose("info", "Host-scoped VM inventory collected; fetching VM details", count=len(summary))
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
                attributes = {}
                if selected_attributes:
                    async with semaphore:
                        values = await self._read_vm_attributes(vid, selected_attributes)
                    if values is None:
                        warnings.append("VM custom attributes unavailable: " + vid)
                    else:
                        attributes = values
                return {"kind": "vm", "external_id": vid, "name": _text(vm.get("name")) or vid,
                        "attributes": attributes,
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
            self._diagnose("info", "VM detail collection completed", count=len(vms), warning_count=len(warnings),
                           with_mac=sum(bool(v["macs"]) for v in vms), with_ip=sum(bool(v["ips"]) for v in vms),
                           selected_attribute_count=len(selected_attributes), vms_with_attributes=sum(bool(v["attributes"]) for v in vms))
            return list(hosts.values()) + vms + list(topology.values()), warnings[:30]
        finally:
            try:
                await self.vi_logout()
            finally:
                await self.logout()


def reconcile_inventory(db: Session, connection_id: int, objects: list[dict], now: datetime):
    """Match by MAC, IP, exact hostname and prior UUID; preserve operator data."""
    existing = db.query(Device).all()
    mac_index = defaultdict(list)
    ip_index = defaultdict(list)
    name_index = defaultdict(list)
    for d in existing:
        if m := _mac(d.mac_address):
            mac_index[m].append(d)
        if d.ip_address:
            ip_index[d.ip_address].append(d)
        if d.hostname:
            name_index[d.hostname.casefold().rstrip(".")].append(d)
    old = {(r.kind, r.external_id): r for r in db.query(VsphereInventoryObject)
           .filter_by(connection_id=connection_id).all()}
    # Mark previous observations stale without deleting inventory or devices.
    for row in old.values():
        row.match_status = "stale"
    vm_mac_counts = Counter(m for item in objects if item["kind"] == "vm" for m in set(item.get("macs", [])))
    vm_uuid_counts = Counter(item.get("instance_uuid") for item in objects if item["kind"] == "vm" and item.get("instance_uuid"))
    vm_ip_counts = Counter(ip for item in objects if item["kind"] == "vm" for ip in set(item.get("ips", [])))
    vm_name_counts = Counter(item["name"].casefold().rstrip(".") for item in objects if item["kind"] == "vm")
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
        if item["kind"] in ("cluster", "datacenter", "network"):
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
        ip_matches = {d.id: d for ip in ips for d in ip_index.get(ip, [])}
        name = item["name"].casefold().rstrip(".")
        name_matches = {d.id: d for d in name_index.get(name, [])} if name else {}
        previous = old.get(("vm", item["external_id"]))
        # A reused MoRef must not inherit the previous VM's device association.
        prior_id = previous.device_id if previous and uid and previous.instance_uuid == uid else None
        candidates = set(matches) | set(ip_matches) | set(name_matches)
        candidate = None
        for index in (matches, ip_matches, name_matches):
            if index:
                candidate = next(iter(index.values()))
                break
        d = None
        status = "no_mac"
        if (any(vm_mac_counts[m] > 1 for m in macs)
                or (uid and vm_uuid_counts[uid] > 1)
                or len(candidates) > 1
                or (prior_id and candidates and prior_id not in candidates)
                or (not matches and ip_matches and any(vm_ip_counts[ip] > 1 for ip in ips))
                or (not matches and not ip_matches and name_matches and vm_name_counts[name] > 1)):
            status = "ambiguous"
        elif candidate:
            real_mac = _mac(candidate.mac_address)
            if (candidate.id in claimed
                    or (real_mac and macs and real_mac not in macs)
                    or (real_mac and real_mac not in macs and vm_mac_counts[real_mac] > 0)):
                status = "ambiguous"
            elif candidate.ignored or candidate.is_archived:
                status = "ignored"
            else:
                d, status = candidate, "existing"
                # Upgrade only the scanner's synthetic IP identifier, never a real MAC.
                if macs and candidate.mac_address and candidate.mac_address.lower().startswith("ip:"):
                    candidate.mac_address = macs[0]
                    mac_index[macs[0]].append(candidate)
        elif prior_id:
            # A stable VM with a changed NIC must not create a second device.
            status = "ambiguous"
        elif macs:
            if any(vm_ip_counts[ip] > 1 for ip in ips):
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
                if name:
                    name_index[name].append(d)
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
    connection = db.get(VsphereConnection, connection_id)
    if connection and connection.read_sysid and connection.sysid_field_key is not None:
        key = str(connection.sysid_field_key)
        vm_rows = [item for item in objects if item["kind"] == "vm"]
        observed = Counter(str(item.get("attributes", {}).get(key, "")).strip().casefold() for item in vm_rows)
        for row in db.query(VsphereInventoryObject).filter_by(connection_id=connection_id, kind="vm").filter(
            VsphereInventoryObject.match_status.in_(("existing", "created")), VsphereInventoryObject.device_id.is_not(None)
        ):
            metadata = json.loads(row.metadata_json)
            value = str(metadata.get("attributes", {}).get(key, "")).strip()
            if not value:
                continue
            device = db.get(Device, row.device_id)
            if (not ID_PATTERN.fullmatch(value) or not row.instance_uuid or observed[value.casefold()] != 1
                    or not device or _mac(device.mac_address) not in metadata.get("macs", [])):
                counts["sysid_conflict"] += 1
                continue
            state = db.query(IdoitDeviceSync).filter_by(device_id=row.device_id).first()
            if state and (state.idoit_sysid or state.idoit_object_id):
                if state.idoit_sysid != value:
                    counts["sysid_conflict"] += 1
                continue
            if db.query(IdoitDeviceSync).filter(func.lower(IdoitDeviceSync.idoit_sysid) == value.lower()).first():
                counts["sysid_conflict"] += 1
                continue
            if state is None:
                state = IdoitDeviceSync(device_id=row.device_id, status="never_synced")
                db.add(state)
            state.idoit_sysid = value
            db.flush()
            counts["sysid_imported"] += 1
    return dict(counts)


def device_vsphere_inventory(db, device_id):
    """Return current, source-labelled observations without modifying guest-scan data."""
    connection = db.get(VsphereConnection, 1)
    if not connection or not connection.enabled:
        return []
    rows = db.query(VsphereInventoryObject).filter_by(connection_id=1, device_id=device_id).filter(
        VsphereInventoryObject.match_status.in_(("existing", "created", "stale"))
    ).all()
    current = [row for row in rows if row.match_status != "stale"]
    candidates = current or rows
    if len(candidates) != 1:
        return []
    row = candidates[0]
    data = json.loads(row.metadata_json)
    fields = visible_fields(connection)
    metadata = {k: data[k] for k in fields if k in data and data[k] not in (None, "", [], {})}
    for kind in ("host", "cluster", "datacenter"):
        key = kind + "_id"
        if key in metadata:
            topology = db.query(VsphereInventoryObject).filter_by(connection_id=1, kind=kind, external_id=metadata[key]).first()
            if topology:
                metadata[key] = topology.name
    attrs = data.get("attributes", {})
    custom = [{"key": key, "label": label, "value": attrs[key]} for key, label in attribute_mappings(connection).items() if key in attrs]
    return [{"name": row.name, "external_id": row.external_id, "kind": row.kind,
             "match_status": row.match_status, "observed_at": row.observed_at.isoformat() + "Z",
             "fields": metadata, "custom_fields": custom}]


def vmware_dashboard_inventory(db, device_ids):
    """Read discovery sources and hardware fallbacks in one joined query."""
    if not device_ids:
        return set(), {}
    source_ids = set()
    summaries = defaultdict(list)
    for row, fields_json in db.query(VsphereInventoryObject, VsphereConnection.visible_fields_json).join(
        VsphereConnection, VsphereConnection.id == VsphereInventoryObject.connection_id
    ).filter(
        VsphereConnection.id == 1, VsphereConnection.enabled.is_(True),
        VsphereInventoryObject.device_id.in_(device_ids),
        VsphereInventoryObject.match_status.in_(("existing", "created")),
    ):
        source_ids.add(row.device_id)
        if row.kind != "vm":
            continue
        try:
            fields = json.loads(fields_json) if fields_json else list(VISIBLE_FIELDS)
            if not isinstance(fields, list):
                fields = list(VISIBLE_FIELDS)
        except (ValueError, TypeError):
            fields = list(VISIBLE_FIELDS)
        data = json.loads(row.metadata_json)
        cpu, ram = data.get("cpu_count"), data.get("memory_size_mib")
        parts = []
        if "cpu_count" in fields and type(cpu) is int and cpu > 0:
            parts.append(f"{cpu} vCPU")
        if "memory_size_mib" in fields and type(ram) is int and ram > 0:
            parts.append(f"{ram / 1024:g} GiB RAM")
        summaries[row.device_id].append("VMware: " + " · ".join(parts) if parts else "")
    return source_ids, {key: values[0] for key, values in summaries.items() if len(values) == 1 and values[0]}


def idoit_vsphere_values(db, device):
    """Only export a uniquely linked, current VM from an enabled integration."""
    if db is None or device.id is None:
        return {}
    rows = (db.query(VsphereInventoryObject).join(VsphereConnection)
            .filter(VsphereConnection.enabled.is_(True), VsphereInventoryObject.kind == "vm",
                    VsphereInventoryObject.device_id == device.id,
                    VsphereInventoryObject.match_status.in_(("existing", "created"))).all())
    if len(rows) != 1:
        return {}
    row = rows[0]
    metadata = json.loads(row.metadata_json)
    if not isinstance(metadata, dict):
        return {}
    values = {}
    for field in ("instance_uuid", "bios_uuid", "vcenter_uuid", "power_state"):
        values["vsphere_" + field] = metadata.get(field)
    for kind in ("host", "cluster", "datacenter"):
        identifier = metadata.get(kind + "_id")
        item = db.query(VsphereInventoryObject).filter_by(connection_id=row.connection_id, kind=kind,
                                                        external_id=identifier).first() if identifier else None
        if item and item.match_status != "stale":
            values["vsphere_" + kind] = item.name
    connection = db.get(VsphereConnection, row.connection_id)
    if "disks" in visible_fields(connection):
        disks = metadata.get("disks")
        if isinstance(disks, list):
            values["vsphere_disk_uuids"] = ", ".join(sorted({d["uuid"] for d in disks
                if isinstance(d, dict) and _uuid(d.get("uuid"))}))
            values["vsphere_disk_inventory"] = "\n".join(
                f'{d.get("label") or d.get("disk_id")}: {d.get("uuid") or "UUID unavailable"}; {d.get("capacity_bytes") if d.get("capacity_bytes") is not None else "unknown"} B'
                for d in disks if isinstance(d, dict))
    return values


def sysid_annotation(annotation, sysid):
    """Replace only LanLens' managed line; preserve all other text."""
    if not isinstance(sysid, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", sysid):
        raise VsphereError("Invalid i-doit SYSID; writeback refused")
    line = "LanLens i-doit SYS-ID: " + sysid
    pattern = re.compile(r"(?m)^LanLens i-doit SYS-ID: [A-Za-z0-9_.:-]+(?=\r?$)")
    matches = list(pattern.finditer(annotation))
    if len(matches) > 1:
        raise VsphereError("Multiple managed SYSID lines; manual review required")
    if matches:
        return pattern.sub(lambda _: line, annotation)
    return annotation + ("" if not annotation or annotation.endswith("\n") else "\n") + line


async def writeback_idoit_sysid(db, device_id, sysid):
    """Write only to a uniquely linked current VM; failures are nonfatal to CMDB sync."""
    from .crypto import decrypt_secret
    from .vsphere_debug import log_vsphere
    from ..routers.vsphere import _discovery_lock
    async with _discovery_lock:
        connection = db.get(VsphereConnection, 1)
        if (not connection or not connection.enabled or not connection.endpoint or not connection.username
                or not connection.encrypted_secret or not connection.writeback_sysid or connection.sysid_field_key is None):
            return None
        rows = db.query(VsphereInventoryObject).filter_by(
            connection_id=connection.id, kind="vm", device_id=device_id
        ).filter(VsphereInventoryObject.match_status.in_(("existing", "created"))).all()
        if not rows:
            return None
        if len(rows) != 1:
            raise VsphereError("Multiple linked VMware VMs; SYSID writeback refused")
        row = rows[0]
        vm_id, uid = row.external_id, row.instance_uuid
        client = VsphereClient(connection.endpoint, connection.username,
                               decrypt_secret(connection.encrypted_secret), verify_tls=connection.verify_tls)
        field_key = connection.sysid_field_key
        vcenter_uuid = json.loads(row.metadata_json).get("vcenter_uuid")
        db.commit()
        log_vsphere(db, "sysid_writeback", "info", "SYSID custom attribute writeback started", device_id=device_id)
        try:
            result = await asyncio.wait_for(client.write_sysid_custom_field(vm_id, uid, sysid, field_key, vcenter_uuid), timeout=120)
        except Exception as exc:
            log_vsphere(db, "sysid_writeback", "error", "SYSID custom attribute writeback failed",
                        {"error_type": type(exc).__name__}, device_id=device_id)
            raise
        log_vsphere(db, "sysid_writeback", "info", "SYSID custom attribute writeback completed", device_id=device_id)
        return result
