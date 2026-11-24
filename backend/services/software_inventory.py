"""Read-only software inventory derived from the latest successful software observation."""
import hashlib
import json
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import DeepScanFinding, DeepScanRun, Device

def parse_software(raw):
    """Accept agent/WinRM JSON and Linux package-manager text."""
    for _ in range(2):
        if not isinstance(raw, str):
            break
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            break
    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(raw, str):
        items = []
        for line in raw.splitlines()[:2000]:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                items.append({"name": parts[0], "version": parts[1], "architecture": parts[2] if len(parts) > 2 else ""})
            elif match := re.fullmatch(r"(.+?)-(\d[^ ]*-r\d+)", line):
                items.append({"name": match[1], "version": match[2]})
            else:
                items.append({"name": line})
        raw = items
    if not isinstance(raw, list):
        return
    for item in raw[:2000]:
        if not isinstance(item, dict):
            continue
        def field(*keys):
            for key in keys:
                value = item.get(key)
                if isinstance(value, (str, int, float)) and str(value).strip():
                    return str(value).strip()[:255]
            return ""
        name = field("Name", "name", "DisplayName", "display_name")
        if name:
            yield (name, field("Publisher", "publisher"), field("Version", "version", "DisplayVersion"),
                   field("Architecture", "architecture", "arch"))

def list_software_inventory(db: Session, search="", offset=0, limit=25, application_id=None):
    latest = (
        db.query(DeepScanFinding.id.label("finding_id"),
                 func.row_number().over(
                     partition_by=DeepScanFinding.device_id,
                     order_by=(DeepScanFinding.observed_at.desc(), DeepScanFinding.id.desc()),
                 ).label("position"))
        .join(DeepScanRun, DeepScanRun.id == DeepScanFinding.run_id)
        .filter(DeepScanRun.status == "done", DeepScanFinding.key == "installed_software")
        .subquery()
    )
    rows = (db.query(DeepScanFinding, Device.id, Device.label, Device.hostname, Device.ip_address)
            .join(latest, latest.c.finding_id == DeepScanFinding.id)
            .join(Device, Device.id == DeepScanFinding.device_id)
            .filter(latest.c.position == 1, Device.is_archived.is_(False), Device.ignored.is_(False))
            .yield_per(50))
    groups = {}
    devices = set()
    term = search.strip().casefold()
    for finding, device_id, label, hostname, ip_address in rows:
        device_name = label or hostname or ip_address or f"Device #{device_id}"
        devices.add(device_id)
        for name, publisher, version, architecture in parse_software(finding.value_json):
            key = hashlib.sha256(json.dumps([name.casefold(), publisher.casefold()], ensure_ascii=False).encode()).hexdigest()
            group = groups.setdefault(key, {"id": key, "name": name, "publisher": publisher,
                                            "versions": set(), "devices": set(), "installations": {}})
            group["versions"].add(version)
            group["devices"].add(device_id)
            if application_id == key or not application_id:
                identity = (device_id, version.casefold(), architecture.casefold())
                group["installations"][identity] = {
                    "device_id": device_id, "device_name": device_name, "ip_address": ip_address,
                    "version": version, "architecture": architecture,
                    "observed_at": finding.observed_at.isoformat() + "Z" if finding.observed_at else None,
                    "source": finding.source,
                }
    product_count = len(groups)
    if application_id:
        installs = list(groups.get(application_id, {}).get("installations", {}).values())
        if term:
            installs = [i for i in installs if any(term in str(i.get(k) or "").casefold() for k in ("device_name", "ip_address", "version", "architecture"))]
        installs.sort(key=lambda i: (i["device_name"].casefold(), i["device_id"], i["version"], i["architecture"]))
        return {"products": [], "installations": installs[offset:offset+limit], "total": len(installs),
                "device_count": len(devices), "product_count": product_count}
    products = []
    for g in groups.values():
        if term and not any(term in str(v).casefold() for v in (g["name"], g["publisher"], *g["versions"],
                    *(i["device_name"] for i in g["installations"].values()),
                    *(i["ip_address"] or "" for i in g["installations"].values()))):
            continue
        products.append({"id": g["id"], "name": g["name"], "publisher": g["publisher"],
                         "versions": sorted(v for v in g["versions"] if v), "device_count": len(g["devices"]),
                         "installation_count": len(g["installations"])})
    products.sort(key=lambda g: (g["name"].casefold(), g["publisher"].casefold(), g["id"]))
    return {"products": products[offset:offset+limit], "installations": [], "total": len(products),
            "device_count": len(devices), "product_count": product_count}
