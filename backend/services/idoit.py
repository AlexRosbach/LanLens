"""i-doit one-way sync helpers.

The i-doit Cloud and on-prem products expose the same JSON-RPC API shape for
LanLens' use case: URL + API key login, then object/category calls with the
returned session token. Cloud-specific differences should stay in configuration
(base URL, key, permissions), not in sync logic.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import csv
import hashlib
import io
import json
import logging
import re
import ssl
import unicodedata
from collections import Counter
from urllib.parse import urlsplit
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Device, DeepScanFinding, DeviceHostRelationship, DeviceIpHistory, IdoitDeviceSync, IdoitSyncLog, PassiveDiscoveryObservation, PortScan, Setting
from .mac_vendor import normalize_mac
from .notification import request_json_via_validated_url
from .passive_discovery import deduplicate_observations
from .snmp import bulk_identities_for_devices, identity_for_device
from .dns_names import device_display_name
from .vsphere import IDOIT_VSPHERE_FIELDS, idoit_vsphere_values, writeback_idoit_sysid
from .software_inventory import parse_software
from ..version import BUILD_COMMIT

logger = logging.getLogger(__name__)
idoit_sync_lock = asyncio.Lock()
CATEGORY_SYNC_REVISION = 2


def _safe_csv_cell(value: Any) -> Any:
    """Escape formula-injection characters for Excel/LibreOffice CSV exports."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    candidate = value.lstrip(" \t\r\n")
    if candidate.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r")):
        return f"'{value}"
    return value


DEFAULT_MAPPING = {
    "name": "Default i-doit mapping",
    "version": 14,
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
        "description": "C__CATG__GLOBAL.description",
        "notes": "C__CATG__GLOBAL.description",
        # Operating systems are real i-doit software objects. LanLens resolves
        # this source separately and links the matching
        # C__OBJTYPE__OPERATING_SYSTEM object through
        # C__CATG__OPERATING_SYSTEM.application instead of copying the OS name
        # into a free-text description.
        "os_info": "",
        "cpu": "C__CATG__CPU.title",
        "model": "C__CATG__MODEL.title",
        "serial": "C__CATG__MODEL.serial",
        "memory": "C__CATG__MEMORY.title",
        "disks": "C__CATG__DRIVE.title",
        "open_ports": "C__CATG__NET_CONNECTIONS_FOLDER",
        "services": "C__CATG__NET_CONNECTIONS_FOLDER",
        "mdns_discovery": "",
        "upnp_discovery": "",
        "passive_discovery": "",
        "tls_certificates": "C__CATG__CERTIFICATE",
        "containers": "C__CATG__APPLICATION",
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
    "idoit_allow_insecure_http": "false",
    "idoit_skip_tls_verification": "false",
    "idoit_portal_url": "",
    "idoit_jsonrpc_path": "/src/jsonrpc.php",
    "idoit_api_key": "",
    "idoit_basic_username": "",
    "idoit_basic_password": "",
    "idoit_timeout_seconds": "15",
    "idoit_default_object_type": "C__OBJTYPE__CLIENT",
    "idoit_auto_sync_enabled": "false",
    "idoit_sync_scope": "all",
    "idoit_create_policy": "match_only",
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
    sync_scope: str
    create_policy: str
    sync_interval_minutes: int
    offline_retire_days: int
    sync_status_field: str
    mapping: dict[str, Any]
    mapping_error: Optional[str] = None
    mapping_raw: str = ""
    allow_insecure_http: bool = False
    skip_tls_verification: bool = False


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


def validate_idoit_https_url(url: str, allow_insecure_http: bool = False) -> None:
    """Prefer verified TLS; plaintext HTTP requires explicit operator opt-in."""
    try:
        parsed = urlsplit(url)
        allowed_schemes = {"https", "http"} if allow_insecure_http else {"https"}
        if parsed.scheme.lower() not in allowed_schemes or not parsed.hostname:
            raise ValueError("i-doit JSON-RPC requires an https:// URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("i-doit URL must not include credentials, query parameters or fragments")
        _ = parsed.port
    except ValueError:
        raise ValueError("Use a valid i-doit HTTPS URL without embedded credentials, query or fragment. HTTP requires explicit insecure HTTP permission.") from None


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
    if upgraded_mapping := _upgrade_default_mapping(mapping):
        # Existing installations may still have an older default mapping stored
        # in the DB. That mapping used invalid/too-generic category fields like
        # C__CATG__GLOBAL.comment, C__CATG__GLOBAL.location_path and
        # C__CATG__MODEL.type, so simply changing SETTING_DEFAULTS would not
        # help those installations.
        mapping = upgraded_mapping
        raw_mapping = json.dumps(upgraded_mapping, indent=2)
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
        allow_insecure_http=_get_setting(db, "idoit_allow_insecure_http") == "true",
        skip_tls_verification=_get_setting(db, "idoit_skip_tls_verification") == "true",
        base_url=(_get_setting(db, "idoit_base_url") or "").strip().rstrip("/"),
        jsonrpc_path=(_get_setting(db, "idoit_jsonrpc_path") or "/src/jsonrpc.php").strip() or "/src/jsonrpc.php",
        portal_url=(_get_setting(db, "idoit_portal_url") or _get_setting(db, "idoit_base_url") or "").strip().rstrip("/"),
        api_key=_get_setting(db, "idoit_api_key"),
        basic_username=_get_setting(db, "idoit_basic_username"),
        basic_password=_get_setting(db, "idoit_basic_password"),
        timeout_seconds=timeout,
        default_object_type=_normalized_default_object_type(_get_setting(db, "idoit_default_object_type")),
        auto_sync_enabled=_get_setting(db, "idoit_auto_sync_enabled") == "true",
        sync_scope="manual" if _get_setting(db, "idoit_sync_scope") == "manual" else "all",
        create_policy="create_missing" if _get_setting(db, "idoit_create_policy") == "create_missing" else "match_only",
        sync_interval_minutes=sync_interval,
        offline_retire_days=offline_retire_days,
        sync_status_field=_normalized_sync_status_field(_get_setting(db, "idoit_sync_status_field")),
        mapping=mapping,
        mapping_error=mapping_error,
        mapping_raw=raw_mapping,
    )


def _upgrade_default_mapping(mapping: Any) -> Optional[dict[str, Any]]:
    if not isinstance(mapping, dict):
        return None
    try:
        version = int(mapping.get("version") or 1)
    except (TypeError, ValueError):
        version = 1
    fields = mapping.get("fields") if isinstance(mapping.get("fields"), dict) else {}
    if mapping.get("name") != "Default i-doit mapping":
        return None
    # Version 13 only needs its old free-text OS mapping retired. It is common
    # for operators to retain the default mapping name while customizing fields
    # or object types, so replacing the complete document would silently lose
    # their configuration.
    if version == 13:
        upgraded = copy.deepcopy(mapping)
        upgraded_fields = upgraded.setdefault("fields", {})
        if not isinstance(upgraded_fields, dict):
            return None
        changed = False
        if upgraded_fields.get("os_info") == "C__CATG__OPERATING_SYSTEM.description":
            upgraded_fields["os_info"] = ""
            changed = True
        if upgraded.get("version") != DEFAULT_MAPPING["version"]:
            upgraded["version"] = DEFAULT_MAPPING["version"]
            changed = True
        return upgraded if changed else None
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
    global_description_dump = version < 10 and any(value == "C__CATG__GLOBAL.description" for value in fields.values())
    if version < 13 or any(value in rejected_defaults for value in fields.values()) or dumps_into_description or global_description_dump:
        return copy.deepcopy(DEFAULT_MAPPING)
    return None


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
        "mdns_discovery",
        "upnp_discovery",
        "passive_discovery",
        "tls_certificates",
        "containers",
        "hypervisor",
        "licenses",
        "relationships",
        "lanlens_inventory",
    } | IDOIT_VSPHERE_FIELDS


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
    vendor = (device.effective_vendor or "").lower()
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


IDOIT_EXPORT_COLUMNS = [
    "Include",
    "Objekt-Typ",
    "Bezeichnung",
    "IP-Adresse",
    "MAC-Adresse",
    "Hostname",
    "Hersteller",
    "Modell",
    "Seriennummer",
    "Betriebssystem",
    "Inventarnummer",
    "CMDB-ID",
    "Standort",
    "Verantwortlich",
    "Notizen",
    "SNMP-Switch",
    "SNMP-Port",
    "mDNS",
    "UPnP/SSDP",
    "Passive Discovery",
    "TLS-Zertifikate",
    "Identity Confidence",
    "LanLens-ID",
]


