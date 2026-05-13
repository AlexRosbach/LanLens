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

from ..models import Device, DeepScanFinding, IdoitDeviceSync, IdoitSyncLog, Setting
from .notification import request_json_via_validated_url

DEFAULT_MAPPING = {
    "name": "Default i-doit mapping",
    "version": 4,
    # Use a neutral appliance for unknown/unclassified devices. Real servers are
    # still mapped to C__OBJTYPE__SERVER below, but LanLens should not document a
    # random discovered host as a server just because no better signal exists.
    "objectType": "C__OBJTYPE__APPLIANCE",
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
        "Firewall": "C__OBJTYPE__APPLIANCE",
        "Printer": "C__OBJTYPE__PRINTER",
        "VoIP": "C__OBJTYPE__VOIP_PHONE",
        "Camera": "C__OBJTYPE__APPLIANCE",
        "TV": "C__OBJTYPE__APPLIANCE",
        "IoT": "C__OBJTYPE__APPLIANCE",
        "Unknown": "C__OBJTYPE__APPLIANCE",
    },
    "identity": {
        "externalIdField": "C__CATG__GLOBAL.description",
        "syncStatusField": "C__CATG__GLOBAL.description",
        "fallback": ["mac_address", "hostname", "ip_address"],
    },
    "fields": {
        "hostname": "C__CATG__IP.hostname",
        "ip_address": "C__CATG__IP.ipv4_address",
        "mac_address": "C__CATG__NETWORK_PORT.mac",
        "vendor": "C__CATG__MODEL.manufacturer",
        "asset_tag": "C__CATG__ACCOUNTING.inventory_no",
        "cmdb_id": "C__CATG__GLOBAL.description",
        "purpose": "",
        "notes": "",
        "os_info": "C__CATG__OPERATING_SYSTEM.title",
        "cpu": "C__CATG__CPU.title",
        "model": "C__CATG__MODEL.title",
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
    "idoit_default_object_type": "C__OBJTYPE__APPLIANCE",
    "idoit_auto_sync_enabled": "false",
    "idoit_sync_interval_minutes": "60",
    "idoit_offline_retire_days": "7",
    "idoit_sync_status_field": "C__CATG__GLOBAL.description",
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
    description_dump_fields = {"purpose", "notes", "os_info", "hardware_summary"}
    dumps_into_description = any(
        fields.get(field) == "C__CATG__GLOBAL.description"
        for field in description_dump_fields
    )
    return version < DEFAULT_MAPPING["version"] or any(value in rejected_defaults for value in fields.values()) or dumps_into_description


def _normalized_default_object_type(value: Optional[str]) -> str:
    field = (value or "").strip()
    if not field or field == "C__OBJTYPE__SERVER":
        return "C__OBJTYPE__APPLIANCE"
    return field


def _normalized_sync_status_field(value: Optional[str]) -> str:
    field = (value or "").strip()
    if not field or field == "C__CATG__GLOBAL.comment":
        return "C__CATG__GLOBAL.description"
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
    if not isinstance(configured_status, str) or not configured_status.strip():
        errors.append("A writable i-doit sync/reference/status field must be configured")
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
        return identity_status.strip()
    return "C__CATG__GLOBAL.description"


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
        return "C__OBJTYPE__APPLIANCE"
    by_class = mapping.get("objectTypeByDeviceClass")
    if isinstance(by_class, dict):
        mapped = by_class.get(device_class)
        if isinstance(mapped, str) and mapped.strip():
            if mapped.strip() == "C__OBJTYPE__SERVER" and not _looks_like_server(device):
                return "C__OBJTYPE__APPLIANCE"
            return mapped.strip()
        for key, value in by_class.items():
            if isinstance(key, str) and key.lower() in device_class.lower() and isinstance(value, str) and value.strip():
                if value.strip() == "C__OBJTYPE__SERVER" and not _looks_like_server(device):
                    return "C__OBJTYPE__APPLIANCE"
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
            DeepScanFinding.key.in_(["cpu", "memory", "model"]),
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


def _cpu_title(cpu_raw: Optional[str]) -> Optional[str]:
    if not cpu_raw:
        return None
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
    details: dict[str, Any] = {}
    if title:
        details["title"] = title[:255]
        details["type"] = title[:255]
        lowered = title.lower()
        if "intel" in lowered:
            details["manufacturer"] = "Intel"
        elif "amd" in lowered:
            details["manufacturer"] = "AMD"
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


def _hardware_summary(findings: dict[str, str]) -> Optional[str]:
    parts: list[str] = []
    if cpu := _cpu_title(findings.get("cpu")):
        parts.append(f"CPU: {cpu}")
    if memory := findings.get("memory"):
        parts.append(f"Memory: {str(memory).strip()[:255]}")
    if model := findings.get("model"):
        parts.append(f"Model: {str(model).strip()[:255]}")
    return "\n".join(parts) or None


def _append_field(fields: dict[str, Any], target: str, value: Any) -> None:
    if value is None or value == "":
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
    source = {
        "label": label,
        "hostname": device.hostname,
        "ip_address": device.ip_address,
        "mac_address": device.mac_address,
        "device_class": device.device_class,
        "vendor": device.vendor,
        "cmdb_id": device.cmdb_id,
        "asset_tag": device.asset_tag,
        "location": device.location,
        "responsible": device.responsible,
        "os_info": device.os_info,
        "cpu": _cpu_title(hw.get("cpu")),
        "memory": hw.get("memory"),
        "model": hw.get("model"),
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
    cpu_details = _cpu_details(hw.get("cpu"))
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

    # Store a human-readable LanLens reference in a dedicated/comment-like field.
    # If a user maps their CMDB ID to the same field, append instead of replacing
    # so duplicate-prevention identifiers are not lost.
    sync_reference = f"LanLens sync reference: {device.cmdb_id or device.mac_address}"
    sync_status_field = _sync_status_field(config)
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


def _category_payloads(fields: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    categories: dict[str, dict[str, Any]] = {}
    direct: dict[str, Any] = {}
    for target, value in fields.items():
        if not isinstance(target, str) or value is None:
            continue
        if "." not in target:
            direct[target] = value
            continue
        category, prop = target.split(".", 1)
        if category and prop:
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
            await client.update_object_title(object_id, payload["title"])
        else:
            object_id = await client.create_object(payload["title"], payload["objectType"])
            state.idoit_object_id = object_id

        categories, direct_fields = _category_payloads(payload.get("fields") if isinstance(payload.get("fields"), dict) else {})
        if direct_fields:
            details["direct_fields_skipped"] = direct_fields
        if categories.get("C__CATG__GLOBAL", {}).get("cmdb_status") == "C__CMDB_STATUS__OUT_OF_OPERATION":
            categories["C__CATG__GLOBAL"]["cmdb_status"] = await client.out_of_operation_status_id()
            details["offline_retirement_applied"] = True
        sync_warnings: list[str] = []
        for category, data in categories.items():
            result = await client.save_category_best_effort(object_id, category, data)
            details["category_results"][category] = result
            if result.get("status") == "partial":
                failed = result.get("failed_fields") if isinstance(result.get("failed_fields"), dict) else {}
                sync_warnings.append(f"{category}: partial save; rejected fields: {', '.join(sorted(failed.keys()))}")

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
