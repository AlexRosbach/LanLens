"""i-doit one-way sync helpers.

The i-doit Cloud and on-prem products expose the same JSON-RPC API shape for
LanLens' use case: URL + API key login, then object/category calls with the
returned session token. Cloud-specific differences should stay in configuration
(base URL, key, permissions), not in sync logic.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Device, IdoitDeviceSync, IdoitSyncLog, Setting

DEFAULT_MAPPING = {
    "name": "Default i-doit mapping",
    "version": 1,
    "objectType": "C__OBJTYPE__SERVER",
    "identity": {
        "externalIdField": "C__CATG__GLOBAL.description",
        "syncStatusField": "C__CATG__GLOBAL.comment",
        "fallback": ["mac_address", "hostname", "ip_address"],
    },
    "fields": {
        "label": "title",
        "ip_address": "C__CATG__IP.ADDRESS",
        "mac_address": "C__CATG__NETWORK_PORT.MAC",
        "device_class": "C__CATG__MODEL.TYPE",
        "hostname": "C__CATG__GLOBAL.title",
        "cmdb_id": "C__CATG__GLOBAL.description",
    },
}

SETTING_DEFAULTS = {
    "idoit_enabled": "false",
    "idoit_base_url": "",
    "idoit_jsonrpc_path": "/src/jsonrpc.php",
    "idoit_api_key": "",
    "idoit_timeout_seconds": "15",
    "idoit_default_object_type": "C__OBJTYPE__SERVER",
    "idoit_auto_sync_enabled": "false",
    "idoit_sync_status_field": "C__CATG__GLOBAL.comment",
    "idoit_mapping_json": json.dumps(DEFAULT_MAPPING, indent=2),
}


@dataclass
class IdoitConfig:
    enabled: bool
    base_url: str
    jsonrpc_path: str
    api_key: str
    timeout_seconds: int
    default_object_type: str
    auto_sync_enabled: bool
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
    base = (base_url or "").rstrip("/")
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
    try:
        timeout = max(3, min(120, int(_get_setting(db, "idoit_timeout_seconds") or "15")))
    except ValueError:
        timeout = 15
    return IdoitConfig(
        enabled=_get_setting(db, "idoit_enabled") == "true",
        base_url=(_get_setting(db, "idoit_base_url") or "").rstrip("/"),
        jsonrpc_path=_get_setting(db, "idoit_jsonrpc_path") or "/src/jsonrpc.php",
        api_key=_get_setting(db, "idoit_api_key"),
        timeout_seconds=timeout,
        default_object_type=_get_setting(db, "idoit_default_object_type") or "C__OBJTYPE__SERVER",
        auto_sync_enabled=_get_setting(db, "idoit_auto_sync_enabled") == "true",
        sync_status_field=_get_setting(db, "idoit_sync_status_field") or "C__CATG__GLOBAL.comment",
        mapping=mapping,
        mapping_error=mapping_error,
        mapping_raw=raw_mapping,
    )


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
    return {column.name for column in Device.__table__.columns}


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
        if invalid_targets := [name for name, target in fields.items() if not isinstance(target, str) or not target.strip()]:
            errors.append(f"Mapping field targets must be non-empty strings: {', '.join(invalid_targets)}")
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
        return config.sync_status_field.strip()
    identity_status = _mapping_identity(config).get("syncStatusField")
    if isinstance(identity_status, str) and identity_status.strip():
        return identity_status.strip()
    return "C__CATG__GLOBAL.comment"


def _json_safe_device_value(device: Device, field_name: str) -> Any:
    if field_name not in _allowed_device_mapping_fields():
        return None
    value = getattr(device, field_name, None)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def device_payload(device: Device, config: IdoitConfig) -> dict[str, Any]:
    # Build the future i-doit write payload without contacting i-doit. Dry-run
    # and placeholder sync both use this so operators can inspect exactly what
    # would be sent once live upstream writes are enabled.
    label = device.label or device.hostname or device.cmdb_id or device.ip_address or device.mac_address
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
    }
    fields = {}
    for lanlens_field, idoit_field in _mapping_fields(config).items():
        if not isinstance(idoit_field, str) or not idoit_field.strip():
            continue
        if lanlens_field in source:
            value = source[lanlens_field]
        else:
            value = _json_safe_device_value(device, lanlens_field)
        if value is not None:
            fields[idoit_field] = value
    external_id_field = _mapping_identity(config).get("externalIdField")
    external_id_value = device.cmdb_id or device.mac_address
    if isinstance(external_id_field, str) and external_id_field.strip() and external_id_value and not fields.get(external_id_field):
        fields[external_id_field] = external_id_value

    # Store a human-readable LanLens reference in a dedicated/comment-like field.
    # If a user maps their CMDB ID to the same field, append instead of replacing
    # so duplicate-prevention identifiers are not lost.
    sync_reference = f"LanLens sync reference: {device.cmdb_id or device.mac_address}"
    sync_status_field = _sync_status_field(config)
    if fields.get(sync_status_field):
        fields[sync_status_field] = f"{fields[sync_status_field]}\n{sync_reference}"
    else:
        fields[sync_status_field] = sync_reference
    return {
        "objectType": _mapping_dict(config).get("objectType") or config.default_object_type,
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


def log_sync(db: Session, device_id: Optional[int], mode: str, result: str, message: str, details: Optional[dict[str, Any]] = None, object_id: Optional[str] = None) -> IdoitSyncLog:
    row = IdoitSyncLog(
        device_id=device_id,
        mode=mode,
        result=result,
        idoit_object_id=object_id,
        message=message,
        details_json=json.dumps(details or {}, default=str),
    )
    db.add(row)
    return row


class IdoitClient:
    def __init__(self, config: IdoitConfig):
        self.config = config
        self.endpoint = build_jsonrpc_endpoint(config.base_url, config.jsonrpc_path)
        self._session_id: Optional[str] = None

    async def call(self, method: str, params: Optional[dict[str, Any]] = None) -> Any:
        headers = {"Content-Type": "application/json"}
        if self._session_id:
            headers["X-RPC-Auth-Session"] = self._session_id
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            res = await client.post(self.endpoint, headers=headers, json=body)
            res.raise_for_status()
            data = res.json()
        if data.get("error"):
            raise RuntimeError(data["error"].get("message") or str(data["error"]))
        return data.get("result")

    async def login(self) -> Any:
        result = await self.call("idoit.login", {"apikey": self.config.api_key})
        if isinstance(result, dict):
            self._session_id = result.get("session-id") or result.get("session_id")
        return result

    async def test_connection(self) -> dict[str, Any]:
        await self.login()
        return {"ok": True, "endpoint": self.endpoint, "authenticated": bool(self._session_id)}


def dry_run(db: Session, device: Device) -> dict[str, Any]:
    # Read-only preview: do not mutate sync state here. The UI uses this to show
    # payload, validation errors, and whether the local device changed since the
    # last placeholder validation.
    config = get_config(db)
    errors = validate_mapping(config.mapping, config.sync_status_field, config.default_object_type, config.mapping_error)
    payload = device_payload(device, config)
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
    payload = device_payload(device, config)
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