def build_export_row(
    db: Session,
    device: Device,
    config: IdoitConfig,
    snmp_identity: Optional[dict[str, Any]] = None,
    findings: Optional[dict[str, dict[str, Any]]] = None,
    open_ports_summary: Optional[str] = None,
    passive_discovery: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Build one editable i-doit CSV export row for a LanLens device."""
    findings = findings if findings is not None else _latest_findings(db, device)
    snmp_identity = snmp_identity if snmp_identity is not None else (identity_for_device(db, device) or {})
    model = _first_finding_text(
        findings,
        [("hardware", "model"), ("hardware", "computer_system")],
        limit=255,
    )
    serial = _first_finding_text(
        findings,
        [("hardware", "serial"), ("hardware", "bios")],
        limit=255,
    )
    os_info = device.os_info or _first_finding_text(
        findings,
        [("os", "release"), ("os", "system"), ("hardware", "os")],
        limit=255,
    )
    open_ports_summary = open_ports_summary if open_ports_summary is not None else _latest_open_ports(db, device)
    passive_discovery = passive_discovery if passive_discovery is not None else _passive_discovery_summaries(db, device)
    notes_parts = [part for part in [device.notes, device.description, open_ports_summary] if part]
    return {
        "include": True,
        "device_id": device.id,
        "object_type": object_type_for_device(device, config),
        "title": device_display_name(device),
        "ip_address": device.ip_address or "",
        "mac_address": device.mac_address or "",
        "hostname": device.hostname or "",
        "manufacturer": device.effective_vendor or "",
        "model": model or "",
        "serial": serial or "",
        "os_info": os_info or "",
        "inventory_no": device.asset_tag or "",
        "cmdb_id": device.cmdb_id or "",
        "location": device.location or "",
        "responsible": device.responsible or "",
        "notes": "\n\n".join(notes_parts),
        "snmp_switch": snmp_identity.get("switch_name", ""),
        "snmp_port": str(snmp_identity.get("interface_name") or snmp_identity.get("if_index") or ""),
        "mdns_discovery": passive_discovery.get("mdns_discovery", ""),
        "upnp_discovery": passive_discovery.get("upnp_discovery", ""),
        "passive_discovery": passive_discovery.get("passive_discovery", ""),
        "tls_certificates": _tls_certificates_summary(device) or "",
        "identity_confidence": snmp_identity.get("confidence", "base"),
        "lanlens_id": str(device.id),
    }


def build_export_rows(db: Session, devices: list[Device], config: IdoitConfig) -> list[dict[str, Any]]:
    """Return editable i-doit CSV export rows for the selected devices."""
    identities = bulk_identities_for_devices(db, devices)
    findings_by_device = _bulk_latest_findings(db, devices)
    open_ports_by_device = _bulk_latest_open_ports(db, devices)
    passive_discovery_by_device = _bulk_passive_discovery_summaries(db, devices)
    return [
        build_export_row(
            db,
            device,
            config,
            identities.get(device.id, {}),
            findings_by_device.get(device.id, {}),
            open_ports_by_device.get(device.id),
            passive_discovery_by_device.get(device.id, {}),
        )
        for device in devices
    ]


def rows_to_export_csv(rows: list[dict[str, Any]]) -> str:
    """Serialize reviewed i-doit export rows as Excel-friendly semicolon CSV."""
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(IDOIT_EXPORT_COLUMNS[1:])
    for row in rows:
        if row.get("include") is False:
            continue
        writer.writerow([
            _safe_csv_cell(row.get("object_type", "")),
            _safe_csv_cell(row.get("title", "")),
            _safe_csv_cell(row.get("ip_address", "")),
            _safe_csv_cell(row.get("mac_address", "")),
            _safe_csv_cell(row.get("hostname", "")),
            _safe_csv_cell(row.get("manufacturer", "")),
            _safe_csv_cell(row.get("model", "")),
            _safe_csv_cell(row.get("serial", "")),
            _safe_csv_cell(row.get("os_info", "")),
            _safe_csv_cell(row.get("inventory_no", "")),
            _safe_csv_cell(row.get("cmdb_id", "")),
            _safe_csv_cell(row.get("location", "")),
            _safe_csv_cell(row.get("responsible", "")),
            _safe_csv_cell(row.get("notes", "")),
            _safe_csv_cell(row.get("snmp_switch", "")),
            _safe_csv_cell(row.get("snmp_port", "")),
            _safe_csv_cell(row.get("mdns_discovery", "")),
            _safe_csv_cell(row.get("upnp_discovery", "")),
            _safe_csv_cell(row.get("passive_discovery", "")),
            _safe_csv_cell(row.get("tls_certificates", "")),
            _safe_csv_cell(row.get("identity_confidence", "")),
            _safe_csv_cell(row.get("lanlens_id", "")),
        ])
    return output.getvalue()


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


def _bulk_latest_findings(db: Session, devices: list[Device]) -> dict[int, dict[str, dict[str, Any]]]:
    device_ids = [device.id for device in devices if device.id]
    if not device_ids:
        return {}
    rows = (
        db.query(
            DeepScanFinding.device_id,
            DeepScanFinding.finding_type,
            DeepScanFinding.key,
            DeepScanFinding.value_json,
            DeepScanFinding.source,
            DeepScanFinding.observed_at,
        )
        .filter(DeepScanFinding.device_id.in_(device_ids))
        .order_by(
            DeepScanFinding.device_id,
            DeepScanFinding.finding_type,
            DeepScanFinding.key,
            DeepScanFinding.observed_at.desc(),
        )
        .all()
    )
    result: dict[int, dict[str, dict[str, Any]]] = {}
    for device_id, finding_type, key, value_json, source, observed_at in rows:
        device_findings = result.setdefault(device_id, {})
        group = device_findings.setdefault(finding_type, {})
        if key not in group:
            group[key] = {
                "value": _decode_finding_value(value_json),
                "source": source,
                "observed_at": observed_at.isoformat() if isinstance(observed_at, datetime) else None,
            }
    return result


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


def _first_documented_os_value(findings: dict[str, dict[str, Any]]) -> Any:
    """Return an untruncated OS identity from deep-scan output, never a kernel."""
    for finding_type, key in (("os", "release"), ("os", "operating_system")):
        entry = findings.get(finding_type, {}).get(key)
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if _os_assigned_version(value):
            return value
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
        return None
    if isinstance(decoded, (dict, list)):
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
    description = []
    if title:
        display_title = re.sub(r"\s*\((?:r|tm)\)", "", title, flags=re.IGNORECASE).strip()
        description.append(f"Processor: {display_title}")
    if "cores" in details:
        description.append(f"Cores: {details['cores']}")
    if "frequency" in details:
        description.append(f"Clock speed: {details['frequency']:g} GHz")
    # Keep useful supplementary inventory without serializing JSON into i-doit.
    if isinstance(decoded, dict):
        for keys, label in (
            (("NumberOfLogicalProcessors", "logical_processors"), "Logical processors"),
            (("SocketDesignation", "socket"), "Socket"),
            (("Architecture", "architecture"), "Architecture"),
        ):
            for key in keys:
                value = decoded.get(key)
                if isinstance(value, (str, int, float)) and str(value).strip():
                    description.append(f"{label}: {str(value).strip()[:150]}")
                    break
    if description:
        details["description"] = "\n".join(description)[:1000]
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
    # i-doit's standard memory-unit dialog uses id 3 for GB.  Normalize all
    # source values to GB so hardware inventories do not depend on a host
    # reporting bytes, MiB, GiB, or TB.  (The old 1/2/3 mapping labelled
    # ordinary GB drives as MB in i-doit.)
    if unit in {"", "b"}:
        amount = amount / (1024 ** 3)
    elif unit in {"k", "kb"}:
        amount = amount / (1024 ** 2)
    elif unit in {"m", "mb"}:
        amount = amount / 1024
    elif unit in {"t", "tb"}:
        amount = amount * 1024
    elif unit in {"p", "pb"}:
        amount = amount * (1024 ** 2)
    elif unit not in {"g", "gb"}:
        return amount, None
    return round(amount, 2), 3


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
            locator = str(item.get("DeviceLocator") or item.get("device_locator") or item.get("Locator") or item.get("locator") or "").strip()
            serial = _drive_serial(item.get("SerialNumber") or item.get("serial"))
            if locator or serial:
                marker = f" [LanLens memory: {locator or serial}]"
                entry["title"] = entry["title"][:255-len(marker)] + marker
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


def _drive_serial(value: Any) -> str:
    serial = str(_plain_category_value(value) or "").strip()
    if (not serial or serial.casefold() in {"unknown", "none", "n/a", "na", "not specified",
                                          "to be filled by o.e.m.", "default string", "-", "null"}
            or re.fullmatch(r"[0\s-]+", serial)):
        return ""
    return serial[:255]


def _drive_entries(raw: Any) -> list[dict[str, Any]]:
    """Give each observed disk a distinct identity, including identical VM disks."""
    items = _to_list(raw)
    if len(items) == 1 and isinstance(items[0], str):
        # Old lsblk output: retain the kernel device name as the locator.
        items = []
        for line in str(raw or "").splitlines():
            parts = line.strip().split(None, 3)
            if len(parts) < 3 or parts[0].lower() == "name" or parts[2] != "disk":
                continue
            items.append({"Name": parts[0], "Size": parts[1], "Model": parts[3] if len(parts) > 3 else parts[0],
                          "DeviceID": "/dev/" + parts[0]})
    items = [item for item in items if isinstance(item, dict)][:64]
    serials = Counter(_drive_serial(item.get("SerialNumber") or item.get("serial")).casefold() for item in items)
    occurrences: Counter = Counter()
    entries = []
    for item in items:
        capacity, unit = _size_to_value_unit(item.get("Size") or item.get("size"))
        model = str(item.get("Model") or item.get("model") or item.get("Name") or item.get("name") or "Disk").strip() or "Disk"
        serial = _drive_serial(item.get("SerialNumber") or item.get("serial"))
        if serials[serial.casefold()] > 1:
            # Some virtual disks expose the same placeholder serial.
            serial = ""
        locator = item.get("DeviceID") or item.get("device_id")
        index = item.get("Index", item.get("index"))
        if isinstance(locator, str) and locator.strip():
            locator = locator.strip()
            physical = re.search(r"PHYSICALDRIVE(\d+)$", locator, re.IGNORECASE)
            locator = f"Disk {physical.group(1)}" if physical else locator
        elif index is not None and str(index).isdigit():
            locator = f"Disk {index}"
        else:
            locator = ""
        if locator:
            identity = str(locator)[:100]
        elif serial:
            identity = "Serial " + serial[:100]
        else:
            # Old scans may contain only model and size. Preserve multiplicity
            # without treating model names as unique physical identities.
            key = (model.casefold(), capacity, unit)
            occurrences[key] += 1
            size_label = f"{capacity:g} GB" if capacity is not None and unit == 3 else "size unknown"
            identity = f"Observed {size_label} #{occurrences[key]}"
        suffix = f" [LanLens disk: {identity}]"
        entry = {"title": model[:255-len(suffix)] + suffix,
                 "capacity": capacity, "unit": unit, "serial": serial,
                 "firmware": item.get("FirmwareRevision") or item.get("firmware")}
        entries.append({k: v for k, v in entry.items() if v not in (None, "")})
    # A repeated locator in one snapshot is unsafe to match. Give distinct
    # observations deterministic labels rather than overwriting either one.
    totals = Counter(entry["title"].casefold() for entry in entries)
    seen: Counter = Counter()
    for entry in entries:
        title = entry["title"]
        if totals[title.casefold()] > 1:
            seen[title.casefold()] += 1
            suffix = f" [observation {seen[title.casefold()]}]"
            entry["title"] = title[:255-len(suffix)] + suffix
    return entries


def _drive_match_id(entries: list[dict[str, Any]], data: dict[str, Any]) -> Optional[str]:
    """Never reuse a disk entry merely because its model/title matches."""
    serial = _drive_serial(data.get("serial")).casefold()
    title = _normalized_match_text(data.get("title"))
    mount = _normalized_match_text(data.get("mount_point"))
    explicit_title = " [lanlens disk: " in title
    serial_matches, location_matches = set(), set()
    for entry in entries:
        status = str(_plain_category_value(entry.get("status")) or "")
        if status and status not in ("2", "C__RECORD_STATUS__NORMAL"):
            continue
        entry_serial = _drive_serial(entry.get("serial")).casefold()
        if serial and entry_serial and serial != entry_serial:
            continue
        oid = _category_entry_id(entry)
        current_title = _normalized_match_text(entry.get("title"))
        current_mount = _normalized_match_text(entry.get("mount_point"))
        same_serial = bool(serial and entry_serial == serial)
        same_location = bool((explicit_title and title == current_title)
                             or (mount and mount == current_mount))
        if (same_serial or same_location) and not oid:
            raise IdoitConnectionError("Matching drive entry has no usable category ID", stage="category_match")
        if same_serial:
            serial_matches.add(oid)
        if same_location:
            location_matches.add(oid)
    if len(location_matches) > 1 or (len(serial_matches) > 1 and not location_matches):
        raise IdoitConnectionError("Multiple matching drive entries; refusing ambiguous update", stage="category_match")
    if location_matches and serial_matches and not (location_matches & serial_matches):
        raise IdoitConnectionError("Drive serial and locator point to different entries", stage="category_match")
    if location_matches:
        return next(iter(location_matches))
    if len(serial_matches) == 1:
        return next(iter(serial_matches))
    return None


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


def _operating_system_assignment(raw: Any, kernel_version: Optional[str] = None) -> Optional[dict[str, str]]:
    """Return normalized i-doit OS-object assignment metadata.

    i-doit's global Operating System category requires an object-browser link;
    the detected operating-system name itself is not a description value.
    Keep the complete detected label as the OS object title and split out a
    useful version for the installation relationship when possible.
    """
    title = _os_assigned_version(raw)
    if not title:
        return None
    title = re.sub(r"\s+", " ", title).strip()[:255]
    version_candidates = re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+){0,3}(?:[-_][A-Za-z0-9.]+)?", title)
    assigned_version = max(
        version_candidates,
        key=lambda value: (value.count("."), len(value)),
        default="",
    )[:255]
    result = {"title": title}
    if assigned_version:
        result["assigned_version"] = assigned_version
    if kernel_version and kernel_version.strip():
        result["description"] = f"Kernel: {kernel_version.strip()[:240]}"
    return result


def _software_assignments(findings: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Extract a bounded, de-duplicated software inventory for i-doit links.

    The product title is resolved against an Application object, while the
    detected version stays on the host's Application assignment.  This mirrors
    the OS relationship and prevents a separate object for every version.
    """
    candidates = [group.get("installed_software") for group in findings.values() if isinstance(group, dict)]
    entry = max((item for item in candidates if isinstance(item, dict)), key=lambda item: item.get("observed_at") or "", default=None)
    raw = entry.get("value") if isinstance(entry, dict) else None
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for title, publisher, version, _architecture in parse_software(raw):
        identity = (title.casefold(), version.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        assignment = {"title": title}
        if version:
            assignment["assigned_version"] = version
        if publisher:
            assignment["description"] = f"Publisher: {publisher}"
        result.append(assignment)
        if len(result) >= 500:
            break
    return result


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
    return _format_open_ports(scan)


def _bulk_latest_open_ports(db: Session, devices: list[Device]) -> dict[int, str]:
    device_ids = [device.id for device in devices if device.id]
    if not device_ids:
        return {}
    scans = (
        db.query(PortScan)
        .filter(PortScan.device_id.in_(device_ids))
        .order_by(PortScan.device_id, PortScan.scanned_at.desc())
        .all()
    )
    latest: dict[int, PortScan] = {}
    for scan in scans:
        if scan.device_id not in latest:
            latest[scan.device_id] = scan
    return {
        device_id: summary
        for device_id, scan in latest.items()
        if (summary := _format_open_ports(scan))
    }


def _format_open_ports(scan: PortScan) -> str:
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


def _open_port_entries(db: Optional[Session], device: Device) -> list[dict[str, Any]]:
    if db is None or not device.id:
        return []
    scan = (
        db.query(PortScan)
        .filter(PortScan.device_id == device.id)
        .order_by(PortScan.scanned_at.desc())
        .first()
    )
    if not scan:
        return []
    try:
        ports = json.loads(scan.open_ports or "[]")
    except Exception:
        ports = []
    if not isinstance(ports, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in ports[:80]:
        if not isinstance(item, dict):
            continue
        port = item.get("port") or item.get("number") or item.get("id")
        proto = item.get("protocol") or item.get("proto") or "tcp"
        service = item.get("service") or item.get("name") or item.get("product") or ""
        description_parts = ["Discovered by LanLens port scan"]
        if scan.scanned_at:
            description_parts.append(f"Observed: {scan.scanned_at.isoformat()}")
        entry = {
            "protocol": str(proto).upper() if proto else None,
            "protocol_layer_5": str(service).upper()[:255] if service else None,
            "port_from": int(port) if str(port).isdigit() else None,
            "port_to": int(port) if str(port).isdigit() else None,
            "description": "\n".join(description_parts),
        }
        entries.append({k: v for k, v in entry.items() if v not in (None, "")})
    return entries


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
        if service.tls_status:
            parts.append(f"tls={service.tls_status}")
        if service.tls_expires_at:
            parts.append(f"tls_expires={service.tls_expires_at.isoformat()}")
        if service.description:
            parts.append(service.description[:180])
        lines.append("- " + " | ".join(str(part) for part in parts if part))
    return "\n".join(lines)[:4000]


def _service_entries(device: Device) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for service in sorted(list(device.services or []), key=lambda item: (item.sort_order or 0, item.name or ""))[:80]:
        endpoint = service.url or (f"{service.protocol or 'tcp'}://{device.ip_address}:{service.port}" if service.port and device.ip_address else "")
        description_parts = [
            value for value in (
                f"Service: {service.name}" if service.name else None,
                f"Type: {service.service_type}" if service.service_type else None,
                f"Endpoint: {endpoint}" if endpoint else None,
                f"Version: {service.version}" if service.version else None,
                f"TLS status: {service.tls_status}" if service.tls_status else None,
                service.description,
                "Discovered by LanLens",
            ) if value
        ]
        raw_protocol = str(service.protocol or "").strip()
        transport_protocol = raw_protocol.upper() if raw_protocol.lower() in {"tcp", "udp"} else "TCP"
        application_protocol = (
            raw_protocol if raw_protocol.lower() not in {"", "tcp", "udp"}
            else service.service_type or service.name
        )
        entry = {
            "protocol": transport_protocol,
            "protocol_layer_5": str(application_protocol).upper()[:255] if application_protocol else None,
            "port_from": service.port,
            "port_to": service.port,
            "description": "\n".join(description_parts)[:2000],
        }
        entries.append({k: v for k, v in entry.items() if v not in (None, "")})
    return entries


def _tls_certificates_summary(device: Device) -> Optional[str]:
    services = [
        service for service in list(device.services or [])
        if service.tls_status or service.tls_expires_at or service.tls_issuer or service.tls_subject or service.tls_sans or service.tls_error
    ]
    if not services:
        return None
    lines = ["LanLens TLS certificates:"]
    for service in sorted(services, key=lambda item: (item.sort_order or 0, item.name or ""))[:80]:
        endpoint = service.url or (f"{service.protocol or 'tcp'}://{device.ip_address}:{service.port}" if service.port and device.ip_address else "")
        lines.append(f"- {service.name or 'Service'}{f' ({endpoint})' if endpoint else ''}")
        if service.tls_status:
            lines.append(f"  status: {service.tls_status}")
        if service.tls_expires_at:
            lines.append(f"  expires: {service.tls_expires_at.isoformat()}")
        if service.tls_issuer:
            lines.append(f"  issuer: {service.tls_issuer}")
        if service.tls_subject:
            lines.append(f"  subject: {service.tls_subject}")
        if service.tls_sans:
            lines.append(f"  SAN: {service.tls_sans}")
        if service.tls_self_signed is not None:
            lines.append(f"  self_signed: {'yes' if service.tls_self_signed else 'no'}")
        if service.tls_error:
            lines.append(f"  error: {service.tls_error}")
    return "\n".join(lines)[:6000]


def _tls_certificate_entries(device: Device) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    services = [
        service for service in list(device.services or [])
        if service.tls_status or service.tls_expires_at or service.tls_issuer or service.tls_subject or service.tls_sans or service.tls_error
    ]
    for service in sorted(services, key=lambda item: (item.sort_order or 0, item.name or ""))[:80]:
        endpoint = service.url or (f"{service.protocol or 'tcp'}://{device.ip_address}:{service.port}" if service.port and device.ip_address else "")
        subject = service.tls_subject or ""
        common_name = subject
        for component in subject.split(","):
            key, separator, value = component.strip().partition("=")
            if separator and key.strip().upper() == "CN" and value.strip():
                common_name = value.strip()
                break
        if not common_name:
            common_name = service.name or endpoint or "TLS certificate"
        description_parts = [
            value for value in (
                f"Subject: {service.tls_subject}" if service.tls_subject else None,
                f"Issuer: {service.tls_issuer}" if service.tls_issuer else None,
                f"SANs: {service.tls_sans}" if service.tls_sans else None,
                f"Endpoint: {endpoint}" if endpoint else None,
                f"Status: {service.tls_status}" if service.tls_status else None,
                f"Self-signed: {'yes' if service.tls_self_signed else 'no'}"
                if service.tls_self_signed is not None else None,
                f"Error: {service.tls_error}" if service.tls_error else None,
                "Discovered by LanLens",
            ) if value
        ]
        entry = {
            "type": "SSL/TLS",
            "common_name": common_name[:1000],
            "expire_date": service.tls_expires_at.date().isoformat() if service.tls_expires_at else None,
            "description": "\n".join(description_parts)[:4000],
        }
        entries.append({k: v for k, v in entry.items() if v not in (None, "")})
    return entries


def _container_entries(container_summary: Optional[str]) -> list[dict[str, Any]]:
    if not container_summary:
        return []
    entries: list[dict[str, Any]] = []
    for line in str(container_summary).splitlines()[:80]:
        cleaned = line.strip().lstrip("- ").strip()
        if cleaned:
            entries.append({"title": cleaned[:255], "source": "LanLens deep scan"})
    return entries or [{"title": "LanLens discovered container/software", "source": "LanLens deep scan"}]


def _passive_discovery_filters(db: Optional[Session], device: Device) -> list[Any]:
    filters: list[Any] = []
    ip_addresses = [device.ip_address] if device.ip_address else []
    if db is not None and device.id:
        history_ips = (
            db.query(DeviceIpHistory.ip_address)
            .filter(DeviceIpHistory.device_id == device.id)
            .all()
        )
        ip_addresses.extend(ip for (ip,) in history_ips if ip)
    ip_addresses = sorted(set(ip_addresses))
    if ip_addresses:
        filters.append(PassiveDiscoveryObservation.source_ip.in_(ip_addresses))
    if device.mac_address and not str(device.mac_address).startswith("ip:"):
        mac = normalize_mac(device.mac_address)
        if mac:
            filters.append(PassiveDiscoveryObservation.source_mac == mac)
    return filters


def _passive_discovery_rows(
    db: Optional[Session],
    device: Device,
    protocols: Optional[set[str]] = None,
    limit: int = 20,
) -> list[PassiveDiscoveryObservation]:
    if db is None or not device.id:
        return []
    filters = _passive_discovery_filters(db, device)
    if not filters:
        return []
    query = db.query(PassiveDiscoveryObservation).filter(or_(*filters))
    if protocols:
        query = query.filter(PassiveDiscoveryObservation.protocol.in_(sorted(protocols)))
    rows = (
        query.order_by(PassiveDiscoveryObservation.observed_at.desc())
        .limit(max(1, min(limit * 5, 500)))
        .all()
    )
    return deduplicate_observations(rows, max(1, min(limit, 100)))


def _passive_row_line(row: PassiveDiscoveryObservation) -> str:
    try:
        metadata = json.loads(row.metadata_json or "{}")
    except Exception:
        metadata = {}
    observed = row.observed_at.isoformat() if row.observed_at else "unknown"
    parts = [
        observed,
        row.protocol.upper(),
        row.summary or row.service_type or row.service_name or "observation",
    ]
    if row.service_name and row.service_name not in parts[-1]:
        parts.append(row.service_name)
    if row.service_type and row.service_type not in " ".join(parts):
        parts.append(row.service_type)
    if row.destination_ip:
        parts.append(f"dst={row.destination_ip}")
    for key in ("query", "answer_count", "location", "server", "user_agent"):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if value not in (None, ""):
            parts.append(f"{key}={str(value)[:160]}")
    return " | ".join(str(part) for part in parts if part)


def _format_passive_discovery_summary(title: str, rows: list[PassiveDiscoveryObservation]) -> Optional[str]:
    if not rows:
        return None
    lines = [title]
    for row in rows:
        lines.append(f"- {_passive_row_line(row)}")
    return "\n".join(lines)[:5000]


def _passive_discovery_summaries(db: Optional[Session], device: Device) -> dict[str, str]:
    mdns_rows = _passive_discovery_rows(db, device, {"mdns"}, 20)
    upnp_rows = _passive_discovery_rows(db, device, {"ssdp"}, 20)
    all_rows = _passive_discovery_rows(db, device, {"mdns", "ssdp", "multicast", "ospf", "vrrp", "hsrp"}, 30)
    return {
        "mdns_discovery": _format_passive_discovery_summary("LanLens mDNS observations:", mdns_rows) or "",
        "upnp_discovery": _format_passive_discovery_summary("LanLens UPnP/SSDP observations:", upnp_rows) or "",
        "passive_discovery": _format_passive_discovery_summary("LanLens passive discovery observations:", all_rows) or "",
    }


def _bulk_passive_discovery_summaries(db: Session, devices: list[Device]) -> dict[int, dict[str, str]]:
    # Kept deliberately simple and bounded; i-doit export previews are limited
    # and this mirrors the per-device matching semantics used by the UI.
    return {
        device.id: summaries
        for device in devices
        if device.id and (summaries := _passive_discovery_summaries(db, device))
    }


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
    passive = _passive_discovery_summaries(db, device)
    lines.append(f"CMDB ID: {device.cmdb_id or '-'}")
    lines.append(f"Class: {device.device_class or 'Unknown'}")
    lines.append(f"MAC: {device.mac_address or '-'}")
    lines.append(f"IP: {device.ip_address or '-'}")
    lines.append(f"Hostname: {device.hostname or '-'}")
    lines.append(f"Vendor: {device.effective_vendor or '-'}")
    lines.append(f"Online: {'yes' if device.is_online else 'no'}")
    lines.append(f"First seen: {device.first_seen.isoformat() if device.first_seen else '-'}")
    lines.append(f"Last seen: {device.last_seen.isoformat() if device.last_seen else '-'}")
    for title, text in (
        ("Documentation", "\n".join(part for part in [device.purpose, device.description, device.notes] if part)),
        ("Open ports", _latest_open_ports(db, device) or ""),
        ("Services", _services_summary(device) or ""),
        ("mDNS discovery", passive.get("mdns_discovery", "")),
        ("UPnP/SSDP discovery", passive.get("upnp_discovery", "")),
        ("TLS certificates", _tls_certificates_summary(device) or ""),
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
    label = device_display_name(device)
    hw = _latest_hardware_findings(db, device)
    findings = _latest_findings(db, device)
    model = _hardware_field_text(hw.get("computer_system"), ("Model", "model")) or hw.get("model") or _first_finding_text(findings, [("hardware", "model")], 500)
    serial = _hardware_field_text(hw.get("bios"), ("SerialNumber", "serial", "Serial")) or hw.get("serial") or _first_finding_text(findings, [("hardware", "serial")], 500)
    vendor = device.effective_vendor or _hardware_field_text(hw.get("computer_system"), ("Manufacturer", "manufacturer"), 255) or hw.get("vendor") or _first_finding_text(findings, [("hardware", "vendor")], 255)
    # An OS assignment must use a documented operating-system value. A kernel
    # release is supplementary metadata, not an OS object title, and JSON must
    # remain intact until _os_assigned_version extracts its display fields.
    os_info = device.os_info or _first_documented_os_value(findings)
    cpu_raw = hw.get("cpu") or hw.get("processor") or _first_finding_text(findings, [("hardware", "cpu"), ("hardware", "processor")], 1500)
    memory = hw.get("memory") or hw.get("physical_memory") or _first_finding_text(findings, [("hardware", "memory"), ("hardware", "physical_memory")], 1500)
    # Preserve the complete raw list; compact display text can truncate JSON.
    disk_findings = findings.get("hardware", {})
    disk_candidates = [disk_findings[key] for key in ("disks", "disk_drives")
                       if isinstance(disk_findings.get(key), dict)]
    latest_disks = max(disk_candidates, key=lambda item: item.get("observed_at") or "", default={})
    disks = latest_disks.get("value") if disk_candidates else (hw.get("disk_drives") or hw.get("disks"))
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
    passive_discovery = _passive_discovery_summaries(db, device)
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
        "purpose": device.purpose,
        "description": device.description,
        "notes": device.notes,
        "password_location": device.password_location,
        "os_info": _os_assigned_version(os_info),
        "cpu": _cpu_title(cpu_raw),
        "memory": _memory_entries(memory),
        "model": model,
        "serial": serial,
        "disks": _drive_entries(disks),
        "open_ports": _open_port_entries(db, device),
        "services": _service_entries(device),
        "mdns_discovery": passive_discovery.get("mdns_discovery"),
        "upnp_discovery": passive_discovery.get("upnp_discovery"),
        "passive_discovery": passive_discovery.get("passive_discovery"),
        "tls_certificates": _tls_certificate_entries(device),
        "containers": _container_entries(containers),
        "hypervisor": hypervisor,
        "licenses": licenses,
        "relationships": _relationships_summary(db, device),
        "lanlens_inventory": _lanlens_inventory_summary(device, findings, db),
        "hardware_summary": _hardware_summary(hw),
    }
    if IDOIT_VSPHERE_FIELDS.intersection(_mapping_fields(config)):
        source.update(idoit_vsphere_values(db, device))
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

    idoit_sysid = None
    if db is not None:
        state = db.query(IdoitDeviceSync).filter(IdoitDeviceSync.device_id == device.id).first()
        if state and state.idoit_sysid:
            idoit_sysid = state.idoit_sysid.strip()

    sync_status_field = _sync_status_field(config)
    if sync_status_field:
        # Optional, explicit operator-selected reference field. The default is
        # empty so LanLens does not pollute generic i-doit descriptions.
        sync_reference = f"LanLens sync reference: {device.cmdb_id or device.mac_address}"
        _append_field(fields, sync_status_field, sync_reference)
    payload = {
        "objectType": object_type_for_device(device, config),
        "title": label,
        "identity": {
            "cmdb_id": device.cmdb_id,
            "mac_address": device.mac_address,
            "hostname": device.hostname,
            "ip_address": device.ip_address,
            "idoit_sysid": idoit_sysid,
        },
        "fields": fields,
    }
    if operating_system := _operating_system_assignment(os_info, device.kernel_version):
        payload["operatingSystem"] = operating_system
    if applications := _software_assignments(findings):
        payload["applications"] = applications
    return payload


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"sync_revision": CATEGORY_SYNC_REVISION, "payload": payload}, sort_keys=True, default=str).encode()).hexdigest()


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
MAX_SYSID_SCAN_OBJECTS = 5000
MULTIVALUE_CATEGORY_MATCH_FIELDS = {
    "C__CATG__NETWORK_PORT": ("mac", "title"),
    "C__CATG__IP": ("ipv4_address", "hostname"),
    "C__CATG__CPU": ("title", "type"),
    "C__CATG__MEMORY": ("title", "manufacturer", "capacity"),
    "C__CATG__DRIVE": ("serial", "mount_point", "title"),
    "C__CATG__CERTIFICATE": ("common_name",),
    "C__CATG__OPERATING_SYSTEM": ("application",),
    "C__CATG__APPLICATION": ("application",),
}
COMPOSITE_MULTIVALUE_CATEGORY_MATCH_FIELDS = {
    "C__CATG__NET_CONNECTIONS_FOLDER": ("port_from", "port_to", "protocol"),
}
FIRST_ENTRY_REUSE_CATEGORIES = {
    "C__CATG__NETWORK_PORT",
    "C__CATG__IP",
}

