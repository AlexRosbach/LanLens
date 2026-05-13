"""i-doit one-way sync helpers.

The i-doit Cloud and on-prem products expose the same JSON-RPC API shape for
LanLens' use case: URL + API key login, then object/category calls with the
returned session token. Cloud-specific differences should stay in configuration
(base URL, key, permissions), not in sync logic.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Device, DeepScanFinding, DeviceHostRelationship, IdoitDeviceSync, IdoitSyncLog, PortScan, Setting
from .notification import request_json_via_validated_url

DEFAULT_MAPPING = {
    "name": "Default i-doit mapping",
    "version": 7,
    # Use Client as neutral fallback: it is not Server, but still supports common
    # hardware categories like CPU/model/OS in default i-doit installations.
    "objectType": "C__OBJTYPE__CLIENT",
    "objectTypeByDeviceClass": {
        "Server": "C__OBJTYPE__SERVER",
        "VM": "C__OBJTYPE__VIRTUAL_SERVER",
        "Virtual Server": "C__OBJTYPE__VIRTUAL_SERVER",
        "Virtual Client": "C__OBJTYPE__VIRTUAL_CLIENT",
        "Workstation": "C__OBJTYPE__CLIENT",
        "Apple Workstation": "C__OBJTYPE__CLIENT",
        "Mobile": "C__OBJTYPE__CELL_PHONE_CONTRACT",
        "NAS": "C__OBJTYPE__SAN",
        "Router": "C__OBJTYPE__ROUTER",
        "Switch": "C__OBJTYPE__SWITCH",
        "AP": "C__OBJTYPE__ACCESS_POINT",
        "Firewall": "C__OBJTYPE__CLIENT",
        "Printer": "C__OBJTYPE__PRINTER",
        "VoIP": "C__OBJTYPE__VOIP_PHONE",
        "Camera": "C__OBJTYPE__CLIENT",
        "TV": "C__OBJTYPE__CLIENT",
        "IoT": "C__OBJTYPE__CLIENT",
        "Unknown": "C__OBJTYPE__CLIENT",
    },
    "identity": {
        "fallback": ["mac_address", "hostname", "ip_address"],
    },
    "fields": {
        "hostname": "C__CATG__IP.hostname",
        "ip_address": "C__CATG__IP.ipv4_address",
        "mac_address": "C__CATG__NETWORK_PORT.mac",
        "vendor": "C__CATG__MODEL.manufacturer",
        "asset_tag": "C__CATG__ACCOUNTING.inventory_no",
        "cmdb_id": "C__CATG__ACCOUNTING.inventory_no",
        "purpose": "C__CATG__GLOBAL.purpose",
        "notes": "",
        "os_info": "C__CATG__OPERATING_SYSTEM.assigned_version",
        "cpu": "C__CATG__CPU.title",
        "model": "C__CATG__MODEL.title",
        "serial": "C__CATG__MODEL.serial",
        "memory": "C__CATG__MEMORY.title",
        "disks": "C__CATG__DRIVE.title",
        "open_ports": "",
        "services": "",
        "containers": "",
        "hypervisor": "",
        "licenses": "",
        "relationships": "",
        "lanlens_inventory": "",
        "hardware_summary": ""
    },
}

SETTING_DEFAULTS = {
    "idoit_enabled": "false",
    "idoit_base_url": "",
    "idoit_portal_url": "",
    "idoit_jsonrpc_path": "/src/jsonrpc.php",
    "idoit_api_key": "",
    "idoit_basic_username": "",
    "idoit_basic_password": "",
    "idoit_timeout_seconds": "15",
    "idoit_default_object_type": "C__OBJTYPE__CLIENT",
    "idoit_auto_sync_enabled": "false",
    "idoit_sync_interval_minutes": "60",
    "idoit_offline_retire_days": "7",
    "idoit_sync_status_field": "",
    "idoit_mapping_json": json.dumps(DEFAULT_MAPPING, indent=2),
}


class IdoitConnectionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        endpoint: str = "",
        status_code: Optional[int] = None,
        response_body: str = "",
        jsonrpc_error: Any = None,
    ):
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.endpoint = endpoint
        self.status_code = status_code
        self.response_body = response_body
        self.jsonrpc_error = jsonrpc_error

    def to_detail(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "stage": self.stage,
            "endpoint": self.endpoint,
            "status_code": self.status_code,
            "response_body": self.response_body,
            "jsonrpc_error": self.jsonrpc_error,
        }


@dataclass
class IdoitConfig:
    enabled: bool
    base_url: str
    jsonrpc_path: str
    portal_url: str
    api_key: str
    basic_username: str
    basic_password: str
    timeout_seconds: int
    default_object_type: str
    auto_sync_enabled: bool
    sync_interval_minutes: int
    offline_retire_days: int
    sync_status_field: str
    mapping: dict[str, Any]
    mapping_error: Optional[str] = None
    mapping_raw: str = ""


def build_jsonrpc_endpoint(base_url: str, jsonrpc_path: str = "/src/jsonrpc.php") -> str:
    """Build the i-doit JSON-RPC endpoint for Cloud and on-prem installs.

    Cloud and on-prem both speak JSON-RPC, but on-prem deployments often sit
    behind a reverse proxy or custom sub-path. If base_url already points to
    jsonrpc.php, keep it as-is; otherwise append the configured path.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    path = (jsonrpc_path or "/src/jsonrpc.php").strip()
    if base.endswith("jsonrpc.php"):
        return base
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _get_setting(db: Session, key: str) -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row and row.value is not None else SETTING_DEFAULTS.get(key, "")


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def get_config(db: Session) -> IdoitConfig:
    # Keep both the raw mapping text and parsed representation. The UI must be
    # able to show malformed JSON back to the operator so it can be corrected
    # without direct DB access.
    raw_mapping = _get_setting(db, "idoit_mapping_json") or SETTING_DEFAULTS["idoit_mapping_json"]
    mapping_error = None
    try:
        mapping = json.loads(raw_mapping)
    except Exception as exc:
        mapping = {}
        mapping_error = f"Mapping JSON is invalid: {exc}"
    if _needs_default_mapping_upgrade(mapping):
        # Existing installations may still have an older default mapping stored
        # in the DB. That mapping used invalid/too-generic category fields like
        # C__CATG__GLOBAL.comment, C__CATG__GLOBAL.location_path and
        # C__CATG__MODEL.type, so simply changing SETTING_DEFAULTS would not
        # help those installations.
        mapping = DEFAULT_MAPPING
        raw_mapping = json.dumps(DEFAULT_MAPPING, indent=2)
    try:
        timeout = max(3, min(120, int(_get_setting(db, "idoit_timeout_seconds") or "15")))
    except ValueError:
        timeout = 15
    try:
        sync_interval = max(5, min(1440, int(_get_setting(db, "idoit_sync_interval_minutes") or "60")))
    except ValueError:
        sync_interval = 60
    try:
        offline_retire_days = max(1, min(3650, int(_get_setting(db, "idoit_offline_retire_days") or "7")))
    except ValueError:
        offline_retire_days = 7
    return IdoitConfig(
        enabled=_get_setting(db, "idoit_enabled") == "true",
        base_url=(_get_setting(db, "idoit_base_url") or "").strip().rstrip("/"),
        jsonrpc_path=(_get_setting(db, "idoit_jsonrpc_path") or "/src/jsonrpc.php").strip() or "/src/jsonrpc.php",
        portal_url=(_get_setting(db, "idoit_portal_url") or _get_setting(db, "idoit_base_url") or "").strip().rstrip("/"),
        api_key=_get_setting(db, "idoit_api_key"),
        basic_username=_get_setting(db, "idoit_basic_username"),
        basic_password=_get_setting(db, "idoit_basic_password"),
        timeout_seconds=timeout,
        default_object_type=_normalized_default_object_type(_get_setting(db, "idoit_default_object_type")),
        auto_sync_enabled=_get_setting(db, "idoit_auto_sync_enabled") == "true",
        sync_interval_minutes=sync_interval,
        offline_retire_days=offline_retire_days,
        sync_status_field=_normalized_sync_status_field(_get_setting(db, "idoit_sync_status_field")),
        mapping=mapping,
        mapping_error=mapping_error,
        mapping_raw=raw_mapping,
    )


