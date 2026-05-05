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


def build_jsonrpc_endpoint(base_url: str, jsonrpc_path: str = "/src/jsonrpc.php") -> str:
    """Build the i-doit JSON-RPC endpoint for Cloud and on-prem installs.

    Cloud and on-prem both speak JSON-RPC, but on-prem deployments often sit
    behind a reverse proxy or custom sub-path. If base_url already points to
    jsonrpc.php, keep it as-is; otherwise append the configured path.
    """
    base = (base_url or "").rstrip("/")
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


def validate_mapping(
    mapping: dict[str, Any],
    sync_status_field: Optional[str] = None,
    default_object_type: Optional[str] = None,
    mapping_error: Optional[str] = None,
) -> list[str]:
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
    identity = mapping.get("identity") or {}
    configured_status = sync_status_field or identity.get("syncStatusField")
    if not configured_status:
        errors.append("A writable i-doit sync/reference/status field must be configured")
    return errors


def device_payload(device: Device, config: IdoitConfig) -> dict[str, Any]:
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
    for lanlens_field, idoit_field in (config.mapping.get("fields") or {}).items():
        if idoit_field and source.get(lanlens_field) is not None:
            fields[idoit_field] = source[lanlens_field]
    sync_reference = f"LanLens sync reference: {device.cmdb_id or device.mac_address}"
    if fields.get(config.sync_status_field):
        fields[config.sync_status_field] = f"{fields[config.sync_status_field]}\n{sync_reference}"
    else:
        fields[config.sync_status_field] = sync_reference
    return {
        "objectType": config.mapping.get("objectType") or config.default_object_type,
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
    state = db.query(IdoitDeviceSync).filter(IdoitDeviceSync.device_id == device.id).first()
    if not state:
        state = IdoitDeviceSync(device_id=device.id, status="never_synced")
        db.add(state)
        db.flush()
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
        body = {"version": "2.0", "method": method, "params": params or {}, "id": 1}
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
    config = get_config(db)
    errors = validate_mapping(config.mapping, config.sync_status_field, config.default_object_type, config.mapping_error)
    payload = device_payload(device, config)
    state = get_or_create_state(db, device)
    digest = payload_hash(payload)
    action = "update" if state.idoit_object_id else "unresolved"
    warnings = []
    if not device.cmdb_id:
        warnings.append("Device has no LanLens CMDB ID; matching will fall back to MAC/hostname/IP")
    if not state.idoit_object_id:
        warnings.append("No stored i-doit object id yet; dry-run does not query i-doit, so create/update is unresolved until live matching is enabled")
    if errors:
        state.status = "mapping_error"
        state.last_error = "; ".join(errors)
    else:
        state.last_error = None
        state.status = "pending_changes" if state.payload_hash and state.payload_hash != digest else "preview_ready"
    log_sync(db, device.id, "dry_run", "failure" if errors else "success", "Dry run generated", {"payload": payload, "errors": errors, "warnings": warnings, "action": action})
    db.commit()
    return {"device_id": device.id, "action": action, "payload_hash": digest, "payload": payload, "errors": errors, "warnings": warnings, "idoit_object_id": state.idoit_object_id}


def mark_manual_sync_placeholder(db: Session, device: Device) -> dict[str, Any]:
    """Persist sync state after LanLens-side validation.

    Real i-doit object create/update is intentionally kept behind live API wiring;
    this gives users a safe first v1.5.0 baseline with config, validation, dry-run,
    sync status and audit logging before credentials are available.
    """
    config = get_config(db)
    payload = device_payload(device, config)
    errors = validate_mapping(config.mapping, config.sync_status_field, config.default_object_type, config.mapping_error)
    state = get_or_create_state(db, device)
    now = datetime.utcnow()
    state.last_sync_at = now
    state.last_mode = "manual"
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