# These fields are derived automatically from deep-scan hardware data and vary
# heavily between i-doit versions/object types. They are useful when accepted,
# but should not turn an otherwise successful sync into operator-visible noise.
# Explicitly mapped/default identity fields still report warnings when rejected.
OPTIONAL_IDOIT_CATEGORY_FIELDS = {
    "C__CATG__MODEL": {"manufacturer"},
    "C__CATG__CPU": {"manufacturer", "type", "frequency", "frequency_unit", "cores"},
    "C__CATG__MEMORY": {"quantity", "manufacturer", "type", "capacity", "unit"},
    "C__CATG__DRIVE": {"serial", "mount_point", "capacity", "unit", "firmware", "drive_type"},
    "C__CATG__NET_CONNECTIONS_FOLDER": {"protocol", "protocol_layer_5", "port_from", "port_to", "description"},
    "C__CATG__CERTIFICATE": {"type", "common_name", "expire_date", "description"},
    "C__CATG__APPLICATION": {"source"},
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
        for key in ("identity_match", "match_debug", "match_required", "create_policy"):
            if key in details:
                summary[key] = details[key]
        if "application_lookup" in details:
            summary["application_lookup"] = details["application_lookup"]
        if "application_resolution_counts" in details:
            summary["application_resolution_counts"] = details["application_resolution_counts"]
        for key in ("application_save_counts", "drive_save_counts", "category_save_counts"):
            if key in details:
                summary[key] = details[key]
        if "applications" in details:
            counts: dict[str, int] = {}
            for item in details["applications"]:
                action = str(item.get("action", "unknown"))
                counts[action] = counts.get(action, 0) + 1
            summary["application_resolution_counts"] = counts
        if "category_results" in details and "C__CATG__CPU" in details["category_results"]:
            cpu_result = details["category_results"]["C__CATG__CPU"]
            if isinstance(cpu_result, dict):
                summary["cpu_save_status"] = cpu_result.get("status")
                summary["cpu_rejected_fields"] = sorted(cpu_result.get("failed_fields", {}))
        if "payload" in details:
            summary["payload"] = _payload_log_summary(details["payload"])
    compact = json.dumps(summary, default=str, sort_keys=True)
    if len(compact) <= MAX_SYNC_LOG_DETAILS_CHARS:
        return compact
    # Keep the log valid JSON even when diagnostics exceed the size budget.
    reduced = {key: summary[key] for key in (
        "truncated", "original_size", "sha256", "upstream_write_performed",
        "application_resolution_counts", "application_lookup", "application_save_counts", "drive_save_counts", "category_save_counts",
        "cpu_save_status", "cpu_rejected_fields",
    ) if key in summary}
    for key in ("warnings", "errors"):
        if key in summary:
            values = summary[key] if isinstance(summary[key], list) else [summary[key]]
            reduced[key] = [str(value)[:300] for value in values[:3]]
    compact = json.dumps(reduced, default=str, sort_keys=True, ensure_ascii=False)
    if len(compact) <= MAX_SYNC_LOG_DETAILS_CHARS:
        return compact
    return json.dumps({key: summary[key] for key in ("truncated", "original_size", "sha256")})


def log_sync(db: Session, device_id: Optional[int], mode: str, result: str, message: str, details: Optional[dict[str, Any]] = None, object_id: Optional[str] = None) -> IdoitSyncLog:
    log_details = details or {}
    row = IdoitSyncLog(
        device_id=device_id,
        mode=mode,
        result=result,
        idoit_object_id=object_id,
        message=message,
        details_json=_safe_log_details(log_details),
    )
    db.add(row)
    log_context: dict[str, Any] = {
        "device_id": device_id,
        "mode": mode,
        "result": result,
        "idoit_object_id": object_id,
    }
    if isinstance(log_details, dict):
        if log_details.get("warnings"):
            log_context["warnings"] = log_details.get("warnings")
        if log_details.get("errors"):
            log_context["errors"] = log_details.get("errors")
        if log_details.get("error"):
            log_context["error"] = log_details.get("error")
        if log_details.get("retry"):
            log_context["retry"] = log_details.get("retry")
        if log_details.get("stale_object_id"):
            log_context["stale_object_id"] = log_details.get("stale_object_id")
    log_message = "i-doit sync log: %s | %s"
    if result == "failure":
        logger.error(log_message, message, json.dumps(log_context, default=str, sort_keys=True))
    elif result == "skipped" or log_context.get("warnings") or log_context.get("retry"):
        logger.warning(log_message, message, json.dumps(log_context, default=str, sort_keys=True))
    else:
        logger.info(log_message, message, json.dumps(log_context, default=str, sort_keys=True))
    return row


def _plain_category_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "title", "name", "const", "id"):
            nested = value.get(key)
            if nested not in (None, ""):
                return nested
        return None
    return value


