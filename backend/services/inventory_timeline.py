"""Compare successful inventory observations within their own data source."""
import json
from datetime import datetime
from sqlalchemy import case, func
from ..models import Credential, DeepScanFinding, DeepScanRun, DeviceChangeEvent


def finding_source():
    return case(
        (DeepScanFinding.source == "lanlens_windows_agent", "windows_agent"),
        (DeepScanFinding.source == "lanlens_linux_agent", "linux_agent"),
        (DeepScanRun.profile == "windows_agent", "windows_agent"),
        (DeepScanRun.profile == "linux_agent", "linux_agent"),
        (DeepScanFinding.source == "winrm/ps", "winrm"),
        (Credential.credential_type == "windows_winrm", "winrm"),
        (Credential.credential_type == "linux_ssh", "ssh"),
        (DeepScanFinding.source.isnot(None), "ssh"),
        else_="unknown",
    )


def _decode(raw):
    try:
        value = json.loads(raw)
        if isinstance(value, str) and value.lstrip().startswith(("[", "{")):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                pass
        return value
    except (ValueError, TypeError):
        return raw


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted((_canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    return value


def _short(value, limit=500):
    return str(value).replace("\r", " ").replace("\n", " ")[:limit]


def _software(value):
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        return None
    result = set()
    for item in value:
        name = item.get("name") or item.get("Name") or item.get("DisplayName")
        version = item.get("version") or item.get("Version") or item.get("DisplayVersion") or ""
        if name:
            result.add(_short(f"{name} {version}".strip(), 200))
    return result


def _summary(kind, key, value):
    if value is None:
        return None
    # Show small, explicitly known inventory fields, not arbitrary raw command
    # output, credentials, licensing data, paths, or full audit payloads.
    safe_scalar = {"vendor", "model", "cpu", "memory", "release", "kernel", "operating_system"}
    if key in safe_scalar and isinstance(value, str):
        return _short(value)
    safe_fields = {"name", "caption", "version", "kernel", "manufacturer", "model",
                   "numberofcores", "numberoflogicalprocessors", "capacity", "speed",
                   "size", "totalphysicalmemory", "buildnumber", "numberofprocessors"}
    if kind in ("os", "hardware") and isinstance(value, (dict, list)):
        rows = value if isinstance(value, list) else [value]
        summaries = [{k: v for k, v in row.items()
                      if str(k).lower() in safe_fields and isinstance(v, (str, int, float, bool))}
                     for row in rows[:10] if isinstance(row, dict)]
        if any(summaries):
            return _short(json.dumps(summaries[0] if isinstance(value, dict) else summaries, ensure_ascii=False))
    if isinstance(value, (list, dict)):
        return f"{len(value)} entries"
    return "Observation available"


def record_inventory_changes(db, run, transport, event_source):
    """One event per changed finding, comparing latest prior successful value.
    Failed or omitted collectors never imply deletion of inventory.
    """
    db.flush()
    current = db.query(DeepScanFinding).filter_by(run_id=run.id).all()
    if not current:
        return []
    source = finding_source()
    ranked = (db.query(DeepScanFinding.id.label("fid"),
                func.row_number().over(partition_by=(DeepScanFinding.finding_type, DeepScanFinding.key),
                    order_by=(DeepScanFinding.observed_at.desc(), DeepScanFinding.id.desc())).label("rank"))
              .join(DeepScanRun, DeepScanRun.id == DeepScanFinding.run_id)
              .outerjoin(Credential, Credential.id == DeepScanRun.credential_id)
              .filter(DeepScanFinding.device_id == run.device_id, DeepScanRun.id != run.id,
                      DeepScanRun.status == "done", source == transport)).subquery()
    prior = {(f.finding_type, f.key): _decode(f.value_json) for f in
             db.query(DeepScanFinding).join(ranked, ranked.c.fid == DeepScanFinding.id)
             .filter(ranked.c.rank == 1).all()}
    changed = []
    for finding in current:
        identity = (finding.finding_type, finding.key)
        before = prior.get(identity)
        after = _decode(finding.value_json)
        if identity in prior and _canonical(before) == _canonical(after):
            continue
        field = f"{finding.finding_type}/{finding.key}"
        changed.append(field)
        old_value = _summary(*identity, before)
        new_value = _summary(*identity, after)
        message = f"Scan #{run.id}: {'updated' if identity in prior else 'added'} {field}"
        if finding.finding_type == "software" and finding.key == "installed_software":
            old_apps, new_apps = _software(before), _software(after)
            if new_apps is not None:
                old_value = f"{len(old_apps)} applications" if old_apps is not None else None
                new_value = f"{len(new_apps)} applications"
                if old_apps is not None:
                    added, removed = sorted(new_apps - old_apps), sorted(old_apps - new_apps)
                    if added or removed:
                        message += "; added/updated: " + _short(", ".join(added), 700)
                        message += "; removed/previous: " + _short(", ".join(removed), 700)
        db.add(DeviceChangeEvent(device_id=run.device_id, event_type="inventory_finding_changed",
            field_name=field[:128], old_value=old_value, new_value=new_value, source=event_source,
            message=message, created_at=datetime.utcnow()))
    return changed
