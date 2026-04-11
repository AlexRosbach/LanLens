from typing import Dict, Any, List
from sqlalchemy.orm import Session
from datetime import datetime
import json

from ..models import DeviceHostRelationship, DeepScanFinding, DeepScanRun, Device


def record_findings_from_run(db: Session, run: DeepScanRun, findings: List[Dict[str, Any]]):
    """Persist structured findings for a given DeepScanRun (planning-only mode).

    findings: list of {key: str, value: Any}
    """
    for f in findings:
        entry = DeepScanFinding(run_id=run.id, key=f.get("key",""), value=json.dumps(f.get("value")) if not isinstance(f.get("value"), str) else f.get("value"))
        db.add(entry)
    db.commit()


def create_device_host_relationship(db: Session, child_device: Device, host_device: Device, match_source: str, confidence: int = 80):
    rel = DeviceHostRelationship(
        child_device_id=child_device.id,
        host_device_id=host_device.id,
        relationship_type="vm_on_host",
        match_source=match_source,
        confidence=confidence,
        observed_at=datetime.utcnow(),
    )
    db.add(rel)
    db.commit()
    return rel


def parse_proxmox_qm_list(output: str) -> List[Dict[str, Any]]:
    """Parse `qm list` output into list of {vmid, name} - best effort in planning mode.
    This is a very tolerant parser and intended for planning-only discovery.
    """
    lines = output.splitlines()
    results = []
    for line in lines:
        parts = line.strip().split()
        if not parts:
            continue
        # qm list often: VMID NAME STATUS
        try:
            vmid = int(parts[0])
            name = parts[1] if len(parts) > 1 else ""
            results.append({"vmid": vmid, "name": name})
        except Exception:
            continue
    return results