def _object_reference_id(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        for key in ("id", "objID", "object_id", "object", "isys_obj__id"):
            candidate = value.get(key)
            if candidate not in (None, ""):
                try:
                    return str(_object_id_as_int(candidate))
                except IdoitConnectionError:
                    continue
    try:
        return str(_object_id_as_int(value))
    except IdoitConnectionError:
        return None


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
            if nested and all(str(k).isdigit() and isinstance(v, dict) for k, v in nested.items()):
                return list(nested.values())
            return [nested] if nested else []
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


def _object_entry_id(entry: dict[str, Any]) -> Optional[str]:
    for key in ("id", "objID", "object_id", "object", "isys_obj__id"):
        value = entry.get(key)
        value = _plain_category_value(value)
        if value not in (None, ""):
            try:
                return str(_object_id_as_int(value))
            except IdoitConnectionError:
                continue
    return None


def _object_entry_title(entry: dict[str, Any]) -> str:
    for key in ("title", "name", "object_title", "isys_obj__title"):
        value = _plain_category_value(entry.get(key))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _object_entry_sysid(entry: dict[str, Any]) -> str:
    for key in ("sysid", "sys_id", "SYSID", "SYS-ID", "isys_obj__sysid"):
        value = _plain_category_value(entry.get(key))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _object_entry_type_constant(entry: dict[str, Any]) -> str:
    for key in ("type_const", "object_type_const", "objecttype_const", "type", "object_type"):
        value = _plain_category_value(entry.get(key))
        if isinstance(value, str) and value.startswith("C__OBJTYPE__"):
            return value.strip()
    return ""


def _identity_terms(payload: dict[str, Any]) -> dict[str, str]:
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    result: dict[str, str] = {}
    for key in ("idoit_sysid", "cmdb_id", "mac_address", "hostname", "ip_address"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    title = payload.get("title")
    if isinstance(title, str) and title.strip():
        result["title"] = title.strip()
    return result


def _normalized_match_text(value: Any) -> str:
    text = str(_plain_category_value(value) or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _operating_system_match_key(value: Any) -> str:
    """Normalize harmless operating-system title variations for lookup only.

    Major/minor version tokens stay part of the key, while vendor, edition and
    point-release noise is removed.  The resolver still accepts this fallback
    only when it yields one unambiguous Operating System object.
    """
    text = unicodedata.normalize("NFKD", _normalized_match_text(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"(\d+)\.(\d+)(?:\.\d+)+", r"\1.\2", text)
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    ignored = {
        "gnu", "linux", "lts", "microsoft", "operating", "system",
        "edition", "standard", "datacenter", "enterprise", "professional",
        "pro", "home",
    }
    parts = [part for part in text.split() if part not in ignored]
    # WMI reports the technical Windows NT build after the marketing name, for
    # example "Windows Server 2025 Standard 10.0.26100".  i-doit OS objects
    # normally use the product name alone.  Once a Windows Server release year
    # identifies the product, the NT major/minor value adds no identity and
    # would prevent that otherwise exact normalized match.  Deliberately keep
    # version tokens for other products to avoid broadening the fallback.
    is_named_windows_server = (
        "windows" in parts
        and "server" in parts
        and any(re.fullmatch(r"20\d{2}", part) for part in parts)
    )
    if is_named_windows_server:
        parts = [part for part in parts if not re.fullmatch(r"\d+\.\d+", part)]
    return " ".join(parts)


def _windows_server_product_title(value: str) -> str:
    """Strip only a trailing Windows NT build from a named server release."""
    if not re.search(r"\bwindows\s+server\s+20\d{2}\b", value, re.IGNORECASE):
        return value
    return re.sub(r"\s+\d+\.\d+\.\d+(?:\.\d+)?$", "", value).strip()


def _windows_server_edition(value: Any) -> str | None:
    text = _normalized_match_text(value)
    if not re.search(r"\bwindows\s+server\b", text):
        return None
    edition = re.search(r"\b(standard|datacenter|essentials|enterprise|foundation|web)\b", text)
    return edition.group(1) if edition else None


def _application_title_candidates(value: str) -> list[str]:
    """Try exact titles after removing only trailing version/architecture noise.

    Keep product years, editions and standalone numbers. Never match a
    different versioned catalog title merely because its base name is similar.
    """
    title = re.sub(r"\s+", " ", (value or "").strip())[:255]
    if not title:
        return []
    candidates = [title]
    normalized = unicodedata.normalize("NFKC", title)
    normalized = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized != title:
        candidates.append(normalized)
        title = normalized
    arch = r"(?:x64|x86|amd64|arm64|aarch64|i[3-6]86|32[- ]?bit|64[- ]?bit)"
    architecture_suffix = re.compile(
        r"(?:\s*\(" + arch + r"\)|\s*\[" + arch + r"\]|\s+" + arch + r")$", re.IGNORECASE,
    )
    # Dotted releases and explicit calendar/build formats; a bare year is a product edition.
    version = r"(?:\d{1,8}(?:\.\d{1,8}){1,5}(?:[-_]\d{1,8})*|(?:19|20)\d{2}[-.](?:0[1-9]|1[0-2])(?:[-_]\d{1,8})+|\d{1,8}(?:_\d{1,8}){1,5})"
    version_suffix = re.compile(
        r"(?:\s+(?:[-–]\s+)?(?:v(?:ersion)?\s*)?" + version
        + r"|\s+(?:[-–]\s+)?(?:v(?:ersion)?\s*)\d{1,8}"
        + r"|\s*\((?:v(?:ersion)?\s*)?" + version + r"\))$", re.IGNORECASE,
    )
    used = set()
    for _ in range(2):
        for label, pattern in (("architecture", architecture_suffix), ("version", version_suffix)):
            if label in used:
                continue
            candidate = pattern.sub("", title).strip()
            if candidate != title and any(char.isalpha() for char in candidate):
                candidates.append(candidate)
                title = candidate
                used.add(label)
                break
        else:
            break
    return candidates


def _application_match_key(value: str) -> str:
    """Normalize typographic differences, without dropping product editions/years."""
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"[-\u2010-\u2015\u2212]+", " ", text)
    # A hyphen between a numeric brand prefix and letters is optional.
    text = re.sub(r"(?<=\d)(?=[a-z])", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _application_catalog_aliases(title: str) -> set[str]:
    # Architecture is not a product edition. Keep explicit catalog versions
    # intact: never map an installed release onto a different release.
    normalized = unicodedata.normalize("NFKC", title)
    arch = r"(?:x64|x86|amd64|arm64|aarch64|i[3-6]86|32[- ]?bit|64[- ]?bit)"
    without_arch = re.sub(r"(?:\s*\(" + arch + r"\)|\s*\[" + arch + r"\]|\s+" + arch + r")$", "", normalized, flags=re.IGNORECASE)
    return {_application_match_key(title), _application_match_key(without_arch)}


def _normalized_match_mac(value: Any) -> str:
    text = str(_plain_category_value(value) or "").strip()
    normalized = normalize_mac(text)
    if normalized:
        return normalized.lower()
    return re.sub(r"[^0-9a-f]", "", text.lower())


def _category_entry_values(entry: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = _plain_category_value(entry.get(key))
        if value not in (None, ""):
            values.append(str(value).strip())
    return values


def _identity_text_matches(value: Any, expected: str) -> bool:
    value_text = _normalized_match_text(value)
    expected_text = _normalized_match_text(expected)
    if not value_text or not expected_text:
        return False
    if value_text == expected_text:
        return True
    raw_parts = [part.strip() for part in re.split(r"[\r\n,;|]+", str(_plain_category_value(value) or "")) if part.strip()]
    return any(_normalized_match_text(part) == expected_text for part in raw_parts)


def _entry_contains_identity(entry: dict[str, Any], identity: dict[str, str], field_map: dict[str, tuple[str, ...]]) -> tuple[int, Optional[str]]:
    for identity_key, keys in field_map.items():
        expected = identity.get(identity_key)
        if not expected:
            continue
        expected_text = _normalized_match_text(expected)
        expected_mac = _normalized_match_mac(expected) if identity_key == "mac_address" else ""
        for value in _category_entry_values(entry, keys):
            if identity_key == "mac_address":
                if expected_mac and _normalized_match_mac(value) == expected_mac:
                    return 100, identity_key
            elif _identity_text_matches(value, expected_text):
                return 95 if identity_key == "idoit_sysid" else 90 if identity_key in {"cmdb_id", "ip_address"} else 80, identity_key
    return 0, None


def _is_missing_object_error(exc: IdoitConnectionError) -> bool:
    detail = json.dumps(exc.to_detail(), default=str).lower()
    missing_markers = (
        "not found",
        "not be found",
        "does not exist",
        "not exists",
        "unknown object",
        "no object",
        "invalid object",
        "references an existing object",
        "needs to be a integer value",
        "needs to be an integer value",
    )
    return any(marker in detail for marker in missing_markers)


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
        self.last_identity_match_debug: dict[str, Any] = {}
        self._application_catalog: dict[str, dict[str, str]] | None = None
        self._application_catalog_complete = False
        self.application_lookup_debug: dict[str, Any] = {}
        self.category_snapshot = None

    async def call(self, method: str, params: Optional[dict[str, Any]] = None) -> Any:
        try:
            validate_idoit_https_url(self.endpoint, self.config.allow_insecure_http)
        except ValueError as exc:
            raise IdoitConnectionError(str(exc), stage="url_validation") from exc
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
                verify_tls=not self.config.skip_tls_verification,
            )
        except ValueError as exc:
            raise IdoitConnectionError(str(exc), stage="url_validation", endpoint=self.endpoint) from exc
        except TimeoutError as exc:
            raise IdoitConnectionError("Connection timed out while calling i-doit", stage="network", endpoint=self.endpoint) from exc
        except Exception as exc:
            if isinstance(exc, ssl.SSLCertVerificationError) or isinstance(exc.__cause__, ssl.SSLCertVerificationError):
                raise IdoitConnectionError(
                    "i-doit TLS certificate verification failed. Check hostname, certificate chain and trusted CA.",
                    stage="tls_verification", endpoint=self.endpoint,
                ) from exc
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

    async def logout_best_effort(self) -> None:
        """Close the i-doit session so upstream object locks are released."""
        if not self._session_id:
            return
        try:
            await self.call("idoit.logout")
        except Exception:
            # Logout must never hide the result of the actual operation. i-doit
            # also expires abandoned sessions server-side as a final fallback.
            pass
        finally:
            self._session_id = None

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

    async def read_objects(self, params: dict[str, Any]) -> Any:
        return await self.call("cmdb.objects.read", params)

    async def find_object_by_title(self, title: str, object_type: Optional[str] = None) -> Optional[str]:
        """Best-effort lookup to avoid duplicate creates when local state is empty.

        i-doit installations/API versions differ slightly in list-filter shape.
        Try the common variants and only accept exact title matches. This is a
        safety net; the persisted `idoit_device_sync.idoit_object_id` remains
        the primary identity once a device has been linked.
        """
        wanted = (title or "").strip().lower()
        if not wanted:
            return None
        filters = [
            {"filter": {"title": title, "type": object_type}} if object_type else None,
            {"filter": {"title": title}},
            {"title": title},
            {"q": title},
        ]
        for params in [item for item in filters if item]:
            try:
                result = await self.read_objects(params)
            except IdoitConnectionError:
                continue
            for entry in _category_entries(result):
                if _object_entry_title(entry).strip().lower() == wanted:
                    object_id = _object_entry_id(entry)
                    if object_id:
                        return object_id
        return None

    async def _resolve_inventory_object(self, title: str, object_type: str, create_missing: bool,
                                        normalize_os: bool = False) -> dict[str, Any]:
        """Resolve inventory links using documented, type-scoped i-doit filters."""
        wanted = re.sub(r"\s+", " ", (title or "").strip())[:255]
        if not wanted:
            return {"object_id": None, "action": "skipped_empty"}
        product_title = _windows_server_product_title(wanted) if normalize_os else wanted
        wanted_key = _operating_system_match_key(wanted) if normalize_os else ""
        wanted_edition = _windows_server_edition(wanted) if normalize_os else None
        exact_candidates: dict[str, str] = {}
        normalized_candidates: dict[str, str] = {}

        def collect(entries: list[dict[str, Any]]) -> None:
            for entry in entries:
                candidate_type = _object_entry_type_constant(entry)
                if candidate_type and candidate_type != object_type:
                    continue
                # The documented typed filter may return a numeric type ID.
                # Do not use unscoped queries or accept archived/deleted objects.
                status = str(_plain_category_value(entry.get("status")) or "")
                if status and status not in ("2", "C__RECORD_STATUS__NORMAL"):
                    continue
                object_id = _object_entry_id(entry)
                candidate_title = _object_entry_title(entry)
                if not object_id or not candidate_title:
                    continue
                if _normalized_match_text(candidate_title) == _normalized_match_text(wanted):
                    exact_candidates[object_id] = candidate_title
                elif normalize_os and wanted_key and _operating_system_match_key(candidate_title) == wanted_key:
                    if not wanted_edition or _windows_server_edition(candidate_title) == wanted_edition:
                        normalized_candidates[object_id] = candidate_title

        def resolution(candidates: dict[str, str], normalized: bool) -> dict[str, Any] | None:
            if len(candidates) > 1:
                return {"object_id": None, "action": "ambiguous_match", "title": wanted,
                        "candidates": list(candidates.values())}
            if len(candidates) == 1:
                object_id, matched_title = next(iter(candidates.items()))
                result = {"object_id": object_id, "action": "matched_normalized" if normalized else "matched",
                          "title": wanted}
                if normalized:
                    result["matched_title"] = matched_title
                return result
            return None

        # Use exact title filters first, including the human-readable OS title.
        # The API documents filter.title, not a top-level q search for this method.
        for query_title in dict.fromkeys((wanted, product_title)):
            entries = _category_entries(await self.read_objects({
                "filter": {"type": object_type, "title": query_title, "status": "C__RECORD_STATUS__NORMAL"},
            }))
            collect(entries)
            if exact := resolution(exact_candidates, False):
                return exact

        # An exact product-title result is enough if it is unique and has a
        # specific edition. Otherwise inspect the scoped catalog to establish
        # uniqueness rather than guessing or creating a duplicate.
        product_matches = {key: value for key, value in normalized_candidates.items()
                           if _normalized_match_text(value) == _normalized_match_text(product_title)}
        if wanted_edition and product_title != wanted and product_matches:
            return resolution(product_matches, True)

        if normalize_os:
            page_size, maximum = 500, 5000
            seen: set[str] = set()
            complete = False
            for offset in range(0, maximum, page_size):
                entries = _category_entries(await self.read_objects({
                    "filter": {"type": object_type, "status": "C__RECORD_STATUS__NORMAL"},
                    "limit": f"{offset},{page_size}", "order_by": "id", "sort": "ASC",
                }))
                ids = {object_id for entry in entries if (object_id := _object_entry_id(entry))}
                collect(entries)
                if len(entries) < page_size:
                    complete = True
                    break
                if not ids - seen:
                    break
                seen.update(ids)
            if not complete:
                return {"object_id": None, "action": "lookup_incomplete", "title": wanted}
            if result := resolution(exact_candidates, False) or resolution(normalized_candidates, True):
                return result
        if not create_missing:
            return {"object_id": None, "action": "match_required", "title": wanted}
        object_id = await self.create_object(product_title, object_type)
        return {"object_id": object_id, "action": "created", "title": wanted}

    async def resolve_operating_system(self, title: str, create_missing: bool = False) -> dict[str, Any]:
        return await self._resolve_inventory_object(title, "C__OBJTYPE__OPERATING_SYSTEM", create_missing,
                                                    normalize_os=True)

    async def resolve_application(self, title: str, create_missing: bool = False) -> dict[str, Any]:
        candidates = _application_title_candidates(title)
        if not candidates:
            return {"object_id": None, "action": "skipped_empty"}
        wanted = candidates[0]
        object_type = "C__OBJTYPE__APPLICATION"
        catalog_was_loaded = self._application_catalog is not None
        for candidate in candidates if not catalog_was_loaded else ():
            result = await self._resolve_inventory_object(candidate, object_type, False)
            if result["action"] == "ambiguous_match":
                return {**result, "title": wanted}
            if result.get("object_id"):
                if candidate != wanted:
                    return {**result, "action": "matched_normalized", "title": wanted,
                            "matched_title": candidate}
                return result
        # Some API versions return no rows for a title filter even though the
        # product is present in the typed catalog. Query that catalog once per
        # client/session and compare complete candidate titles locally.
        if self._application_catalog is None:
            await self._load_application_catalog()
        if not self._application_catalog_complete:
            return {"object_id": None, "action": "lookup_incomplete", "title": wanted}
        if not self._application_catalog and not create_missing:
            return {"object_id": None, "action": "catalog_empty", "title": wanted}
        for candidate in candidates:
            matches = self._application_catalog.get(_normalized_match_text(candidate), {})
            if len(matches) > 1:
                return {"object_id": None, "action": "ambiguous_match", "title": wanted,
                        "candidates": list(matches.values())}
            if len(matches) == 1:
                object_id, matched_title = next(iter(matches.items()))
                result = {"object_id": object_id, "action": "matched" if candidate == wanted else "matched_normalized",
                          "title": wanted, "lookup": "typed_catalog"}
                if candidate != wanted:
                    result["matched_title"] = matched_title
                return result
        # Compare both sides with the same conservative typography rules.
        # Exact and explicit product-title candidates above have precedence.
        for candidate in candidates:
            key = _application_match_key(candidate)
            matches = {oid: name for entries in self._application_catalog.values()
                       for oid, name in entries.items() if key in _application_catalog_aliases(name)}
            if len(matches) > 1:
                return {"object_id": None, "action": "ambiguous_match", "title": wanted,
                        "candidates": list(matches.values()), "lookup": "normalized_catalog"}
            if len(matches) == 1:
                object_id, matched_title = next(iter(matches.items()))
                return {"object_id": object_id, "action": "matched_normalized", "title": wanted,
                        "matched_title": matched_title, "lookup": "normalized_catalog"}
        # A typed list can omit an object that a typed title query returns.
        # Recheck a cache miss by product title before declaring it missing.
        # This is an exact object-type/status scoped lookup, not substring matching.
        if catalog_was_loaded:
            candidate = candidates[-1]
            self.application_lookup_debug["direct_fallback_queries"] = self.application_lookup_debug.get("direct_fallback_queries", 0) + 1
            direct = await self._resolve_inventory_object(candidate, object_type, False)
            if direct.get("action") == "ambiguous_match":
                return {**direct, "title": wanted, "lookup": "direct_fallback"}
            if direct.get("object_id"):
                oid = direct["object_id"]
                self._application_catalog.setdefault(_normalized_match_text(candidate), {})[oid] = candidate
                self.application_lookup_debug["direct_fallback_matches"] = self.application_lookup_debug.get("direct_fallback_matches", 0) + 1
                return {**direct, "title": wanted,
                        "action": "matched" if candidate == wanted else "matched_normalized",
                        "matched_title": candidate, "lookup": "direct_fallback"}
        if not create_missing:
            return {"object_id": None, "action": "match_required", "title": wanted, "lookup": "typed_catalog"}
        object_id = await self.create_object(wanted, object_type)
        self._application_catalog.setdefault(_normalized_match_text(wanted), {})[object_id] = wanted
        return {"object_id": object_id, "action": "created", "title": wanted}

    async def _load_application_catalog(self) -> None:
        object_type = "C__OBJTYPE__APPLICATION"

        async def scan(type_filter: str | int, expected_type_id: str = "", include_status: bool = True):
            catalog: dict[str, dict[str, str]] = {}
            seen: set[str] = set()
            page_size, maximum = 500, 10000
            complete = False
            rejected = 0
            for offset in range(0, maximum, page_size):
                filters: dict[str, Any] = {"type": type_filter}
                if include_status:
                    filters["status"] = "C__RECORD_STATUS__NORMAL"
                entries = _category_entries(await self.read_objects({
                    "filter": filters,
                    "limit": f"{offset},{page_size}", "order_by": "id", "sort": "ASC",
                }))
                ids = {oid for entry in entries if (oid := _object_entry_id(entry))}
                if entries and (not ids or ids & seen):
                    break
                for entry in entries:
                    candidate_type = _object_entry_type_constant(entry)
                    numeric_type = str(_plain_category_value(entry.get("type") or entry.get("objecttype") or entry.get("isys_obj__isys_obj_type__id")) or "")
                    status = str(_plain_category_value(entry.get("status")) or "")
                    if ((candidate_type and candidate_type != object_type)
                            or (expected_type_id and numeric_type.isdigit() and numeric_type != expected_type_id)
                            or (status and status not in ("2", "C__RECORD_STATUS__NORMAL"))
                            or (not include_status and status not in ("2", "C__RECORD_STATUS__NORMAL"))):
                        rejected += 1
                        continue
                    title, oid = _object_entry_title(entry), _object_entry_id(entry)
                    if title and oid:
                        catalog.setdefault(_normalized_match_text(title), {})[oid] = title
                    else:
                        rejected += 1
                seen.update(ids)
                if len(entries) < page_size:
                    complete = True
                    break
            return catalog, complete, {
                "filter_type": type_filter, "status_filter": include_status, "rows": len(seen),
                "accepted": sum(len(matches) for matches in catalog.values()),
                "rejected": rejected, "complete": complete,
            }

        catalog, complete, attempt = await scan(object_type)
        attempts = [attempt]
        # Resolve the actual numeric type from the tenant rather than hard-code
        # an installation-specific ID. Some servers return no objects for the
        # constant filter. Only retry with an explicitly verified type ID.
        if complete and not catalog:
            try:
                types = _category_entries(await self.call("cmdb.object_types", {
                    "filter": {"id": object_type}, "countobjects": True,
                }))
            except IdoitConnectionError:
                types = []
                self.application_lookup_debug["type_lookup_failed"] = True
            verified = {}
            for entry in types:
                const = entry.get("const") or entry.get("isys_obj_type__const")
                oid = entry.get("id") or entry.get("isys_obj_type__id")
                if const == object_type and str(oid).isdigit() and int(oid) > 0:
                    verified[str(oid)] = entry
            if len(verified) == 1:
                type_id, metadata = next(iter(verified.items()))
                self.application_lookup_debug["object_type_id"] = type_id
                count = metadata.get("objectcount")
                if str(count).isdigit():
                    self.application_lookup_debug["reported_object_count"] = int(count)
                catalog, complete, attempt = await scan(int(type_id), type_id)
                attempts.append(attempt)
                # Retry without the server-side status filter only when the
                # object type is verified; enforce NORMAL explicitly locally.
                if complete and not catalog:
                    catalog, complete, attempt = await scan(int(type_id), type_id, include_status=False)
                    attempts.append(attempt)
                # An empty list despite a positive reported object count may
                # indicate an API filter/permission issue. Do not create blindly.
                if not catalog and str(count).isdigit() and int(count) > 0:
                    complete = False
            else:
                # Cannot distinguish an empty catalog from an invalid filter.
                complete = False
                self.application_lookup_debug["type_lookup_unverified"] = True
        self._application_catalog = catalog
        self._application_catalog_complete = complete
        self.application_lookup_debug.update({
            "attempts": attempts, "complete": complete,
            "catalog_size": sum(len(matches) for matches in catalog.values()),
        })

    async def diagnose_application(self, title: str) -> dict[str, Any]:
        """Read-only diagnosis: catalog and candidate matches, no object creation."""
        candidates = _application_title_candidates(title)
        resolution = await self.resolve_application(title, create_missing=False)
        # Load the catalog even if an exact title query already matched.
        if self._application_catalog is None:
            await self._load_application_catalog()
        catalog = self._application_catalog or {}
        candidate_matches = []
        for candidate in candidates:
            exact = catalog.get(_normalized_match_text(candidate), {})
            key = _application_match_key(candidate)
            normalized = {oid: name for entries in catalog.values() for oid, name in entries.items()
                          if key in _application_catalog_aliases(name)}
            candidate_matches.append({
                "title": candidate, "matches": [{"object_id": oid, "title": name}
                                                  for oid, name in list(exact.items())[:20]],
                "match_count": len(exact),
                "normalized_matches": [{"object_id": oid, "title": name}
                                       for oid, name in list(normalized.items())[:20]],
                "normalized_match_count": len(normalized),
            })
        return {"resolution": resolution, "candidates": candidate_matches,
                "matching_revision": 3, "build_commit": BUILD_COMMIT,
                "catalog": self.application_lookup_debug, "create_policy": self.config.create_policy,
                "upstream_write_performed": False}

    async def find_object_by_sysid(self, sysid: str, object_type: Optional[str] = None) -> Optional[str]:
        """Find an existing i-doit object by exact SYSID before fuzzy identity matching."""
        wanted = (sysid or "").strip()
        if not wanted:
            return None
        lookup_debug = {
            "direct_candidate_count": 0,
            "fallback_scan_performed": False,
            "fallback_candidate_count": 0,
            "fallback_limit": MAX_SYSID_SCAN_OBJECTS,
            "limit_reached": False,
            "result": None,
            "attempts": [],
        }
        filters = [
            {"filter": {"sysid": wanted, "type": object_type}} if object_type else None,
            {"filter": {"sysid": wanted}},
            {"filter": {"SYSID": wanted}},
            {"filter": {"C__CATG__ACCOUNTING.inventory_no": wanted, "type": object_type}} if object_type else None,
            {"filter": {"C__CATG__ACCOUNTING.inventory_no": wanted}},
            {"filter": {"C__CATG__ACCOUNTING.inventory_number": wanted}},
            {"sysid": wanted},
            {"q": wanted},
        ]
        seen_ids: set[str] = set()
        for params in [item for item in filters if item]:
            attempt = {
                "params": params,
                "candidate_count": 0,
                "candidates": [],
                "error": None,
            }
            lookup_debug["attempts"].append(attempt)
            try:
                result = await self.read_objects(params)
            except IdoitConnectionError as exc:
                attempt["error"] = exc.to_detail()
                continue
            entries = _category_entries(result)
            attempt["candidate_count"] = len(entries)
            for entry in entries:
                object_id = _object_entry_id(entry)
                if not object_id or object_id in seen_ids:
                    continue
                seen_ids.add(object_id)
                lookup_debug["direct_candidate_count"] += 1
                entry_sysid = _object_entry_sysid(entry)
                candidate_debug: dict[str, Any] = {
                    "object_id": object_id,
                    "title": _object_entry_title(entry),
                    "entry_sysid": entry_sysid or None,
                    "object_sysid": None,
                    "category_score": None,
                    "category_match": None,
                    "rejected_reason": None,
                }
                if len(attempt["candidates"]) < 20:
                    attempt["candidates"].append(candidate_debug)
                if entry_sysid and entry_sysid == wanted:
                    lookup_debug["result"] = {"object_id": object_id, "matched_by": "object_list_sysid"}
                    self.last_identity_match_debug["sysid_lookup"] = lookup_debug
                    return object_id
                try:
                    upstream_sysid = await self.object_sysid(object_id)
                except IdoitConnectionError as exc:
                    candidate_debug["rejected_reason"] = f"object_sysid_error: {exc.message}"
                    continue
                candidate_debug["object_sysid"] = upstream_sysid
                if upstream_sysid and upstream_sysid.strip() == wanted:
                    lookup_debug["result"] = {"object_id": object_id, "matched_by": "object_sysid"}
                    self.last_identity_match_debug["sysid_lookup"] = lookup_debug
                    return object_id
                category_score, category_match = await self._identity_category_score(object_id, {"idoit_sysid": wanted})
                candidate_debug["category_score"] = category_score
                candidate_debug["category_match"] = category_match
                if category_score >= 95 and category_match == "idoit_sysid":
                    lookup_debug["result"] = {"object_id": object_id, "matched_by": "accounting_inventory_sysid"}
                    self.last_identity_match_debug["sysid_lookup"] = lookup_debug
                    return object_id
                candidate_debug["rejected_reason"] = "no exact SYSID match on object entry, object read, or mapped identity categories"
        fallback_match = await self._scan_objects_for_sysid(wanted, object_type, seen_ids, lookup_debug)
        self.last_identity_match_debug["sysid_lookup"] = lookup_debug
        if fallback_match:
            return fallback_match
        return None

    async def _scan_objects_for_sysid(self, wanted: str, object_type: Optional[str], seen_ids: set[str], lookup_debug: dict[str, Any]) -> Optional[str]:
        """Bounded fallback for i-doit tenants that do not support SYSID/category filters."""
        lookup_debug["fallback_scan_performed"] = True
        lookup_debug["fallback_pages"] = []
        base_queries: list[dict[str, Any]] = []
        if object_type:
            base_queries.extend([
                {"filter": {"type": object_type}},
                {"type": object_type},
            ])
        base_queries.append({})
        for base_query in base_queries:
            for object_id in await self._listed_object_ids(base_query, lookup_debug["fallback_pages"]):
                if object_id in seen_ids:
                    continue
                seen_ids.add(object_id)
                lookup_debug["fallback_candidate_count"] += 1
                if lookup_debug["fallback_candidate_count"] > MAX_SYSID_SCAN_OBJECTS:
                    lookup_debug["limit_reached"] = True
                    return None
                try:
                    upstream_sysid = await self.object_sysid(object_id)
                except IdoitConnectionError:
                    continue
                if upstream_sysid and upstream_sysid.strip() == wanted:
                    lookup_debug["result"] = {"object_id": object_id, "matched_by": "fallback_object_sysid"}
                    return object_id
                category_score, category_match = await self._identity_category_score(object_id, {"idoit_sysid": wanted})
                if category_score >= 95 and category_match == "idoit_sysid":
                    lookup_debug["result"] = {"object_id": object_id, "matched_by": "fallback_accounting_inventory_sysid"}
                    return object_id
        return None

    async def _listed_object_ids(self, base_query: dict[str, Any], debug_pages: Optional[list[dict[str, Any]]] = None) -> list[str]:
        entries = await self._listed_object_entries(base_query, debug_pages)
        return [object_id for object_id, _title in entries]

    async def _listed_object_entries(self, base_query: dict[str, Any], debug_pages: Optional[list[dict[str, Any]]] = None) -> list[tuple[str, str]]:
        objects: list[tuple[str, str]] = []
        seen: set[str] = set()

        async def read_page(query: dict[str, Any]) -> tuple[int, int, Optional[str]]:
            try:
                result = await self.read_objects(query)
            except IdoitConnectionError as exc:
                return 0, 0, exc.message
            entries = _category_entries(result)
            added = 0
            for entry in entries:
                object_id = _object_entry_id(entry)
                if object_id and object_id not in seen:
                    seen.add(object_id)
                    objects.append((object_id, _object_entry_title(entry)))
                    added += 1
                    if len(objects) >= MAX_SYSID_SCAN_OBJECTS:
                        return len(entries), added, None
            return len(entries), added, None

        page_size = min(MAX_SYSID_SCAN_OBJECTS, 500)
        offset = 0
        while offset < MAX_SYSID_SCAN_OBJECTS:
            if len(objects) >= MAX_SYSID_SCAN_OBJECTS:
                break
            paged_query = dict(base_query)
            paged_query.update({"limit": page_size, "offset": offset})
            entry_count, added, error = await read_page(paged_query)
            if debug_pages is not None and len(debug_pages) < 40:
                debug_pages.append({
                    "base_query": base_query,
                    "limit": page_size,
                    "offset": offset,
                    "entry_count": entry_count,
                    "new_entries": added,
                    "error": error,
                })
            if entry_count <= 0:
                break
            # If the tenant ignores offset and returns an already-seen page,
            # stop instead of looping over the same objects repeatedly.
            if added <= 0:
                break
            offset += entry_count
        return objects

    async def _scan_objects_for_identity(self, identity: dict[str, str], object_type: Optional[str], seen_ids: set[str]) -> Optional[dict[str, Any]]:
        """Bounded fallback for i-doit tenants that cannot search category fields."""
        scan_debug = {
            "fallback_scan_performed": True,
            "fallback_candidate_count": 0,
            "fallback_limit": MAX_SYSID_SCAN_OBJECTS,
            "limit_reached": False,
            "best_candidate": None,
            "result": None,
        }
        self.last_identity_match_debug["fallback_identity_scan"] = scan_debug
        base_queries: list[dict[str, Any]] = []
        if object_type:
            base_queries.extend([
                {"filter": {"type": object_type}},
                {"type": object_type},
            ])
        base_queries.append({})
        best: Optional[dict[str, Any]] = None
        for base_query in base_queries:
            scan_pages: list[dict[str, Any]] = []
            scan_debug.setdefault("fallback_pages", scan_pages)
            for object_id, title in await self._listed_object_entries(base_query, scan_pages):
                if object_id in seen_ids:
                    continue
                seen_ids.add(object_id)
                scan_debug["fallback_candidate_count"] += 1
                if scan_debug["fallback_candidate_count"] > MAX_SYSID_SCAN_OBJECTS:
                    scan_debug["limit_reached"] = True
                    return best if best and best["confidence"] >= 80 else None
                score = 0
                matched_by = None
                title_text = _normalized_match_text(title)
                if title_text:
                    for key in ("title", "hostname"):
                        if identity.get(key) and title_text == _normalized_match_text(identity[key]):
                            score = 80 if key == "title" else 85
                            matched_by = key
                            break
                category_score, category_match = await self._identity_category_score(object_id, identity)
                if category_score > score:
                    score = category_score
                    matched_by = category_match
                if score <= 0:
                    continue
                candidate = {"object_id": object_id, "confidence": score, "matched_by": matched_by or "identity_fallback"}
                if best is None or candidate["confidence"] > best["confidence"]:
                    best = candidate
                    scan_debug["best_candidate"] = candidate
                    if candidate["confidence"] >= 95:
                        scan_debug["result"] = candidate
                        return candidate
        result = best if best and best["confidence"] >= 80 else None
        scan_debug["result"] = result
        return result

    async def find_existing_object(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Find an existing i-doit object from stable LanLens identity fields."""
        identity = _identity_terms(payload)
        self.last_identity_match_debug = {
            "identity": identity,
            "object_type": payload.get("objectType") if isinstance(payload.get("objectType"), str) else None,
            "search_values": [],
            "candidate_count": 0,
            "best_candidate": None,
            "result": None,
        }
        if not identity:
            return None
        object_type = payload.get("objectType") if isinstance(payload.get("objectType"), str) else None
        sysid_match = await self.find_object_by_sysid(identity.get("idoit_sysid", ""), object_type)
        if sysid_match:
            result = {"object_id": sysid_match, "confidence": 100, "matched_by": "idoit_sysid"}
            self.last_identity_match_debug["result"] = result
            return result
        search_values = [
            identity.get("idoit_sysid"),
            identity.get("cmdb_id"),
            identity.get("mac_address"),
            identity.get("ip_address"),
            identity.get("hostname"),
            identity.get("title"),
        ]
        self.last_identity_match_debug["search_values"] = [item for item in search_values if item]
        seen_ids: set[str] = set()
        candidates: list[tuple[str, str]] = []
        for value in [item for item in search_values if item]:
            filters = [
                {"filter": {"title": value, "type": object_type}} if object_type else None,
                {"filter": {"title": value}},
                {"q": value},
                {"title": value},
            ]
            for params in [item for item in filters if item]:
                try:
                    result = await self.read_objects(params)
                except IdoitConnectionError:
                    continue
                for entry in _category_entries(result):
                    object_id = _object_entry_id(entry)
                    if not object_id or object_id in seen_ids:
                        continue
                    seen_ids.add(object_id)
                    candidates.append((object_id, _object_entry_title(entry)))
        self.last_identity_match_debug["candidate_count"] = len(candidates)
        best: Optional[dict[str, Any]] = None
        for object_id, title in candidates:
            score = 0
            matched_by = None
            title_text = _normalized_match_text(title)
            if title_text:
                for key in ("title", "hostname"):
                    if identity.get(key) and title_text == _normalized_match_text(identity[key]):
                        score = 80 if key == "title" else 85
                        matched_by = key
                        break
            category_score, category_match = await self._identity_category_score(object_id, identity)
            if category_score > score:
                score = category_score
                matched_by = category_match
            if score <= 0:
                continue
            candidate = {"object_id": object_id, "confidence": score, "matched_by": matched_by or "identity"}
            if best is None or candidate["confidence"] > best["confidence"]:
                best = candidate
        self.last_identity_match_debug["best_candidate"] = best
        result = best if best and best["confidence"] >= 80 else None
        if result is None:
            result = await self._scan_objects_for_identity(identity, object_type, seen_ids)
        self.last_identity_match_debug["result"] = result
        return result

    async def _identity_category_score(self, object_id: str, identity: dict[str, str]) -> tuple[int, Optional[str]]:
        checks: tuple[tuple[str, dict[str, tuple[str, ...]]], ...] = (
            ("C__CATG__ACCOUNTING", {"idoit_sysid": ("inventory_no", "inventory_number", "inventory", "title"), "cmdb_id": ("inventory_no", "inventory_number", "inventory", "title")}),
            ("C__CATG__NETWORK_PORT", {"mac_address": ("mac", "mac_address", "address", "title")}),
            ("C__CATG__IP", {"ip_address": ("ipv4_address", "ip_address", "address", "title"), "hostname": ("hostname", "title", "name")}),
            ("C__CATG__GLOBAL", {"hostname": ("title", "name"), "cmdb_id": ("purpose",)}),
        )
        best_score = 0
        best_match = None
        for category, field_map in checks:
            try:
                result = await self.read_category(object_id, category)
            except IdoitConnectionError:
                continue
            for entry in _category_entries(result):
                score, matched_by = _entry_contains_identity(entry, identity, field_map)
                if score > best_score:
                    best_score = score
                    best_match = matched_by
        return best_score, best_match

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
        key = (str(object_int), category)
        if self.category_snapshot is not None and key in self.category_snapshot:
            result = self.category_snapshot[key]
            if isinstance(result, Exception):
                raise result
            return result
        try:
            result = await self.call("cmdb.category.read", {"object": object_int, "objID": object_int, "category": category})
        except IdoitConnectionError as exc:
            if self.category_snapshot is not None:
                self.category_snapshot[key] = exc
            raise
        if self.category_snapshot is not None:
            self.category_snapshot[key] = result
        return result

    async def save_category(self, object_id: str, category: str, data: dict[str, Any], entry_id: Optional[str] = None) -> Any:
        object_int = _object_id_as_int(object_id)
        params: dict[str, Any] = {"object": object_int, "objID": object_int, "category": category, "data": data}
        if entry_id:
            params["entry"] = _object_id_as_int(entry_id)
        result = await self.call("cmdb.category.save", params)
        if result is False or (isinstance(result, dict) and str(result.get("success", True)).lower() in ("false", "0")):
            raise IdoitConnectionError("i-doit rejected the category save", stage="jsonrpc_error",
                                       endpoint=self.endpoint, jsonrpc_error=result)
        return result

    async def reconcile_category(self, object_id: str, category: str, desired: list[dict[str, Any]], clean_global=False) -> list[dict[str, Any]]:
        """One read, preflight all identities, then write only changed rows."""
        try:
            raw = await self.read_category(object_id, category)
            if not isinstance(raw, (dict, list)) or (isinstance(raw, dict) and (
                raw.get("error") or str(raw.get("success", True)).lower() in ("false", "0")
            )):
                raise IdoitConnectionError("Category read returned no valid snapshot", stage="category_read")
            if isinstance(raw, list) and any(not isinstance(row, dict) for row in raw):
                raise IdoitConnectionError("Category read contains invalid rows", stage="category_read")
            decoded = _category_entries(raw)
            if any(not _category_entry_id(row) for row in decoded):
                raise IdoitConnectionError("Category read contains rows without entry identifiers", stage="category_read")
            rows = [dict(row) for row in decoded
                    if str(_plain_category_value(row.get("status")) or "") in ("", "2", "C__RECORD_STATUS__NORMAL")]
        except IdoitConnectionError as exc:
            return [{"status": "failed", "reason": "read_failed", "error": exc.to_detail()} for _ in (desired or [{}])]
        if clean_global and category == "C__CATG__GLOBAL" and len(rows) == 1:
            cleaned = _clean_lanlens_global_description(rows[0].get("description"))
            if cleaned is not None:
                if desired:
                    desired = [{**desired[0], "description": cleaned}, *desired[1:]]
                else:
                    desired = [{"description": cleaned}]
        if not desired:
            return []
        keys = [_category_identity_key(category, data) for data in desired]
        duplicates = Counter(key for key in keys if key is not None)
        planned = []
        for key, data in zip(keys, desired):
            if key is None:
                planned.append((data, None, {"status": "failed", "reason": "missing_identity"}))
                continue
            if duplicates[key] > 1:
                planned.append((data, None, {"status": "ambiguous", "reason": "duplicate_payload_identity"}))
                continue
            try:
                matches = _matching_category_rows(category, rows, data, key)
            except IdoitConnectionError:
                planned.append((data, None, {"status": "ambiguous", "reason": "ambiguous_existing_identity"}))
                continue
            if len(matches) > 1 or (matches and not _category_entry_id(matches[0])):
                planned.append((data, None, {"status": "ambiguous", "reason": "ambiguous_existing_identity"}))
                continue
            planned.append((data, matches[0] if matches else None, None))
        claimed = Counter(_category_entry_id(row) for _, row, error in planned if row is not None and error is None)
        results = []
        for data, row, error in planned:
            if error:
                results.append(error)
                continue
            entry_id = _category_entry_id(row) if row is not None else None
            if entry_id and claimed[entry_id] > 1:
                results.append({"status": "ambiguous", "reason": "multiple_payload_rows_target_same_entry"})
                continue
            changes = {field: value for field, value in data.items()
                       if row is None or not _category_value_equal(field, row.get(field), value)}
            if not changes:
                results.append({"status": "unchanged", "entry_id": entry_id})
                continue
            try:
                result = await self.save_category(object_id, category, changes, entry_id)
            except IdoitConnectionError as exc:
                # Never retry a failed create without a verified returned entry ID.
                results.append({"status": "failed", "reason": "save_rejected", "error": exc.to_detail()})
                continue
            if row is None:
                new_id = _object_reference_id(result.get("entry")) if isinstance(result, dict) else _object_reference_id(result)
                if not new_id:
                    results.append({"status": "failed", "reason": "missing_created_entry_id"})
                    continue
                rows.append({"id": new_id, "status": "2", **data})
                results.append({"status": "created", "entry_id": new_id})
            else:
                row.update(changes)
                results.append({"status": "updated", "entry_id": entry_id, "changed_fields": sorted(changes)})
        if self.category_snapshot is not None:
            self.category_snapshot[(str(object_id), category)] = rows
        return results

    async def save_category_best_effort(self, object_id: str, category: str, data: dict[str, Any]) -> dict[str, Any]:
        """Save a category without letting one invalid field abort the sync.

        i-doit category validation is strict and differs by object type/version.
        Try the full category first; if i-doit rejects it, retry individual
        fields so valid information still lands in the CMDB and the operator can
        see exactly which field was rejected.
        """
        if category == "C__CATG__DRIVE":
            return await self.save_drive_category(object_id, data)
        if category == "C__CATG__APPLICATION" and data.get("application"):
            return await self.save_application_assignment(object_id, data)
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
                retry_data = {field: value}
                # Several i-doit categories validate mandatory fields even
                # while updating one property. Preserve a supplied title on
                # every field-level retry instead of sending incomplete rows.
                if field != "title" and data.get("title") not in (None, ""):
                    retry_data["title"] = data["title"]
                if category in {"C__CATG__APPLICATION", "C__CATG__OPERATING_SYSTEM"} and field != "application" and data.get("application"):
                    retry_data["application"] = data["application"]
                try:
                    saved[field] = await self.save_category(object_id, category, retry_data, entry_id)
                    if not entry_id and category in {"C__CATG__APPLICATION", "C__CATG__OPERATING_SYSTEM", "C__CATG__CPU"}:
                        entry_id = await self.find_reusable_category_entry(object_id, category, data)
                        if not entry_id:
                            break  # Do not create additional partial rows.
                except IdoitConnectionError as field_error:
                    failed[field] = field_error.to_detail()
            if not saved:
                optional_fields = OPTIONAL_IDOIT_CATEGORY_FIELDS.get(category, set())
                if failed and all(field in optional_fields for field in failed):
                    response = {"status": "skipped_optional", "ignored_fields": sorted(failed.keys()), "ignored_field_errors": failed}
                    if entry_id:
                        response["entry_id"] = entry_id
                    return response
                response = {
                    "status": "failed",
                    "failed_fields": failed,
                    "error": full_error.to_detail(),
                }
                if entry_id:
                    response["entry_id"] = entry_id
                return response
            optional_fields = OPTIONAL_IDOIT_CATEGORY_FIELDS.get(category, set())
            ignored = {field: error for field, error in failed.items() if field in optional_fields}
            warning_failed = {field: error for field, error in failed.items() if field not in optional_fields}
            response = {"status": "partial", "saved_fields": sorted(saved.keys()), "failed_fields": warning_failed}
            if ignored:
                response["ignored_fields"] = sorted(ignored.keys())
                response["ignored_field_errors"] = ignored
            if entry_id:
                response["entry_id"] = entry_id
            return response

    async def save_application_assignment(self, object_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create the relationship independently of optional version/description."""
        category = "C__CATG__APPLICATION"
        link = {"application": data["application"]}
        metadata = {k: v for k, v in data.items() if k != "application"}
        try:
            entry_id = await self.find_reusable_category_entry(object_id, category, link)
            if not entry_id:
                result = await self.save_category(object_id, category, link)
                entry_id = await self.find_reusable_category_entry(object_id, category, link)
                if not entry_id:
                    return {"status": "verification_failed", "result": result}
            else:
                result = {"already_linked": True}
        except IdoitConnectionError as exc:
            return {"status": "failed", "error": exc.to_detail()}
        failed = {}
        for field, value in metadata.items():
            try:
                await self.save_category(object_id, category, {field: value}, entry_id)
            except IdoitConnectionError as exc:
                failed[field] = exc.to_detail()
        try:
            verified = await self.find_reusable_category_entry(object_id, category, link)
        except IdoitConnectionError:
            verified = None
        if verified != entry_id:
            return {"status": "verification_failed", "result": result}
        if failed:
            return {"status": "partial", "entry_id": entry_id, "failed_fields": failed,
                    "saved_fields": ["application", *[f for f in metadata if f not in failed]]}
        return {"status": "saved", "entry_id": entry_id, "verified_entry_id": verified, "result": result}

    async def save_drive_category(self, object_id: str, data: dict[str, Any]) -> dict[str, Any]:
        # One full write per disk. Never retry individual fields without a
        # proven entry ID; a partial create could otherwise add/overwrite rows.
        category = "C__CATG__DRIVE"
        try:
            if not (_drive_serial(data.get("serial")) or _normalized_match_text(data.get("mount_point"))
                    or " [lanlens disk: " in _normalized_match_text(data.get("title"))):
                raise IdoitConnectionError("Drive has no usable identity", stage="category_match")
            entry_id = await self.find_reusable_category_entry(object_id, category, data)
            result = await self.save_category(object_id, category, data, entry_id)
        except IdoitConnectionError as exc:
            return {"status": "failed", "error": exc.to_detail()}
        try:
            verified = await self.find_reusable_category_entry(object_id, category, data)
        except IdoitConnectionError:
            verified = None
        if not verified or (entry_id and entry_id != verified):
            return {"status": "verification_failed", "result": result}
        return {"status": "saved", "result": result, "entry_id": verified,
                "action": "updated" if entry_id else "created"}

    async def find_reusable_category_entry(self, object_id: str, category: str, data: dict[str, Any]) -> Optional[str]:
        if category not in MULTIVALUE_CATEGORY_MATCH_FIELDS and category not in COMPOSITE_MULTIVALUE_CATEGORY_MATCH_FIELDS:
            return None
        try:
            result = await self.read_category(object_id, category)
        except IdoitConnectionError:
            # A failed read cannot establish that an existing software assignment
            # is absent. Propagate it rather than appending duplicate links.
            if category in {"C__CATG__OPERATING_SYSTEM", "C__CATG__APPLICATION", "C__CATG__CPU", "C__CATG__DRIVE"}:
                raise
            return None
        entries = _category_entries(result)
        if not entries:
            return None
        if category == "C__CATG__DRIVE":
            return _drive_match_id(entries, data)
        composite_fields = COMPOSITE_MULTIVALUE_CATEGORY_MATCH_FIELDS.get(category)
        if composite_fields:
            expected_values = {
                field: _plain_category_value(data.get(field))
                for field in composite_fields
            }
            if all(value not in (None, "") for value in expected_values.values()):
                for entry in entries:
                    if all(
                        str(_plain_category_value(entry.get(field)) or "").strip().lower()
                        == str(expected).strip().lower()
                        for field, expected in expected_values.items()
                    ):
                        return _category_entry_id(entry)
            return None
        if category == "C__CATG__CPU":
            # Reuse the unique existing CPU even if an older sync stored its
            # model in a structured JSON description instead of the title.
            expected = _normalized_match_text(data.get("title") or data.get("type"))
            if not expected:
                return None
            matches = set()
            for entry in entries:
                status = str(_plain_category_value(entry.get("status")) or "")
                if status and status not in ("2", "C__RECORD_STATUS__NORMAL"):
                    continue
                legacy = _decode_finding_value(_plain_category_value(entry.get("description")))
                if isinstance(legacy, list) and len(legacy) == 1:
                    legacy = legacy[0]
                legacy_title = (legacy.get("Name") or legacy.get("name") or legacy.get("ModelName")
                                or legacy.get("model_name")) if isinstance(legacy, dict) else None
                identities = [entry.get("title"), entry.get("type"), legacy_title]
                if any(_normalized_match_text(value) == expected for value in identities):
                    if entry_id := _category_entry_id(entry):
                        matches.add(entry_id)
            if len(matches) > 1:
                raise IdoitConnectionError("Multiple CPU entries match; refusing to overwrite an ambiguous entry",
                                           stage="category_match", endpoint=self.endpoint)
            return next(iter(matches), None)
        match_fields = MULTIVALUE_CATEGORY_MATCH_FIELDS[category]
        for field in match_fields:
            expected = _plain_category_value(data.get(field))
            if expected in (None, ""):
                continue
            for entry in entries:
                if field == "application":
                    expected_reference = _object_reference_id(data.get(field))
                    current_reference = _object_reference_id(entry.get(field))
                    if expected_reference and current_reference == expected_reference:
                        return _category_entry_id(entry)
                    continue
                current = _plain_category_value(entry.get(field))
                if current not in (None, "") and str(current).strip().lower() == str(expected).strip().lower():
                    return _category_entry_id(entry)
        # LanLens manages one discovered MAC/IP identity per object. If i-doit
        # already has an identity entry but its value changed, update that entry
        # instead of appending a duplicate. Inventory categories must never use
        # this fallback because each port/certificate/hardware row is distinct.
        if category in FIRST_ENTRY_REUSE_CATEGORIES:
            return _category_entry_id(entries[0])
        return None

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
        try:
            login_result = await self.login()
            return {
                "ok": True,
                "endpoint": self.endpoint,
                "authenticated": bool(self._session_id),
                "session_received": bool(login_result),
                "message": "i-doit JSON-RPC login succeeded",
            }
        finally:
            await self.logout_best_effort()


_SINGLE_VALUE_CATEGORIES = {"C__CATG__GLOBAL", "C__CATG__MODEL", "C__CATG__ACCOUNTING"}


def _category_identity_key(category, data):
    def text(field):
        return _normalized_match_text(data.get(field))
    if category in ("C__CATG__APPLICATION", "C__CATG__OPERATING_SYSTEM"):
        oid = _object_reference_id(data.get("application"))
        return (oid, text("assigned_version")) if oid and category == "C__CATG__APPLICATION" else (oid,) if oid else None
    if category == "C__CATG__DRIVE":
        serial = _drive_serial(data.get("serial")).casefold()
        return ("serial", serial) if serial else ("mount", text("mount_point")) if text("mount_point") else ("title", text("title")) if " [lanlens disk: " in text("title") else None
    if category == "C__CATG__MEMORY":
        title = text("title")
        marker = re.search(r"\[lanlens memory: (.+)\]$", title)
        return ("module", marker.group(1)) if marker else ("aggregate", title) if title == "system memory" else None
    if category == "C__CATG__CPU":
        return (text("title") or text("type"),) if text("title") or text("type") else None
    if category == "C__CATG__CERTIFICATE":
        serial = _drive_serial(data.get("serial") or data.get("serial_number")).casefold()
        return ("serial", serial) if serial else ("certificate", text("common_name"), text("expire_date")[:10]) if text("common_name") and text("expire_date") else None
    if category == "C__CATG__NET_CONNECTIONS_FOLDER":
        values = tuple(text(k) for k in ("port_from", "port_to", "protocol"))
        return values if all(values) else None
    if category == "C__CATG__NETWORK_PORT":
        mac = _normalized_match_mac(data.get("mac"))
        return ("mac", mac) if mac else ("title", text("title")) if text("title") else None
    if category == "C__CATG__IP":
        return ("ip", text("ipv4_address")) if text("ipv4_address") else ("hostname", text("hostname")) if text("hostname") else None
    if category in _SINGLE_VALUE_CATEGORIES:
        return ("singleton",)
    return ("title", text("title")) if text("title") else None


def _matching_category_rows(category, rows, data, key):
    if category == "C__CATG__DRIVE":
        entry_id = _drive_match_id(rows, data)
        return [row for row in rows if _category_entry_id(row) == entry_id] if entry_id else []
    if category == "C__CATG__CPU":
        matches = []
        for row in rows:
            legacy = _decode_finding_value(_plain_category_value(row.get("description")))
            if isinstance(legacy, list) and len(legacy) == 1:
                legacy = legacy[0]
            legacy_title = (legacy.get("Name") or legacy.get("name") or legacy.get("ModelName") or legacy.get("model_name")) if isinstance(legacy, dict) else None
            if any(_normalized_match_text(value) == key[0] for value in (row.get("title"), row.get("type"), legacy_title)):
                matches.append(row)
        return matches
    if category == "C__CATG__IP":
        # Reuse an explicit hostname identity only when there is no conflicting IP.
        exact = [row for row in rows if _category_identity_key(category, row) == key]
        return exact
    return [row for row in rows if _category_identity_key(category, row) == key]


def _category_value_equal(field, current, expected):
    if field == "application":
        return _object_reference_id(current) == _object_reference_id(expected)
    if field == "mac":
        return _normalized_match_mac(current) == _normalized_match_mac(expected)
    # i-doit returns IDs/status and numbers as strings, dialogs as objects.
    def scalar(value):
        if value is None:
            return ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(float(value))
        return str(value).strip()
    choices = [current] if not isinstance(current, dict) else [current.get(k) for k in ("value", "title", "name", "const", "id") if current.get(k) is not None]
    want = scalar(_plain_category_value(expected))
    for value in choices:
        if scalar(value) == want:
            return True
        if field in {"capacity", "unit", "quantity", "cores", "frequency", "frequency_unit", "port_from", "port_to"}:
            try:
                if float(value) == float(want):
                    return True
            except (ValueError, TypeError):
                pass
        if field == "expire_date" and scalar(value)[:10] == want[:10]:
            return True
    return False


def _category_payloads(fields: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    categories: dict[str, Any] = {}
    direct: dict[str, Any] = {}
    for target, value in fields.items():
        if not isinstance(target, str) or value is None:
            continue
        if "." not in target:
            if target.startswith("C__CAT") and isinstance(value, list) and all(isinstance(item, dict) for item in value):
                existing = categories.setdefault(target, [])
                if isinstance(existing, list):
                    existing.extend(value)
                continue
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


async def sync_device_to_idoit(db: Session, device: Device, mode: str = "manual", skip_unchanged: bool = False, _stale_retry: bool = False, _application_run: Optional[dict] = None) -> dict[str, Any]:
    config = get_config(db)
    if not config.enabled:
        raise IdoitConnectionError("i-doit integration is disabled", stage="configuration", endpoint=build_jsonrpc_endpoint(config.base_url, config.jsonrpc_path))
    if mode != "manual" and not device.idoit_sync_enabled:
        state = get_or_create_state(db, device)
        state.last_mode = mode
        state.last_validation_at = datetime.utcnow()
        state.status = "skipped"
        state.last_error = "i-doit sync is disabled for this device"
        log_sync(db, device.id, mode, "skipped", "i-doit sync skipped; disabled for this device", {"upstream_write_performed": False}, state.idoit_object_id)
        db.commit()
        return {"device_id": device.id, "status": state.status, "idoit_object_id": state.idoit_object_id, "upstream_write_performed": False, "skipped": True, "skip_reason": "device_disabled"}
    errors = validate_mapping(config.mapping, config.sync_status_field, config.default_object_type, config.mapping_error)
    payload = device_payload(device, config, db)
    state = get_or_create_state(db, device)
    state.last_mode = mode
    state.last_validation_at = datetime.utcnow()
    digest = payload_hash(payload)
    previous_hash = state.payload_hash
    state.payload_hash = digest
    if errors:
        state.status = "mapping_error"
        state.last_error = "; ".join(errors)
        log_sync(db, device.id, mode, "failure", "i-doit mapping validation failed", {"payload": payload, "errors": errors, "upstream_write_performed": False}, state.idoit_object_id)
        db.commit()
        return {"device_id": device.id, "status": state.status, "errors": errors, "payload_hash": digest, "upstream_write_performed": False}

    # get_or_create_state() flushes a new row. Commit before any remote i-doit
    # calls so SQLite does not hold a write lock for the duration of network
    # requests and block unrelated UI/API writes.
    db.commit()

    client = IdoitClient(config)
    if hasattr(client, "reconcile_category"):
        client.category_snapshot = {}
    application_run = _application_run if _application_run is not None else {}
    if application_run.get("catalog") is not None and hasattr(client, "_application_catalog"):
        client._application_catalog = application_run["catalog"]
        client._application_catalog_complete = application_run["complete"]
        client.application_lookup_debug = application_run["debug"]
    application_cache = application_run.setdefault("resolutions", {})
    details: dict[str, Any] = {"payload": payload, "upstream_write_performed": False, "category_results": {}, "category_save_counts": {}}
    try:
        await client.login()
        object_id = state.idoit_object_id
        action = "update" if object_id else "create"
        if object_id:
            try:
                await client.read_object(object_id)
            except IdoitConnectionError as exc:
                if not _is_missing_object_error(exc):
                    raise
                details["stale_object_link"] = {
                    "old_idoit_object_id": object_id,
                    "reason": "Linked i-doit object no longer exists; clearing local link and recreating/relinking on this sync.",
                }
                state.idoit_object_id = None
                state.idoit_sysid = None
                object_id = None
                action = "recreate_missing"
                db.commit()
        if skip_unchanged and state.status == "synced" and object_id and previous_hash == digest:
            log_sync(db, device.id, mode, "skipped", "i-doit sync skipped; payload unchanged", {"payload_hash": digest, "upstream_write_performed": False}, object_id)
            db.commit()
            return {"device_id": device.id, "status": state.status, "idoit_object_id": object_id, "payload_hash": digest, "upstream_write_performed": False, "skipped": True}
        if object_id:
            current_type_title = await client.object_type_title(object_id)
            desired_type = payload["objectType"]
            if desired_type != "C__OBJTYPE__SERVER" and "server" in current_type_title.lower():
                # Never create another i-doit object just because the current
                # linked object has the wrong type. That produced duplicates in
                # real sync runs. Keep the stable link and surface the mismatch;
                # object type cleanup must be an explicit operator action.
                action = "update_type_mismatch"
                details["object_type_mismatch"] = {
                    "current_type_title": current_type_title,
                    "desired_type": desired_type,
                    "resolution": "Kept existing linked i-doit object to avoid duplicates; change/relink the object type manually if required.",
                }
                await client.update_object_title(object_id, payload["title"])
            else:
                await client.update_object_title(object_id, payload["title"])
        else:
            match = await client.find_existing_object(payload)
            details["identity_match"] = getattr(client, "last_identity_match_debug", {"result": match})
            object_id = match.get("object_id") if match else None
            if object_id:
                try:
                    await client.read_object(object_id)
                    action = "link_existing"
                    details["link_reason"] = "Local sync state had no i-doit object id; reused an existing i-doit object from identity matching instead of creating a duplicate."
                    details["match"] = match
                except IdoitConnectionError as exc:
                    if not _is_missing_object_error(exc):
                        raise
                    details["ignored_stale_identity_match"] = {
                        "idoit_object_id": object_id,
                        "reason": "Identity lookup returned an object id that i-doit no longer accepts as existing; creating a fresh object instead.",
                    }
                    object_id = None
            if not object_id:
                if config.create_policy != "create_missing":
                    state.status = "match_required"
                    state.last_error = "No confident existing i-doit match found; create policy is match-only"
                    log_sync(
                        db,
                        device.id,
                        mode,
                        "skipped",
                        "i-doit sync skipped; no confident existing object match and create policy is match-only",
                        {
                            **details,
                            "payload_hash": digest,
                            "match_required": True,
                            "create_policy": config.create_policy,
                            "upstream_write_performed": False,
                        },
                        None,
                    )
                    db.commit()
                    return {
                        "device_id": device.id,
                        "status": state.status,
                        "payload_hash": digest,
                        "upstream_write_performed": False,
                        "skipped": True,
                        "skip_reason": "match_required",
                    }
                object_id = await client.create_object(payload["title"], payload["objectType"])
                action = "create"
            state.idoit_object_id = object_id
            # Persist the upstream object link immediately. If a later category
            # save fails or the request is interrupted, the next sync must update
            # this object instead of creating another duplicate.
            db.commit()

        categories, direct_fields = _category_payloads(payload.get("fields") if isinstance(payload.get("fields"), dict) else {})
        if direct_fields:
            details["direct_fields_skipped"] = direct_fields
        sync_warnings: list[str] = []
        log_only_warnings: list[str] = []
        operating_system = payload.get("operatingSystem") if isinstance(payload.get("operatingSystem"), dict) else None
        if operating_system and operating_system.get("title"):
            os_resolution = await client.resolve_operating_system(
                str(operating_system["title"]),
                create_missing=config.create_policy == "create_missing",
            )
            details["operating_system"] = os_resolution
            os_object_id = os_resolution.get("object_id")
            if os_object_id:
                os_entry: dict[str, Any] = {"application": _object_id_as_int(os_object_id)}
                for field in ("assigned_version", "description"):
                    if operating_system.get(field) not in (None, ""):
                        os_entry[field] = operating_system[field]
                categories["C__CATG__OPERATING_SYSTEM"] = [os_entry]
            else:
                sync_warnings.append(
                    "C__CATG__OPERATING_SYSTEM: no unique Operating System object match; "
                    "enable create-missing or create the OS object in i-doit"
                )
        applications = list(payload.get("applications") or []) if isinstance(payload.get("applications"), list) else []
        # Container summaries are not assignments. Resolve titles before including them.
        mapped_apps = categories.pop("C__CATG__APPLICATION", [])
        for entry in (mapped_apps if isinstance(mapped_apps, list) else [mapped_apps]):
            if not isinstance(entry, dict):
                continue
            if entry.get("application"):
                categories.setdefault("C__CATG__APPLICATION", []).append(entry)
            elif entry.get("title"):
                applications.append({"title": entry["title"], "description": "LanLens container discovery", "container": True})
        details["detected_application_count"] = len(applications)
        application_entries: list[dict[str, Any]] = []
        application_details: list[dict[str, Any]] = []
        unmatched_application_titles: list[str] = []
        for application in applications:
            if not isinstance(application, dict) or not application.get("title"):
                continue
            title = str(application["title"])
            allow_create = config.create_policy == "create_missing" and not application.get("container")
            cache_key = (_normalized_match_text(title), allow_create)
            if cache_key not in application_cache:
                application_cache[cache_key] = await client.resolve_application(title, create_missing=allow_create)
            resolution = application_cache[cache_key]
            application_details.append(resolution)
            application_id = resolution.get("object_id")
            if application_id:
                assignment: dict[str, Any] = {"application": _object_id_as_int(application_id)}
                for field in ("assigned_version", "description"):
                    if application.get(field) not in (None, ""):
                        assignment[field] = application[field]
                application_entries.append(assignment)
            else:
                unmatched_application_titles.append(str(application["title"]))
        if application_entries:
            existing_applications = categories.get("C__CATG__APPLICATION")
            existing_entries = existing_applications if isinstance(existing_applications, list) else ([existing_applications] if isinstance(existing_applications, dict) else [])
            categories["C__CATG__APPLICATION"] = [*existing_entries, *application_entries]
        if getattr(client, "_application_catalog", None) is not None:
            application_run.update(catalog=client._application_catalog, complete=client._application_catalog_complete, debug=client.application_lookup_debug)
        if application_details:
            details["applications"] = application_details
            counts: dict[str, int] = {}
            for resolution in application_details:
                reason = str(resolution.get("action", "unknown"))
                counts[reason] = counts.get(reason, 0) + 1
            details["application_resolution_counts"] = counts
            details["application_lookup"] = {
                "create_policy": config.create_policy,
                "matching_revision": 3,
                "build_commit": BUILD_COMMIT,
                **getattr(client, "application_lookup_debug", {}),
                "unmatched_examples": [{"title": title, "candidates": _application_title_candidates(title)}
                                       for title in unmatched_application_titles[:5]],
            }
        if unmatched_application_titles:
            preview = ", ".join(repr(title) for title in unmatched_application_titles[:5])
            remainder = max(0, len(unmatched_application_titles) - 5)
            if remainder:
                preview = f"{preview}, and {remainder} more"
            log_only_warnings.append(
                "C__CATG__APPLICATION: "
                f"{len(unmatched_application_titles)} installed application(s) have no unique i-doit Application object match "
                f"({preview}); resolution: {details['application_resolution_counts']}; "
                f"policy: {config.create_policy}. Inspect application_lookup in the sync log before creating objects."
            )
        if any(item.get("action") == "lookup_incomplete" for item in application_details):
            sync_warnings.append("C__CATG__APPLICATION: application catalog lookup incomplete; see sync log")
        global_category = categories.get("C__CATG__GLOBAL") if isinstance(categories.get("C__CATG__GLOBAL"), dict) else {}
        if global_category.get("description") is None:
            if hasattr(client, "reconcile_category"):
                categories.setdefault("C__CATG__GLOBAL", {})
            else:
                cleaned_description = await client.cleanup_lanlens_global_description(object_id)
                if cleaned_description is not None:
                    details["global_description_cleanup"] = "removed previous LanLens inventory/reference dump"
        if global_category.get("cmdb_status") == "C__CMDB_STATUS__OUT_OF_OPERATION":
            global_category["cmdb_status"] = await client.out_of_operation_status_id()
            details["offline_retirement_applied"] = True
        for category, data in categories.items():
            entries = data if isinstance(data, list) else [data]
            valid_entries = [entry for entry in entries if isinstance(entry, dict) and entry]
            if hasattr(client, "reconcile_category"):
                category_results = await client.reconcile_category(object_id, category, valid_entries,
                    clean_global=category == "C__CATG__GLOBAL" and global_category.get("description") is None)
            else:
                category_results = [await client.save_category_best_effort(object_id, category, entry) for entry in valid_entries]
            for result in category_results:
                if result.get("status") == "ambiguous":
                    sync_warnings.append(f"{category}: ambiguous identity; no write performed")
                elif result.get("status") == "partial":
                    failed = result.get("failed_fields") if isinstance(result.get("failed_fields"), dict) else {}
                    if failed:
                        sync_warnings.append(f"{category}: partial save; rejected fields: {', '.join(sorted(failed.keys()))}")
                elif result.get("status") == "verification_failed":
                    sync_warnings.append(f"{category}: save reported success but category entry could not be verified by reading the host category")
                elif result.get("status") == "failed":
                    failed = result.get("failed_fields") if isinstance(result.get("failed_fields"), dict) else {}
                    rejected = ", ".join(sorted(failed.keys())) if failed else "category payload"
                    error = result.get("error") or {}
                    reason = error.get("message") if isinstance(error, dict) else None
                    sync_warnings.append(f"{category}: {result.get('reason', 'save rejected by i-doit')}; rejected fields: {rejected}" + (f"; {reason}" if category == "C__CATG__DRIVE" and reason else ""))
            details["category_results"][category] = category_results if isinstance(data, list) else (category_results[0] if category_results else {"status": "skipped_empty"})
            counts = Counter(str(result.get("status", "failed")) for result in category_results)
            details["category_save_counts"][category] = {key: counts[key] for key in ("created", "updated", "unchanged", "ambiguous", "failed")}
            if category in {"C__CATG__APPLICATION", "C__CATG__DRIVE"}:
                details["drive_save_counts" if category == "C__CATG__DRIVE" else "application_save_counts"] = dict(counts)

        sysid = await client.object_sysid(object_id)
        if sysid:
            state.idoit_sysid = sysid
            details["idoit_sysid"] = sysid

        # Persist the successful CMDB link before optional VMware network I/O.
        db.commit()
        if sysid:
            try:
                writeback = await writeback_idoit_sysid(db, device.id, sysid)
                if writeback:
                    details["vsphere_sysid_writeback"] = writeback
            except Exception:
                db.rollback()
                sync_warnings.append("VMware SYSID custom attribute writeback failed; check VM identity, selected attribute, existing value and permissions")
                details["vsphere_sysid_writeback"] = "failed"

        now = datetime.utcnow()
        state.status = "synced_with_warnings" if sync_warnings or log_only_warnings else "synced"
        state.last_sync_at = now
        state.last_success_at = now
        state.last_error = None
        details["upstream_write_performed"] = True
        details["action"] = action
        if sync_warnings or log_only_warnings:
            details["warnings"] = [*sync_warnings, *log_only_warnings]
        if sync_warnings:
            state.last_error = "; ".join(sync_warnings)
        log_sync(db, device.id, mode, "success", f"i-doit {action} completed", details, object_id)
        db.commit()
        return {"device_id": device.id, "status": state.status, "action": action, "idoit_object_id": object_id, "idoit_sysid": state.idoit_sysid, "payload_hash": digest, "upstream_write_performed": True, "warnings": sync_warnings}
    except IdoitConnectionError as exc:
        if _is_missing_object_error(exc) and not _stale_retry:
            stale_object_id = state.idoit_object_id
            state.idoit_object_id = None
            state.idoit_sysid = None
            state.status = "recreate_pending"
            state.last_error = "Linked i-doit object vanished during sync; retrying with a fresh object link"
            log_sync(
                db,
                device.id,
                mode,
                "skipped",
                "i-doit object vanished during sync; cleared local link and retrying",
                {**details, "stale_object_id": stale_object_id, "retry": "recreate_missing_object"},
                stale_object_id,
            )
            db.commit()
            logout = getattr(client, "logout_best_effort", None)
            if logout:
                await logout()
            return await sync_device_to_idoit(db, device, mode=mode, skip_unchanged=False, _stale_retry=True, _application_run=application_run)
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
    finally:
        logout = getattr(client, "logout_best_effort", None)
        if logout:
            await logout()


async def sync_all_registered_devices_to_idoit(db: Session, mode: str = "manual", skip_unchanged: bool = False, on_progress=None) -> dict[str, Any]:
    query = db.query(Device).filter(Device.is_registered == True)  # noqa: E712
    config = get_config(db)
    if config.sync_scope == "manual":
        query = query.filter(Device.idoit_sync_enabled == True)  # noqa: E712
    devices = query.all()
    summary: dict[str, Any] = {
        "total": len(devices),
        "success": 0,
        "failure": 0,
        "skipped": 0,
        "results": [],
    }
    application_run: dict = {}
    if on_progress:
        on_progress(summary)
    for device in devices:
        try:
            result = await sync_device_to_idoit(db, device, mode=mode, skip_unchanged=skip_unchanged, _application_run=application_run)
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
        if on_progress:
            on_progress(summary)
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