def _needs_default_mapping_upgrade(mapping: Any) -> bool:
    if not isinstance(mapping, dict):
        return False
    try:
        version = int(mapping.get("version") or 1)
    except (TypeError, ValueError):
        version = 1
    fields = mapping.get("fields") if isinstance(mapping.get("fields"), dict) else {}
    if mapping.get("name") != "Default i-doit mapping":
        return False
    rejected_defaults = {
        "C__CATG__IP.ADDRESS",
        "C__CATG__NETWORK_PORT.MAC",
        "C__CATG__MODEL.TYPE",
        "C__CATG__MODEL.type",
        "C__CATG__GLOBAL.comment",
        "C__CATG__GLOBAL.location_path",
    }
    description_dump_fields = {"purpose", "notes", "os_info"}
    dumps_into_description = any(
        fields.get(field) == "C__CATG__GLOBAL.description"
        for field in description_dump_fields
    ) and version < 4
    global_description_dump = any(value == "C__CATG__GLOBAL.description" for value in fields.values())
    return version < DEFAULT_MAPPING["version"] or any(value in rejected_defaults for value in fields.values()) or dumps_into_description or global_description_dump


def _normalized_default_object_type(value: Optional[str]) -> str:
    field = (value or "").strip()
    if not field or field in {"C__OBJTYPE__SERVER", "C__OBJTYPE__APPLIANCE"}:
        return "C__OBJTYPE__CLIENT"
    return field


def _normalized_sync_status_field(value: Optional[str]) -> str:
    field = (value or "").strip()
    if not field or field in {"C__CATG__GLOBAL.comment", "C__CATG__GLOBAL.description"}:
        return ""
    return field


def update_config(db: Session, payload: dict[str, Any]) -> IdoitConfig:
    for key in SETTING_DEFAULTS:
        if key not in payload:
            continue
        value = payload[key]
        if key == "idoit_mapping_json" and isinstance(value, dict):
            value = json.dumps(value, indent=2)
        elif isinstance(value, bool):
            value = "true" if value else "false"
        elif value is None:
            value = ""
        _set_setting(db, key, str(value))
    db.commit()
    return get_config(db)


def _allowed_device_mapping_fields() -> set[str]:
    # Mapping sources can be regular Device columns or computed read-only values
    # that LanLens derives from deep-scan findings before writing to i-doit.
    return {column.name for column in Device.__table__.columns} | {
        "hardware_summary",
        "cpu",
        "memory",
        "model",
        "serial",
        "disks",
        "open_ports",
        "services",
        "containers",
        "hypervisor",
        "licenses",
        "relationships",
        "lanlens_inventory",
    }


def validate_mapping(
    mapping: dict[str, Any],
    sync_status_field: Optional[str] = None,
    default_object_type: Optional[str] = None,
    mapping_error: Optional[str] = None,
) -> list[str]:
    # This is intentionally local/schema-only validation. It prevents malformed
    # LanLens mapping JSON from crashing preview/sync endpoints. Remote category
    # validation against i-doit belongs to a later live-sync implementation.
    errors: list[str] = []
    if mapping_error:
        errors.append(mapping_error)
    if not isinstance(mapping, dict):
        return errors + ["Mapping must be a JSON object"]
    if not (mapping.get("objectType") or default_object_type):
        errors.append("Mapping requires objectType or idoit_default_object_type")
    fields = mapping.get("fields")
    if not isinstance(fields, dict) or not fields:
        errors.append("Mapping requires at least one field mapping")
    else:
        if invalid_targets := [name for name, target in fields.items() if not isinstance(target, str)]:
            errors.append(f"Mapping field targets must be strings: {', '.join(invalid_targets)}")
        allowed_sources = _allowed_device_mapping_fields()
        if unknown_sources := [name for name in fields if name not in allowed_sources]:
            errors.append(f"Mapping source fields are not supported Device columns: {', '.join(unknown_sources)}")
    identity_raw = mapping.get("identity") or {}
    if not isinstance(identity_raw, dict):
        errors.append("Mapping identity must be a JSON object when provided")
        identity = {}
    else:
        identity = identity_raw
    configured_status = sync_status_field if isinstance(sync_status_field, str) and sync_status_field.strip() else identity.get("syncStatusField")
    if configured_status is not None and not isinstance(configured_status, str):
        errors.append("Mapping identity.syncStatusField must be a string when provided")
    external_id_field = identity.get("externalIdField")
    if external_id_field is not None and (not isinstance(external_id_field, str) or not external_id_field.strip()):
        errors.append("Mapping identity.externalIdField must be a non-empty string when provided")
    return errors


def _mapping_dict(config: IdoitConfig) -> dict[str, Any]:
    return config.mapping if isinstance(config.mapping, dict) else {}


def _mapping_fields(config: IdoitConfig) -> dict[str, Any]:
    fields = _mapping_dict(config).get("fields")
    return fields if isinstance(fields, dict) else {}


def _mapping_identity(config: IdoitConfig) -> dict[str, Any]:
    identity = _mapping_dict(config).get("identity")
    return identity if isinstance(identity, dict) else {}


def _sync_status_field(config: IdoitConfig) -> str:
    if isinstance(config.sync_status_field, str) and config.sync_status_field.strip():
        return _normalized_sync_status_field(config.sync_status_field)
    identity_status = _mapping_identity(config).get("syncStatusField")
    if isinstance(identity_status, str) and identity_status.strip():
        return _normalized_sync_status_field(identity_status)
    return ""


def _json_safe_device_value(device: Device, field_name: str) -> Any:
    if field_name not in {column.name for column in Device.__table__.columns}:
        return None
    value = getattr(device, field_name, None)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _looks_like_server(device: Device) -> bool:
    vendor = (device.vendor or "").lower()
    hostname = (device.hostname or device.label or "").lower()
    server_vendors = ("dell emc", "hewlett packard enterprise", "supermicro", "ibm", "lenovo system x")
    if any(vendor_name in vendor for vendor_name in server_vendors):
        return True
    return bool(re.search(r"(^|[-_.])(srv|server|esx|esxi|hyperv|proxmox)([0-9-_.]|$)", hostname))


