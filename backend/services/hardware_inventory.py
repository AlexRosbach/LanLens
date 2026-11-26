"""Read-only hardware presentation; preserve every collector's observations."""
from __future__ import annotations

import json

from sqlalchemy import func

from ..models import DeepScanFinding, DeepScanRun


def decode_hardware_value(value):
    # Older WinRM findings contain JSON inside a JSON string.
    for _ in range(2):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            break
    return value


def latest_hardware_by_device(db, device_ids):
    if not device_ids:
        return {}
    ranked = (db.query(DeepScanFinding.device_id, DeepScanFinding.key, DeepScanFinding.value_json,
                       func.row_number().over(
                           partition_by=(DeepScanFinding.device_id, DeepScanFinding.key),
                           order_by=(DeepScanFinding.observed_at.desc(), DeepScanFinding.id.desc()),
                       ).label("rank"))
            .join(DeepScanRun, DeepScanRun.id == DeepScanFinding.run_id)
            .filter(DeepScanFinding.device_id.in_(device_ids),
                    DeepScanFinding.finding_type == "hardware", DeepScanRun.status == "done",
                    DeepScanFinding.key.in_(("cpu", "processor", "memory", "physical_memory", "model", "computer_system")))
            .subquery())
    rows = db.query(ranked.c.device_id, ranked.c.key, ranked.c.value_json).filter(ranked.c.rank == 1)
    inventory = {}
    for device_id, key, value in rows:
        fields = inventory.setdefault(device_id, {})
        if key not in fields:
            fields[key] = decode_hardware_value(value)
    return inventory


def _first_object(value):
    value = decode_hardware_value(value)
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), {})
    return value if isinstance(value, dict) else {}


def _cpu_summary(hardware):
    value = decode_hardware_value(hardware.get("cpu") or hardware.get("processor"))
    data = _first_object(value)
    title = next((str(data[key]) for key in ("Name", "name", "ModelName", "model_name") if data.get(key)), "")
    if not title and isinstance(value, str):
        title = next((line.split(":", 1)[1].strip() for line in value.splitlines()
                      if ":" in line and "model name" in line.lower()), "")
        if not title and "\n" not in value:
            title = value.strip()
    return title.replace("(R)", "").replace("(TM)", "").split(" @ ")[0].strip()[:60]


def _memory_summary(hardware):
    value = decode_hardware_value(hardware.get("memory"))
    if isinstance(value, str):
        for line in value.splitlines():
            if line.strip().lower().startswith("mem:") and len(line.split()) >= 2:
                total = line.split()[1].replace("Gi", " GB").replace("Mi", " MB")
                return f"{total} RAM"
    modules = decode_hardware_value(hardware.get("physical_memory"))
    modules = modules if isinstance(modules, list) else [modules]
    sizes = []
    for module in modules:
        if isinstance(module, dict):
            try:
                size = int(module.get("Capacity", module.get("capacity", 0)))
                if size > 0:
                    sizes.append(size)
            except (TypeError, ValueError):
                pass
    if not sizes:
        system = _first_object(hardware.get("computer_system"))
        try:
            size = int(system.get("TotalPhysicalMemory", 0))
            if size > 0:
                sizes.append(size)
        except (TypeError, ValueError):
            pass
    return f"{sum(sizes) / 1024 ** 3:g} GiB RAM" if sizes else ""


def hardware_summary(guest=None, vmware=None):
    """VMware wins per available field, independently of scan arrival order."""
    guest, vmware = guest or {}, vmware or {}
    preferred, fallback = [], []
    if vmware.get("cpu_count"):
        preferred.append(f"{vmware['cpu_count']} vCPU")
    elif cpu := _cpu_summary(guest):
        fallback.append(cpu)
    if vmware.get("memory_size_mib"):
        preferred.append(f"{vmware['memory_size_mib'] / 1024:g} GiB RAM")
    elif memory := _memory_summary(guest):
        fallback.append(memory)
    if not preferred and not fallback:
        system = _first_object(guest.get("computer_system"))
        model = system.get("Model") or system.get("model") or guest.get("model")
        if isinstance(model, str) and model.strip():
            fallback.append(model.strip()[:60])
    parts = ["VMware: " + " · ".join(preferred)] if preferred else []
    if fallback:
        parts.append(("Deep Scan: " if preferred else "") + " · ".join(fallback))
    return " · ".join(parts) or None