def object_type_for_device(device: Device, config: IdoitConfig) -> str:
    mapping = _mapping_dict(config)
    device_class = (device.device_class or "").strip()
    if not device_class or device_class.lower() == "unknown":
        return "C__OBJTYPE__CLIENT"
    by_class = mapping.get("objectTypeByDeviceClass")
    if isinstance(by_class, dict):
        mapped = by_class.get(device_class)
        if isinstance(mapped, str) and mapped.strip():
            if mapped.strip() == "C__OBJTYPE__SERVER" and not _looks_like_server(device):
                return "C__OBJTYPE__CLIENT"
            return mapped.strip()
        for key, value in by_class.items():
            if isinstance(key, str) and key.lower() in device_class.lower() and isinstance(value, str) and value.strip():
                if value.strip() == "C__OBJTYPE__SERVER" and not _looks_like_server(device):
                    return "C__OBJTYPE__CLIENT"
                return value.strip()
    object_type = mapping.get("objectType")
    if isinstance(object_type, str) and object_type.strip():
        return _normalized_default_object_type(object_type)
    return _normalized_default_object_type(config.default_object_type)


def build_object_url(portal_url: str, object_id: Optional[str]) -> Optional[str]:
    if not portal_url or not object_id:
        return None
    base = portal_url.rstrip("/")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}objID={object_id}"


def _object_id_as_int(object_id: Any) -> int:
    try:
        parsed = int(str(object_id).strip())
    except (TypeError, ValueError) as exc:
        raise IdoitConnectionError(
            f"Stored i-doit object id is not an integer: {object_id!r}",
            stage="object_id_validation",
        ) from exc
    if parsed <= 0:
        raise IdoitConnectionError(
            f"Stored i-doit object id must be positive: {object_id!r}",
            stage="object_id_validation",
        )
    return parsed


def _latest_hardware_findings(db: Optional[Session], device: Device) -> dict[str, str]:
    if db is None or not device.id:
        return {}
    rows = (
        db.query(DeepScanFinding.key, DeepScanFinding.value_json)
        .filter(
            DeepScanFinding.device_id == device.id,
            DeepScanFinding.finding_type == "hardware",
            DeepScanFinding.key.in_(["cpu", "processor", "memory", "physical_memory", "model", "computer_system", "vendor", "serial", "bios", "disks", "disk_drives"]),
        )
        .order_by(DeepScanFinding.key, DeepScanFinding.observed_at.desc())
        .all()
    )
    findings: dict[str, str] = {}
    for key, value in rows:
        if key not in findings and value:
            try:
                decoded = json.loads(value)
            except Exception:
                decoded = value
            findings[key] = decoded if isinstance(decoded, str) else json.dumps(decoded, default=str)
    return findings


def _decode_finding_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _compact_text(value: Any, limit: int = 1200) -> str:
    decoded = _decode_finding_value(value)
    if decoded is None:
        return ""
    if isinstance(decoded, str):
        text = decoded.strip()
    else:
        text = json.dumps(decoded, ensure_ascii=False, default=str, sort_keys=True)
    text = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _latest_findings(db: Optional[Session], device: Device) -> dict[str, dict[str, Any]]:
    if db is None or not device.id:
        return {}
    rows = (
        db.query(DeepScanFinding.finding_type, DeepScanFinding.key, DeepScanFinding.value_json, DeepScanFinding.source, DeepScanFinding.observed_at)
        .filter(DeepScanFinding.device_id == device.id)
        .order_by(DeepScanFinding.finding_type, DeepScanFinding.key, DeepScanFinding.observed_at.desc())
        .all()
    )
    findings: dict[str, dict[str, Any]] = {}
    for finding_type, key, value_json, source, observed_at in rows:
        group = findings.setdefault(finding_type, {})
        if key not in group:
            group[key] = {
                "value": _decode_finding_value(value_json),
                "source": source,
                "observed_at": observed_at.isoformat() if isinstance(observed_at, datetime) else None,
            }
    return findings


def _finding_text(findings: dict[str, dict[str, Any]], finding_type: str, key: str, limit: int = 1200) -> Optional[str]:
    entry = findings.get(finding_type, {}).get(key)
    if not isinstance(entry, dict):
        return None
    text = _compact_text(entry.get("value"), limit)
    return text or None


def _first_finding_text(findings: dict[str, dict[str, Any]], candidates: list[tuple[str, str]], limit: int = 1200) -> Optional[str]:
    for finding_type, key in candidates:
        text = _finding_text(findings, finding_type, key, limit)
        if text:
            return text
    return None


def _cpu_title(cpu_raw: Optional[str]) -> Optional[str]:
    if not cpu_raw:
        return None
    decoded = _decode_finding_value(cpu_raw)
    if isinstance(decoded, list) and decoded:
        decoded = decoded[0]
    if isinstance(decoded, dict):
        for key in ("Name", "name", "ModelName", "model_name"):
            value = decoded.get(key)
            if value:
                return str(value).strip()[:255] or None
    for line in str(cpu_raw).splitlines():
        if "model name" in line.lower():
            value = line.split(":", 1)[-1].strip()
            return value or None
    return str(cpu_raw).strip()[:255] or None


def _cpu_details(cpu_raw: Optional[str]) -> dict[str, Any]:
    title = _cpu_title(cpu_raw)
    if not cpu_raw:
        return {}
    raw = str(cpu_raw)
    decoded = _decode_finding_value(cpu_raw)
    if isinstance(decoded, list) and decoded:
        decoded = decoded[0]
    details: dict[str, Any] = {}
    if title:
        details["title"] = title[:255]
        details["type"] = title[:255]
        lowered = title.lower()
        if "intel" in lowered:
            details["manufacturer"] = "Intel"
        elif "amd" in lowered:
            details["manufacturer"] = "AMD"
    if isinstance(decoded, dict):
        cores = decoded.get("NumberOfCores") or decoded.get("cores")
        if isinstance(cores, int) or (isinstance(cores, str) and cores.isdigit()):
            details["cores"] = int(cores)
        mhz = decoded.get("MaxClockSpeed") or decoded.get("max_clock_speed")
        try:
            if mhz:
                details["frequency"] = round(float(str(mhz).replace(",", ".")) / 1000, 2)
                details["frequency_unit"] = 4
        except ValueError:
            pass
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        key_lower = key.lower()
        if key_lower == "cpu(s)" and value.isdigit():
            details.setdefault("cores", int(value))
        elif "core(s) per socket" in key_lower and value.isdigit():
            details["cores"] = int(value)
        elif key_lower in {"cpu mhz", "cpu max mhz"}:
            try:
                mhz = float(value.replace(",", "."))
                if mhz > 0:
                    details.setdefault("frequency", round(mhz / 1000, 2))
                    details.setdefault("frequency_unit", 4)  # GHz in i-doit dialog defaults
            except ValueError:
                pass
    details.setdefault("description", raw[:1000])
    return details


def _hardware_field_text(raw: Any, preferred_keys: tuple[str, ...], limit: int = 500) -> Optional[str]:
    decoded = _decode_finding_value(raw)
    if isinstance(decoded, list) and decoded:
        decoded = decoded[0]
    if isinstance(decoded, dict):
        for key in preferred_keys:
            value = decoded.get(key)
            if value not in (None, ""):
                return str(value).strip()[:limit] or None
    text = _compact_text(decoded, limit)
    return text or None


def _hardware_summary(findings: dict[str, str]) -> Optional[str]:
    parts: list[str] = []
    if cpu := _cpu_title(findings.get("cpu")):
        parts.append(f"CPU: {cpu}")
    if memory := findings.get("memory"):
        parts.append(f"Memory: {str(memory).strip()[:255]}")
    if model := findings.get("model"):
        parts.append(f"Model: {str(model).strip()[:255]}")
    return "\n".join(parts) or None


def _to_list(value: Any) -> list[Any]:
    decoded = _decode_finding_value(value)
    if decoded in (None, ""):
        return []
    return decoded if isinstance(decoded, list) else [decoded]


def _size_to_value_unit(value: Any) -> tuple[Optional[float], Optional[int]]:
    if value in (None, ""):
        return None, None
    text = str(value).strip().replace(",", ".")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGTPE]?i?B?|[KMGTPE])?", text, re.IGNORECASE)
    if not match:
        return None, None
    amount = float(match.group(1))
    unit = (match.group(2) or "").lower().replace("ib", "b")
    # i-doit dialog ids in default installations: 1=MB, 2=GB, 3=TB.
    if unit in {"", "b"}:
        amount = amount / (1024 ** 3)
        return round(amount, 2), 2
    if unit in {"k", "kb"}:
        return round(amount / (1024 ** 2), 2), 2
    if unit in {"m", "mb"}:
        return round(amount, 2), 1
    if unit in {"g", "gb"}:
        return round(amount, 2), 2
    if unit in {"t", "tb"}:
        return round(amount, 2), 3
    return amount, None


def _memory_entries(raw: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in _to_list(raw):
        if isinstance(item, dict):
            capacity, unit = _size_to_value_unit(item.get("Capacity") or item.get("capacity") or item.get("Size") or item.get("size"))
            entry = {
                "quantity": 1,
                "title": str(item.get("PartNumber") or item.get("Name") or item.get("DeviceLocator") or "Memory module")[:255],
                "manufacturer": item.get("Manufacturer") or item.get("manufacturer"),
                "type": item.get("MemoryType") or item.get("SMBIOSMemoryType") or item.get("type"),
                "capacity": capacity,
                "unit": unit,
            }
            entries.append({k: v for k, v in entry.items() if v not in (None, "")})
    if entries:
        return entries[:32]
    text = str(raw or "")
    for line in text.splitlines():
        if line.strip().lower().startswith("mem:"):
            parts = line.split()
            if len(parts) >= 2:
                capacity, unit = _size_to_value_unit(parts[1])
                if capacity:
                    return [{"quantity": 1, "title": "System memory", "capacity": capacity, "unit": unit}]
    capacity, unit = _size_to_value_unit(text)
    return [{"quantity": 1, "title": "System memory", "capacity": capacity, "unit": unit}] if capacity else []


def _drive_entries(raw: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in _to_list(raw):
        if isinstance(item, dict):
            size, unit = _size_to_value_unit(item.get("Size") or item.get("size"))
            title = item.get("Model") or item.get("model") or item.get("Name") or item.get("name") or item.get("DeviceID") or "Disk"
            entry = {
                "title": str(title)[:255],
                "capacity": size,
                "unit": unit,
                "serial": item.get("SerialNumber") or item.get("serial"),
                "drive_type": item.get("MediaType") or item.get("media_type") or item.get("type"),
                "firmware": item.get("FirmwareRevision") or item.get("firmware"),
            }
            entries.append({k: v for k, v in entry.items() if v not in (None, "")})
    if entries:
        return entries[:64]
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("name "):
            continue
        parts = stripped.split(None, 3)
        if len(parts) < 2:
            continue
        name = parts[0]
        size = parts[1]
        dtype = parts[2] if len(parts) > 2 else None
        model = parts[3] if len(parts) > 3 else None
        capacity, unit = _size_to_value_unit(size)
        entry = {
            "title": (model or name)[:255],
            "mount_point": name[:255],
            "capacity": capacity,
            "unit": unit,
            "drive_type": dtype,
        }
        entries.append({k: v for k, v in entry.items() if v not in (None, "")})
    return entries[:64]


def _os_assigned_version(raw: Any) -> Optional[str]:
    decoded = _decode_finding_value(raw)
    if isinstance(decoded, dict):
        for key in ("Caption", "caption", "PRETTY_NAME", "pretty_name", "Name", "name"):
            if decoded.get(key):
                version = decoded.get("Version") or decoded.get("version")
                return f"{decoded[key]} {version}"[:255] if version else str(decoded[key])[:255]
    text = str(raw or "").strip()
    if not text:
        return None
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')[:255]
    return text.splitlines()[0][:255]


def _latest_open_ports(db: Optional[Session], device: Device) -> Optional[str]:
    if db is None or not device.id:
        return None
    scan = (
        db.query(PortScan)
        .filter(PortScan.device_id == device.id)
        .order_by(PortScan.scanned_at.desc())
        .first()
    )
    if not scan:
        return None
    try:
        ports = json.loads(scan.open_ports or "[]")
    except Exception:
        ports = scan.open_ports
    lines = [f"Port scan: {scan.scanned_at.isoformat() if scan.scanned_at else 'unknown'}"]
    if isinstance(ports, list):
        for item in ports[:80]:
            if isinstance(item, dict):
                port = item.get("port") or item.get("number") or item.get("id")
                proto = item.get("protocol") or item.get("proto") or "tcp"
                service = item.get("service") or item.get("name") or item.get("product") or ""
                lines.append(f"- {port}/{proto} {service}".rstrip())
            else:
                lines.append(f"- {item}")
    else:
        lines.append(_compact_text(ports, 2000))
    return "\n".join(lines)[:3000]


def _services_summary(device: Device) -> Optional[str]:
    services = list(device.services or [])
    if not services:
        return None
    lines = ["LanLens services:"]
    for service in sorted(services, key=lambda item: (item.sort_order or 0, item.name or ""))[:80]:
        endpoint = service.url or (f"{service.protocol or 'tcp'}://{device.ip_address}:{service.port}" if service.port and device.ip_address else "")
        parts = [service.name, service.service_type]
        if endpoint:
            parts.append(endpoint)
        if service.version:
            parts.append(f"version={service.version}")
        if service.description:
            parts.append(service.description[:180])
        lines.append("- " + " | ".join(str(part) for part in parts if part))
    return "\n".join(lines)[:4000]


def _relationships_summary(db: Optional[Session], device: Device) -> Optional[str]:
    if db is None or not device.id:
        return None
    rows = (
        db.query(DeviceHostRelationship)
        .filter((DeviceHostRelationship.host_device_id == device.id) | (DeviceHostRelationship.child_device_id == device.id))
        .order_by(DeviceHostRelationship.last_confirmed_at.desc())
        .limit(80)
        .all()
    )
    if not rows:
        return None
    lines = ["LanLens host relationships:"]
    for rel in rows:
        if rel.host_device_id == device.id:
            other = rel.child_device
            direction = "hosts"
        else:
            other = rel.host_device
            direction = "runs on"
        other_label = other.label or other.hostname or other.ip_address or other.mac_address if other else "unknown"
        lines.append(f"- {direction}: {other_label} ({rel.relationship_type}, source={rel.match_source or 'unknown'}, id={rel.vm_identifier or '-'})")
    return "\n".join(lines)[:4000]


def _deep_scan_summary(findings: dict[str, dict[str, Any]]) -> Optional[str]:
    if not findings:
        return None
    lines = ["LanLens deep-scan findings:"]
    for finding_type in sorted(findings.keys()):
        lines.append(f"[{finding_type}]")
        for key, entry in sorted(findings[finding_type].items()):
            value = entry.get("value") if isinstance(entry, dict) else entry
            lines.append(f"- {key}: {_compact_text(value, 700)}")
    return "\n".join(lines)[:10000]


def _lanlens_inventory_summary(device: Device, findings: dict[str, dict[str, Any]], db: Optional[Session]) -> str:
    lines = ["LanLens inventory snapshot"]
    lines.append(f"CMDB ID: {device.cmdb_id or '-'}")
    lines.append(f"Class: {device.device_class or 'Unknown'}")
    lines.append(f"MAC: {device.mac_address or '-'}")
    lines.append(f"IP: {device.ip_address or '-'}")
    lines.append(f"Hostname: {device.hostname or '-'}")
    lines.append(f"Vendor: {device.vendor or '-'}")
    lines.append(f"Online: {'yes' if device.is_online else 'no'}")
    lines.append(f"First seen: {device.first_seen.isoformat() if device.first_seen else '-'}")
    lines.append(f"Last seen: {device.last_seen.isoformat() if device.last_seen else '-'}")
    for title, text in (
        ("Documentation", "\n".join(part for part in [device.purpose, device.description, device.notes] if part)),
        ("Open ports", _latest_open_ports(db, device) or ""),
        ("Services", _services_summary(device) or ""),
        ("Relationships", _relationships_summary(db, device) or ""),
        ("Deep scan", _deep_scan_summary(findings) or ""),
    ):
        if text:
            lines.append(f"\n## {title}\n{text}")
    return "\n".join(lines)[:15000]


def _append_field(fields: dict[str, Any], target: str, value: Any) -> None:
    if value is None or value == "":
        return
    if isinstance(value, list):
        if not value:
            return
        if target in fields and isinstance(fields[target], list):
            fields[target].extend(value)
        else:
            fields[target] = value
        return
    if target in fields and fields[target]:
        fields[target] = f"{fields[target]}\n{value}"
    else:
        fields[target] = value


def _offline_retirement_due(device: Device, config: IdoitConfig) -> bool:
    if device.is_online or not device.last_seen:
        return False
    return device.last_seen <= datetime.utcnow() - timedelta(days=config.offline_retire_days)


def device_payload(device: Device, config: IdoitConfig, db: Optional[Session] = None) -> dict[str, Any]:
    # Build the future i-doit write payload without contacting i-doit. Dry-run
    # and placeholder sync both use this so operators can inspect exactly what
    # would be sent once live upstream writes are enabled.
    label = device.label or device.hostname or device.cmdb_id or device.ip_address or device.mac_address
    hw = _latest_hardware_findings(db, device)
    findings = _latest_findings(db, device)
    model = _hardware_field_text(hw.get("computer_system"), ("Model", "model")) or hw.get("model") or _first_finding_text(findings, [("hardware", "model")], 500)
    serial = _hardware_field_text(hw.get("bios"), ("SerialNumber", "serial", "Serial")) or hw.get("serial") or _first_finding_text(findings, [("hardware", "serial")], 500)
    vendor = device.vendor or _hardware_field_text(hw.get("computer_system"), ("Manufacturer", "manufacturer"), 255) or hw.get("vendor") or _first_finding_text(findings, [("hardware", "vendor")], 255)
    os_info = device.os_info or _first_finding_text(findings, [("os", "release"), ("os", "operating_system"), ("os", "kernel")], 1000)
    cpu_raw = hw.get("cpu") or hw.get("processor") or _first_finding_text(findings, [("hardware", "cpu"), ("hardware", "processor")], 1500)
    memory = hw.get("memory") or hw.get("physical_memory") or _first_finding_text(findings, [("hardware", "memory"), ("hardware", "physical_memory")], 1500)
    disks = hw.get("disks") or _first_finding_text(findings, [("hardware", "disks"), ("hardware", "disk_drives")], 2500)
    containers = "\n".join(
        text for text in [
            _finding_text(findings, "container", "docker_containers", 2500),
            _finding_text(findings, "container", "podman_containers", 2500),
            _finding_text(findings, "container", "k3s_pods", 2500),
            _finding_text(findings, "container", "docker_info", 1200),
        ] if text
    ) or None
    hypervisor = "\n".join(
        text for text in [
            _finding_text(findings, "hypervisor", "kvm_vms", 2500),
            _finding_text(findings, "hypervisor", "proxmox_qemu", 2500),
            _finding_text(findings, "hypervisor", "proxmox_ct", 2500),
            _finding_text(findings, "hypervisor", "proxmox_qemu_configs", 3500),
            _finding_text(findings, "hypervisor", "proxmox_ct_configs", 3500),
            _finding_text(findings, "audit", "hyper_v_vms", 2500),
        ] if text
    ) or None
    licenses = _finding_text(findings, "audit", "licensing", 2500)
    source = {
        "label": label,
        "hostname": device.hostname,
        "ip_address": device.ip_address,
        "mac_address": device.mac_address,
        "device_class": device.device_class,
        "vendor": vendor,
        "cmdb_id": device.cmdb_id,
        "asset_tag": device.asset_tag,
        "location": device.location,
        "responsible": device.responsible,
        "os_info": _os_assigned_version(os_info),
        "cpu": _cpu_title(cpu_raw),
        "memory": _memory_entries(memory),
        "model": model,
        "serial": serial,
        "disks": _drive_entries(disks),
        "open_ports": _latest_open_ports(db, device),
        "services": _services_summary(device),
        "containers": containers,
        "hypervisor": hypervisor,
        "licenses": licenses,
        "relationships": _relationships_summary(db, device),
        "lanlens_inventory": _lanlens_inventory_summary(device, findings, db),
        "hardware_summary": _hardware_summary(hw),
    }
    fields = {}
    for lanlens_field, idoit_field in _mapping_fields(config).items():
        if not isinstance(idoit_field, str) or not idoit_field.strip():
            continue
        if lanlens_field in source:
            value = source[lanlens_field]
        else:
            value = _json_safe_device_value(device, lanlens_field)
        _append_field(fields, idoit_field.strip(), value)
    cpu_details = _cpu_details(cpu_raw)
    if fields.get("C__CATG__CPU.title") and cpu_details:
        for cpu_field in ("manufacturer", "type", "frequency", "frequency_unit", "cores", "description"):
            target = f"C__CATG__CPU.{cpu_field}"
            if target not in fields and cpu_details.get(cpu_field) not in (None, ""):
                fields[target] = cpu_details[cpu_field]
    if _offline_retirement_due(device, config):
        fields["C__CATG__GLOBAL.cmdb_status"] = "C__CMDB_STATUS__OUT_OF_OPERATION"
    external_id_field = _mapping_identity(config).get("externalIdField")
    external_id_value = device.cmdb_id or device.mac_address
    if isinstance(external_id_field, str) and external_id_field.strip() and external_id_value and not fields.get(external_id_field):
        fields[external_id_field] = external_id_value

    sync_status_field = _sync_status_field(config)
    if sync_status_field:
        # Optional, explicit operator-selected reference field. The default is
        # empty so LanLens does not pollute generic i-doit descriptions.
        sync_reference = f"LanLens sync reference: {device.cmdb_id or device.mac_address}"
        _append_field(fields, sync_status_field, sync_reference)
    return {
        "objectType": object_type_for_device(device, config),
        "title": label,
        "identity": {
            "cmdb_id": device.cmdb_id,
            "mac_address": device.mac_address,
            "hostname": device.hostname,
            "ip_address": device.ip_address,
        },
        "fields": fields,
    }


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def get_or_create_state(db: Session, device: Device) -> IdoitDeviceSync:
    # Dry-run/sync can be triggered more than once from the UI. Handle the
    # check-then-insert race by re-reading after an IntegrityError instead of
    # surfacing a 500 to the operator.
    state = db.query(IdoitDeviceSync).filter(IdoitDeviceSync.device_id == device.id).first()
    if not state:
        state = IdoitDeviceSync(device_id=device.id, status="never_synced")
        db.add(state)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            state = db.query(IdoitDeviceSync).filter(IdoitDeviceSync.device_id == device.id).first()
            if not state:
                raise
    return state


MAX_SYNC_LOG_DETAILS_CHARS = 8000
MULTIVALUE_CATEGORY_MATCH_FIELDS = {
    "C__CATG__NETWORK_PORT": ("mac", "title"),
    "C__CATG__IP": ("ipv4_address", "hostname"),
    "C__CATG__CPU": ("title", "type"),
    "C__CATG__MEMORY": ("title", "manufacturer", "capacity"),
    "C__CATG__DRIVE": ("serial", "mount_point", "title"),
}


def _payload_log_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    encoded = json.dumps(payload, default=str, sort_keys=True)
    return {
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "objectType": payload.get("objectType"),
        "title": payload.get("title"),
        "identity": payload.get("identity") if isinstance(payload.get("identity"), dict) else None,
        "field_count": len(fields),
        "field_names": sorted(str(name) for name in fields.keys()),
    }


def _safe_log_details(details: dict[str, Any]) -> str:
    encoded = json.dumps(details or {}, default=str, sort_keys=True)
    if len(encoded) <= MAX_SYNC_LOG_DETAILS_CHARS:
        return encoded

    summary: dict[str, Any] = {
        "truncated": True,
        "original_size": len(encoded),
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }
    if isinstance(details, dict):
        for key in ("errors", "warnings", "upstream_write_performed"):
            if key in details:
                summary[key] = details[key]
        if "payload" in details:
            summary["payload"] = _payload_log_summary(details["payload"])
    return json.dumps(summary, default=str, sort_keys=True)[:MAX_SYNC_LOG_DETAILS_CHARS]


def log_sync(db: Session, device_id: Optional[int], mode: str, result: str, message: str, details: Optional[dict[str, Any]] = None, object_id: Optional[str] = None) -> IdoitSyncLog:
    row = IdoitSyncLog(
        device_id=device_id,
        mode=mode,
        result=result,
        idoit_object_id=object_id,
        message=message,
        details_json=_safe_log_details(details or {}),
    )
    db.add(row)
    return row


def _plain_category_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "title", "name", "const", "id"):
            nested = value.get(key)
            if nested not in (None, ""):
                return nested
        return None
    return value


def _category_entries(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [entry for entry in result if isinstance(entry, dict)]
    if not isinstance(result, dict):
        return []
    for key in ("data", "entries", "result"):
        nested = result.get(key)
        if isinstance(nested, list):
            return [entry for entry in nested if isinstance(entry, dict)]
        if isinstance(nested, dict):
            return [nested]
    if result and all(isinstance(value, dict) for value in result.values()):
        return list(result.values())
    # Some i-doit versions return one single-value category entry directly.
    return [result] if result else []


def _category_entry_id(entry: dict[str, Any]) -> Optional[str]:
    for key in ("id", "entry", "entry_id", "category_id", "data_id"):
        value = entry.get(key)
        value = _plain_category_value(value)
        if value not in (None, ""):
            try:
                return str(_object_id_as_int(value))
            except IdoitConnectionError:
                continue
    return None


def _clean_lanlens_global_description(value: Any) -> Optional[str]:
    text = _plain_category_value(value)
    if not isinstance(text, str):
        return None
    original = text
    for marker in ("LanLens inventory snapshot", "LanLens deep-scan findings:"):
        if marker in text:
            text = text.split(marker, 1)[0]
    lines = [line for line in text.splitlines() if not line.strip().startswith("LanLens sync reference:")]
    cleaned = "\n".join(lines).strip()
    return cleaned if cleaned != original.strip() else None


class IdoitClient:
    def __init__(self, config: IdoitConfig):
        self.config = config
        self.endpoint = build_jsonrpc_endpoint(config.base_url, config.jsonrpc_path)
        self._session_id: Optional[str] = None

    async def call(self, method: str, params: Optional[dict[str, Any]] = None) -> Any:
        headers = {"Content-Type": "application/json"}
        if self.config.basic_username or self.config.basic_password:
            credentials = f"{self.config.basic_username}:{self.config.basic_password}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("ascii")
        if self._session_id:
            headers["X-RPC-Auth-Session"] = self._session_id
        request_params = dict(params or {})
        # i-doit requires the tenant API key not only for idoit.login but also
        # for regular JSON-RPC calls like cmdb.object.create/category.save. Keep
        # the login session header as a performance/auth context, but include
        # the apikey on every call so Test Connection and real sync use the same
        # authentication shape.
        if self.config.api_key and "apikey" not in request_params:
            request_params["apikey"] = self.config.api_key
        body = {"jsonrpc": "2.0", "method": method, "params": request_params, "id": 1}
        try:
            res = await request_json_via_validated_url(
                self.endpoint,
                method="POST",
                payload=body,
                headers=headers,
                timeout_seconds=self.config.timeout_seconds,
                label="i-doit JSON-RPC URL",
            )
        except ValueError as exc:
            raise IdoitConnectionError(str(exc), stage="url_validation", endpoint=self.endpoint) from exc
        except TimeoutError as exc:
            raise IdoitConnectionError("Connection timed out while calling i-doit", stage="network", endpoint=self.endpoint) from exc
        except Exception as exc:
            raise IdoitConnectionError(str(exc) or "Network request to i-doit failed", stage="network", endpoint=self.endpoint) from exc
        if not 200 <= res.status_code < 300:
            body_snippet = (res.text or "")[:500]
            raise IdoitConnectionError(
                f"i-doit JSON-RPC returned HTTP {res.status_code}",
                stage="http_status",
                endpoint=self.endpoint,
                status_code=res.status_code,
                response_body=body_snippet,
            )
        try:
            data = json.loads(res.text)
        except json.JSONDecodeError as exc:
            raise IdoitConnectionError(
                "i-doit did not return valid JSON-RPC JSON",
                stage="json_parse",
                endpoint=self.endpoint,
                status_code=res.status_code,
                response_body=(res.text or "")[:500],
            ) from exc
        if data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise IdoitConnectionError(
                message or "i-doit JSON-RPC returned an error",
                stage="jsonrpc_error",
                endpoint=self.endpoint,
                status_code=res.status_code,
                jsonrpc_error=error,
            )
        return data.get("result")

    async def login(self) -> Any:
        result = await self.call("idoit.login", {"apikey": self.config.api_key})
        if isinstance(result, dict):
            self._session_id = result.get("session-id") or result.get("session_id")
        return result

    async def create_object(self, title: str, object_type: str) -> str:
        result = await self.call("cmdb.object.create", {"type": object_type, "title": title})
        if isinstance(result, dict):
            object_id = result.get("id") or result.get("object_id") or result.get("objID")
            if object_id:
                return str(_object_id_as_int(object_id))
        if isinstance(result, (str, int)):
            return str(_object_id_as_int(result))
        raise IdoitConnectionError("i-doit did not return an object id after create", stage="jsonrpc_error", endpoint=self.endpoint, jsonrpc_error=result)

    async def update_object_title(self, object_id: str, title: str) -> Any:
        return await self.call("cmdb.object.update", {"id": _object_id_as_int(object_id), "title": title})

    async def read_object(self, object_id: str) -> Any:
        return await self.call("cmdb.object.read", {"id": _object_id_as_int(object_id)})

    async def object_type_title(self, object_id: str) -> str:
        result = await self.read_object(object_id)
        if isinstance(result, dict):
            return str(result.get("type_title") or result.get("objecttype_title") or "")
        return ""

    async def read_cmdb_statuses(self) -> Any:
        return await self.call("cmdb.status.read", {"language": "en"})

    async def out_of_operation_status_id(self) -> Optional[int]:
        try:
            result = await self.read_cmdb_statuses()
        except IdoitConnectionError:
            return 10
        for entry in _category_entries(result):
            label = " ".join(
                str(_plain_category_value(entry.get(key)) or "")
                for key in ("title", "name", "const", "constant")
            ).lower()
            if "out of operation" in label or "außer betrieb" in label or "ausser betrieb" in label:
                entry_id = _category_entry_id(entry)
                if entry_id:
                    return int(entry_id)
        return 10

    async def read_category(self, object_id: str, category: str) -> Any:
        object_int = _object_id_as_int(object_id)
        return await self.call("cmdb.category.read", {"object": object_int, "objID": object_int, "category": category})

    async def save_category(self, object_id: str, category: str, data: dict[str, Any], entry_id: Optional[str] = None) -> Any:
        object_int = _object_id_as_int(object_id)
        params: dict[str, Any] = {"object": object_int, "objID": object_int, "category": category, "data": data}
        if entry_id:
            params["entry"] = _object_id_as_int(entry_id)
        return await self.call("cmdb.category.save", params)

    async def save_category_best_effort(self, object_id: str, category: str, data: dict[str, Any]) -> dict[str, Any]:
        """Save a category without letting one invalid field abort the sync.

        i-doit category validation is strict and differs by object type/version.
        Try the full category first; if i-doit rejects it, retry individual
        fields so valid information still lands in the CMDB and the operator can
        see exactly which field was rejected.
        """
        entry_id = await self.find_reusable_category_entry(object_id, category, data)
        try:
            result = await self.save_category(object_id, category, data, entry_id)
            response: dict[str, Any] = {"status": "saved", "result": result}
            if entry_id:
                response["entry_id"] = entry_id
            return response
        except IdoitConnectionError as full_error:
            saved: dict[str, Any] = {}
            failed: dict[str, Any] = {}
            for field, value in data.items():
                try:
                    saved[field] = await self.save_category(object_id, category, {field: value}, entry_id)
                except IdoitConnectionError as field_error:
                    failed[field] = field_error.to_detail()
            if not saved:
                raise full_error
            response = {"status": "partial", "saved_fields": sorted(saved.keys()), "failed_fields": failed}
            if entry_id:
                response["entry_id"] = entry_id
            return response

    async def find_reusable_category_entry(self, object_id: str, category: str, data: dict[str, Any]) -> Optional[str]:
        if category not in MULTIVALUE_CATEGORY_MATCH_FIELDS:
            return None
        try:
            result = await self.read_category(object_id, category)
        except IdoitConnectionError:
            return None
        entries = _category_entries(result)
        if not entries:
            return None
        match_fields = MULTIVALUE_CATEGORY_MATCH_FIELDS[category]
        for field in match_fields:
            expected = _plain_category_value(data.get(field))
            if expected in (None, ""):
                continue
            for entry in entries:
                current = _plain_category_value(entry.get(field))
                if current not in (None, "") and str(current).strip().lower() == str(expected).strip().lower():
                    return _category_entry_id(entry)
        # LanLens manages one discovered network identity per object. If i-doit
        # already has an entry but the MAC/IP changed, update the first one
        # instead of appending a fresh duplicate on every sync.
        return _category_entry_id(entries[0])

    async def cleanup_lanlens_global_description(self, object_id: str) -> Optional[str]:
        try:
            result = await self.read_category(object_id, "C__CATG__GLOBAL")
        except IdoitConnectionError:
            return None
        entries = _category_entries(result)
        if not entries:
            return None
        description = entries[0].get("description")
        cleaned = _clean_lanlens_global_description(description)
        if cleaned is None:
            return None
        await self.save_category(object_id, "C__CATG__GLOBAL", {"description": cleaned})
        return cleaned

    async def object_sysid(self, object_id: str) -> Optional[str]:
        result = await self.read_object(object_id)
        if isinstance(result, dict):
            for key in ("sysid", "sys_id", "SYSID", "SYS-ID"):
                value = result.get(key)
                if value:
                    return str(value)
        return None

    async def test_connection(self) -> dict[str, Any]:
        login_result = await self.login()
        return {
            "ok": True,
            "endpoint": self.endpoint,
            "authenticated": bool(self._session_id),
            "session_received": bool(login_result),
            "message": "i-doit JSON-RPC login succeeded",
        }


def _category_payloads(fields: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    categories: dict[str, Any] = {}
    direct: dict[str, Any] = {}
    for target, value in fields.items():
        if not isinstance(target, str) or value is None:
            continue
        if "." not in target:
            direct[target] = value
            continue
        category, prop = target.split(".", 1)
        if category and prop:
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                existing = categories.setdefault(category, [])
                if isinstance(existing, list):
                    existing.extend(value)
                continue
            categories.setdefault(category, {})[prop] = value
    return categories, direct


async def sync_device_to_idoit(db: Session, device: Device, mode: str = "manual", skip_unchanged: bool = False) -> dict[str, Any]:
    config = get_config(db)
    if not config.enabled:
        raise IdoitConnectionError("i-doit integration is disabled", stage="configuration", endpoint=build_jsonrpc_endpoint(config.base_url, config.jsonrpc_path))
    errors = validate_mapping(config.mapping, config.sync_status_field, config.default_object_type, config.mapping_error)
    payload = device_payload(device, config, db)
    state = get_or_create_state(db, device)
    state.last_mode = mode
    state.last_validation_at = datetime.utcnow()
    digest = payload_hash(payload)
    previous_hash = state.payload_hash
    if skip_unchanged and state.status == "synced" and state.idoit_object_id and previous_hash == digest:
        log_sync(db, device.id, mode, "skipped", "i-doit sync skipped; payload unchanged", {"payload_hash": digest, "upstream_write_performed": False}, state.idoit_object_id)
        db.commit()
        return {"device_id": device.id, "status": state.status, "idoit_object_id": state.idoit_object_id, "payload_hash": digest, "upstream_write_performed": False, "skipped": True}
    state.payload_hash = digest
    if errors:
        state.status = "mapping_error"
        state.last_error = "; ".join(errors)
        log_sync(db, device.id, mode, "failure", "i-doit mapping validation failed", {"payload": payload, "errors": errors, "upstream_write_performed": False}, state.idoit_object_id)
        db.commit()
        return {"device_id": device.id, "status": state.status, "errors": errors, "payload_hash": digest, "upstream_write_performed": False}

    client = IdoitClient(config)
    details: dict[str, Any] = {"payload": payload, "upstream_write_performed": False, "category_results": {}}
    try:
        await client.login()
        object_id = state.idoit_object_id
        action = "update" if object_id else "create"
        if object_id:
            current_type_title = await client.object_type_title(object_id)
            desired_type = payload["objectType"]
            if desired_type != "C__OBJTYPE__SERVER" and "server" in current_type_title.lower():
                old_object_id = object_id
                object_id = await client.create_object(payload["title"], desired_type)
                state.idoit_object_id = object_id
                action = "replace_type_mismatch"
                details["replaced_object_id"] = old_object_id
                details["replaced_object_type_title"] = current_type_title
                details["replacement_reason"] = "Existing i-doit object was typed as Server; i-doit object type changes require a new object. Old object was left untouched."
            else:
                await client.update_object_title(object_id, payload["title"])
        else:
            object_id = await client.create_object(payload["title"], payload["objectType"])
            state.idoit_object_id = object_id

        categories, direct_fields = _category_payloads(payload.get("fields") if isinstance(payload.get("fields"), dict) else {})
        if direct_fields:
            details["direct_fields_skipped"] = direct_fields
        global_category = categories.get("C__CATG__GLOBAL") if isinstance(categories.get("C__CATG__GLOBAL"), dict) else {}
        if global_category.get("description") is None:
            cleaned_description = await client.cleanup_lanlens_global_description(object_id)
            if cleaned_description is not None:
                details["global_description_cleanup"] = "removed previous LanLens inventory/reference dump"
        if global_category.get("cmdb_status") == "C__CMDB_STATUS__OUT_OF_OPERATION":
            global_category["cmdb_status"] = await client.out_of_operation_status_id()
            details["offline_retirement_applied"] = True
        sync_warnings: list[str] = []
        for category, data in categories.items():
            entries = data if isinstance(data, list) else [data]
            category_results: list[dict[str, Any]] = []
            for entry_data in entries:
                if not isinstance(entry_data, dict) or not entry_data:
                    continue
                result = await client.save_category_best_effort(object_id, category, entry_data)
                category_results.append(result)
                if result.get("status") == "partial":
                    failed = result.get("failed_fields") if isinstance(result.get("failed_fields"), dict) else {}
                    sync_warnings.append(f"{category}: partial save; rejected fields: {', '.join(sorted(failed.keys()))}")
            details["category_results"][category] = category_results if isinstance(data, list) else (category_results[0] if category_results else {"status": "skipped_empty"})

        sysid = await client.object_sysid(object_id)
        if sysid:
            state.idoit_sysid = sysid
            details["idoit_sysid"] = sysid

        now = datetime.utcnow()
        state.status = "synced_with_warnings" if sync_warnings else "synced"
        state.last_sync_at = now
        state.last_success_at = now
        state.last_error = None
        details["upstream_write_performed"] = True
        details["action"] = action
        if sync_warnings:
            details["warnings"] = sync_warnings
            state.last_error = "; ".join(sync_warnings)
        log_sync(db, device.id, mode, "success", f"i-doit {action} completed", details, object_id)
        db.commit()
        return {"device_id": device.id, "status": state.status, "action": action, "idoit_object_id": object_id, "idoit_sysid": state.idoit_sysid, "payload_hash": digest, "upstream_write_performed": True, "warnings": sync_warnings}
    except IdoitConnectionError as exc:
        state.status = "error"
        state.last_error = exc.message
        log_sync(db, device.id, mode, "failure", exc.message, {**details, "error": exc.to_detail()}, state.idoit_object_id)
        db.commit()
        raise
    except Exception as exc:
        state.status = "error"
        state.last_error = str(exc)
        log_sync(db, device.id, mode, "failure", str(exc), details, state.idoit_object_id)
        db.commit()
        raise


async def sync_all_registered_devices_to_idoit(db: Session, mode: str = "manual", skip_unchanged: bool = False) -> dict[str, Any]:
    devices = db.query(Device).filter(Device.is_registered == True).all()  # noqa: E712
    summary: dict[str, Any] = {
        "total": len(devices),
        "success": 0,
        "failure": 0,
        "skipped": 0,
        "results": [],
    }
    for device in devices:
        try:
            result = await sync_device_to_idoit(db, device, mode=mode, skip_unchanged=skip_unchanged)
            if result.get("skipped"):
                summary["skipped"] += 1
            elif result.get("upstream_write_performed"):
                summary["success"] += 1
            else:
                summary["failure"] += 1
            summary["results"].append(result)
        except IdoitConnectionError as exc:
            summary["failure"] += 1
            summary["results"].append({"device_id": device.id, "status": "error", "error": exc.to_detail()})
        except Exception as exc:
            summary["failure"] += 1
            summary["results"].append({"device_id": device.id, "status": "error", "error": {"message": str(exc), "stage": "sync"}})
    return summary


def dry_run(db: Session, device: Device) -> dict[str, Any]:
    # Read-only preview: do not mutate sync state here. The UI uses this to show
    # payload, validation errors, and whether the local device changed since the
    # last placeholder validation.
    config = get_config(db)
    errors = validate_mapping(config.mapping, config.sync_status_field, config.default_object_type, config.mapping_error)
    payload = device_payload(device, config, db)
    state = db.query(IdoitDeviceSync).filter(IdoitDeviceSync.device_id == device.id).first()
    digest = payload_hash(payload)
    action = "update" if state and state.idoit_object_id else "unresolved"
    warnings = []
    if not device.cmdb_id:
        warnings.append("Device has no LanLens CMDB ID; matching will fall back to MAC/hostname/IP")
    if not state or not state.idoit_object_id:
        warnings.append("No stored i-doit object id yet; dry-run does not query i-doit, so create/update is unresolved until live matching is enabled")
    pending_change = bool(state and state.payload_hash and state.payload_hash != digest)
    return {"device_id": device.id, "action": action, "payload_hash": digest, "payload": payload, "errors": errors, "warnings": warnings, "idoit_object_id": state.idoit_object_id if state else None, "pending_change": pending_change}


def mark_manual_sync_placeholder(db: Session, device: Device) -> dict[str, Any]:
    """Persist sync state after LanLens-side validation.

    Real i-doit object create/update is intentionally kept behind live API wiring.
    v1.5.0 records validation attempts, payload hashes and audit logs only, so
    API consumers must treat this as "validated pending sync" rather than proof
    that i-doit was updated.
    """
    config = get_config(db)
    payload = device_payload(device, config, db)
    errors = validate_mapping(config.mapping, config.sync_status_field, config.default_object_type, config.mapping_error)
    state = get_or_create_state(db, device)
    state.last_mode = "manual"
    # This endpoint performs local validation only. Keep last_sync_at available
    # for future real upstream writes and record the validation attempt separately.
    state.last_validation_at = datetime.utcnow()
    state.payload_hash = payload_hash(payload)
    if errors:
        state.status = "mapping_error"
        state.last_error = "; ".join(errors)
        result = "failure"
    else:
        state.status = "validated_pending_sync"
        state.last_error = None
        result = "skipped"
    log_sync(db, device.id, "manual", result, "LanLens-side i-doit validation completed; no upstream write performed", {"payload": payload, "errors": errors, "upstream_write_performed": False}, state.idoit_object_id)
    db.commit()
    return {"device_id": device.id, "status": state.status, "errors": errors, "payload_hash": state.payload_hash, "upstream_write_performed": False}
