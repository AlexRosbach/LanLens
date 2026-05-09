"""Generic CMDB REST integration helpers.

This module intentionally provides a connector-neutral REST foundation next to
LanLens' i-doit-specific integration. It supports three safe building blocks:

* stable CMDB-oriented inventory export from LanLens
* local payload preview/mapping validation
* explicit outbound push/import-preview calls with masked secrets and audit logs
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import CmdbSyncLog, Device, Setting
from .notification import request_json_via_validated_url

logger = logging.getLogger(__name__)

DEFAULT_MAPPING = {
    "name": "Default generic CMDB REST mapping",
    "version": 1,
    "identity": {
        "field": "mac_address",
        "fallback": ["hostname", "ip_address", "asset_tag", "cmdb_id"],
    },
    "fields": {
        "id": "lanlens_id",
        "mac_address": "mac_address",
        "ip_address": "ip_address",
        "hostname": "hostname",
        "label": "name",
        "vendor": "vendor",
        "device_class": "device_class",
        "cmdb_id": "external_id",
        "asset_tag": "asset_tag",
        "location": "location",
        "responsible": "owner",
        "purpose": "purpose",
        "description": "description",
        "is_online": "online",
        "is_registered": "registered",
        "first_seen": "first_seen",
        "last_seen": "last_seen",
    },
}

SETTING_DEFAULTS = {
    "cmdb_rest_enabled": "false",
    "cmdb_rest_target_url": "",
    "cmdb_rest_import_url": "",
    "cmdb_rest_method": "POST",
    "cmdb_rest_auth_type": "none",
    "cmdb_rest_bearer_token": "",
    "cmdb_rest_basic_username": "",
    "cmdb_rest_basic_password": "",
    "cmdb_rest_header_name": "",
    "cmdb_rest_header_value": "",
    "cmdb_rest_timeout_seconds": "15",
    "cmdb_rest_identity_field": "mac_address",
    "cmdb_rest_import_conflict_strategy": "fill_empty",
    "cmdb_rest_mapping_json": json.dumps(DEFAULT_MAPPING, indent=2),
}

SECRET_KEYS = {
    "cmdb_rest_bearer_token",
    "cmdb_rest_basic_password",
    "cmdb_rest_header_value",
}

PUSH_METHODS = {"POST", "PUT", "PATCH"}
AUTH_TYPES = {"none", "bearer", "basic", "header"}
CONFLICT_STRATEGIES = {"fill_empty", "cmdb_wins", "lanlens_wins", "manual_review"}


@dataclass
class CmdbConfig:
    enabled: bool
    target_url: str
    import_url: str
    method: str
    auth_type: str
    bearer_token: str
    basic_username: str
    basic_password: str
    header_name: str
    header_value: str
    timeout_seconds: int
    identity_field: str
    import_conflict_strategy: str
    mapping: dict[str, Any]
    mapping_raw: str
    mapping_error: Optional[str] = None


def _get_setting(db: Session, key: str) -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row and row.value is not None else SETTING_DEFAULTS.get(key, "")


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def get_config(db: Session) -> CmdbConfig:
    raw_mapping = _get_setting(db, "cmdb_rest_mapping_json") or SETTING_DEFAULTS["cmdb_rest_mapping_json"]
    mapping_error = None
    try:
        mapping = json.loads(raw_mapping)
    except Exception as exc:
        mapping = {}
        mapping_error = f"Mapping JSON is invalid: {exc}"
    try:
        timeout = max(3, min(120, int(_get_setting(db, "cmdb_rest_timeout_seconds") or "15")))
    except ValueError:
        timeout = 15
    method = (_get_setting(db, "cmdb_rest_method") or "POST").upper()
    auth_type = (_get_setting(db, "cmdb_rest_auth_type") or "none").lower()
    strategy = (_get_setting(db, "cmdb_rest_import_conflict_strategy") or "fill_empty").lower()
    return CmdbConfig(
        enabled=_get_setting(db, "cmdb_rest_enabled") == "true",
        target_url=(_get_setting(db, "cmdb_rest_target_url") or "").strip(),
        import_url=(_get_setting(db, "cmdb_rest_import_url") or "").strip(),
        method=method if method in PUSH_METHODS else "POST",
        auth_type=auth_type if auth_type in AUTH_TYPES else "none",
        bearer_token=_get_setting(db, "cmdb_rest_bearer_token"),
        basic_username=_get_setting(db, "cmdb_rest_basic_username"),
        basic_password=_get_setting(db, "cmdb_rest_basic_password"),
        header_name=_get_setting(db, "cmdb_rest_header_name"),
        header_value=_get_setting(db, "cmdb_rest_header_value"),
        timeout_seconds=timeout,
        identity_field=_get_setting(db, "cmdb_rest_identity_field") or "mac_address",
        import_conflict_strategy=strategy if strategy in CONFLICT_STRATEGIES else "fill_empty",
        mapping=mapping,
        mapping_raw=raw_mapping,
        mapping_error=mapping_error,
    )


def update_config(db: Session, payload: dict[str, Any]) -> CmdbConfig:
    for key in SETTING_DEFAULTS:
        if key not in payload:
            continue
        value = payload[key]
        if key in SECRET_KEYS and value == "••••••••":
            continue
        if key == "cmdb_rest_mapping_json" and isinstance(value, dict):
            value = json.dumps(value, indent=2)
        elif isinstance(value, bool):
            value = "true" if value else "false"
        elif value is None:
            value = ""
        if key in {"cmdb_rest_target_url", "cmdb_rest_import_url"}:
            value = str(value).strip()
        if key == "cmdb_rest_method":
            value = str(value).upper()
        if key == "cmdb_rest_auth_type" or key == "cmdb_rest_import_conflict_strategy":
            value = str(value).lower()
        _set_setting(db, key, str(value))
    db.commit()
    return get_config(db)


def allowed_device_fields() -> set[str]:
    return {column.name for column in Device.__table__.columns}


def validate_mapping(config: CmdbConfig) -> list[str]:
    errors: list[str] = []
    if config.mapping_error:
        errors.append(config.mapping_error)
    mapping = config.mapping
    if not isinstance(mapping, dict):
        return errors + ["Mapping must be a JSON object"]
    fields = mapping.get("fields")
    if not isinstance(fields, dict) or not fields:
        errors.append("Mapping requires at least one field mapping")
    else:
        allowed_sources = allowed_device_fields()
        if invalid_sources := [name for name in fields if name not in allowed_sources]:
            errors.append(f"Mapping source fields are not supported Device columns: {', '.join(invalid_sources)}")
        if invalid_targets := [name for name, target in fields.items() if not isinstance(target, str) or not target.strip()]:
            errors.append(f"Mapping targets must be non-empty strings: {', '.join(invalid_targets)}")
    identity = mapping.get("identity") or {}
    if not isinstance(identity, dict):
        errors.append("Mapping identity must be a JSON object when provided")
    identity_field = config.identity_field or identity.get("field")
    if identity_field not in allowed_device_fields():
        errors.append(f"Identity field is not a supported Device column: {identity_field}")
    return errors


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def device_export(device: Device) -> dict[str, Any]:
    segment = device.segment
    return {
        "id": device.id,
        "mac_address": device.mac_address,
        "ip_address": device.ip_address,
        "hostname": device.hostname,
        "label": device.label,
        "vendor": device.vendor,
        "device_class": device.device_class,
        "cmdb_id": device.cmdb_id,
        "asset_tag": device.asset_tag,
        "purpose": device.purpose,
        "description": device.description,
        "location": device.location,
        "responsible": device.responsible,
        "os_info": device.os_info,
        "notes": device.notes,
        "is_registered": device.is_registered,
        "is_online": device.is_online,
        "first_seen": device.first_seen.isoformat() if device.first_seen else None,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        "segment": {
            "id": segment.id,
            "name": segment.name,
            "color": segment.color,
        } if segment else None,
    }


def build_payload(device: Device, config: CmdbConfig) -> dict[str, Any]:
    fields = config.mapping.get("fields") if isinstance(config.mapping, dict) else {}
    fields = fields if isinstance(fields, dict) else {}
    payload: dict[str, Any] = {}
    for source, target in fields.items():
        if source not in allowed_device_fields() or not isinstance(target, str) or not target.strip():
            continue
        payload[target.strip()] = _json_safe_value(getattr(device, source, None))
    identity_field = config.identity_field if config.identity_field in allowed_device_fields() else "mac_address"
    return {
        "source": "LanLens",
        "identity": {
            "field": identity_field,
            "value": _json_safe_value(getattr(device, identity_field, None)),
        },
        "device": payload,
        "lanlens": device_export(device),
    }


def _auth_headers(config: CmdbConfig) -> dict[str, str]:
    headers = {"User-Agent": "LanLens CMDB REST", "Content-Type": "application/json"}
    if config.auth_type == "bearer" and config.bearer_token:
        headers["Authorization"] = f"Bearer {config.bearer_token}"
    elif config.auth_type == "basic" and (config.basic_username or config.basic_password):
        token = base64.b64encode(f"{config.basic_username}:{config.basic_password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    elif config.auth_type == "header" and config.header_name and config.header_value:
        headers[config.header_name] = config.header_value
    return headers


def _safe_log_details(details: dict[str, Any]) -> str:
    return json.dumps(details, default=str, sort_keys=True)[:8000]


def log_attempt(db: Session, device_id: Optional[int], mode: str, result: str, message: str, details: Optional[dict[str, Any]] = None) -> None:
    db.add(CmdbSyncLog(
        device_id=device_id,
        mode=mode,
        result=result,
        message=message,
        details_json=_safe_log_details(details or {}),
    ))
    db.commit()


async def push_device(db: Session, device: Device, config: CmdbConfig) -> dict[str, Any]:
    errors = validate_mapping(config)
    if errors:
        log_attempt(db, device.id, "push", "failure", "CMDB mapping validation failed", {"errors": errors})
        return {"success": False, "errors": errors}
    if not config.enabled:
        log_attempt(db, device.id, "push", "skipped", "Generic CMDB REST integration is disabled")
        return {"success": False, "message": "Generic CMDB REST integration is disabled"}
    if not config.target_url:
        log_attempt(db, device.id, "push", "failure", "CMDB target URL is not configured")
        return {"success": False, "message": "CMDB target URL is not configured"}

    payload = build_payload(device, config)
    try:
        response = await request_json_via_validated_url(
            config.target_url,
            method=config.method,
            payload=payload,
            headers=_auth_headers(config),
            timeout_seconds=config.timeout_seconds,
            label="CMDB REST target URL",
        )
        success = 200 <= response.status_code < 300
        message = f"CMDB REST push returned HTTP {response.status_code}"
        log_attempt(db, device.id, "push", "success" if success else "failure", message, {"status_code": response.status_code})
        return {"success": success, "status_code": response.status_code, "message": message}
    except Exception as exc:
        log_attempt(db, device.id, "push", "failure", f"CMDB REST push failed: {exc}")
        return {"success": False, "message": f"CMDB REST push failed: {exc}"}


async def test_connection(config: CmdbConfig) -> dict[str, Any]:
    url = config.target_url or config.import_url
    if not url:
        return {"success": False, "message": "CMDB REST target/import URL is not configured"}
    try:
        response = await request_json_via_validated_url(
            url,
            method="GET",
            headers=_auth_headers(config),
            timeout_seconds=config.timeout_seconds,
            label="CMDB REST URL",
        )
        return {"success": 200 <= response.status_code < 500, "status_code": response.status_code, "message": f"CMDB REST endpoint returned HTTP {response.status_code}"}
    except Exception as exc:
        return {"success": False, "message": f"CMDB REST connection failed: {exc}"}


async def import_preview(config: CmdbConfig, limit: int = 20) -> dict[str, Any]:
    url = config.import_url or config.target_url
    if not url:
        return {"success": False, "message": "CMDB REST import URL is not configured"}
    response = await request_json_via_validated_url(
        url,
        method="GET",
        headers=_auth_headers(config),
        timeout_seconds=config.timeout_seconds,
        label="CMDB REST import URL",
    )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"CMDB REST import returned HTTP {response.status_code}")
    data = json.loads(response.text)
    items = data if isinstance(data, list) else data.get("items") if isinstance(data, dict) else []
    items = items if isinstance(items, list) else []
    return {
        "success": True,
        "count": len(items),
        "sample": items[: max(1, min(limit, 100))],
        "conflict_strategy": config.import_conflict_strategy,
        "write_performed": False,
    }


def generate_cmdb_id(db: Session, prefix: str = "DEV", digits: int = 4) -> str:
    """Generate the next available CMDB ID with the given prefix and zero-padded digits.

    Format: {PREFIX}-{0000}  e.g. DEV-0001, CMDB-00042
    Finds the highest existing number with this prefix and returns prefix-(max+1).
    """
    pattern = f"{prefix}-"
    rows = (
        db.query(Device.cmdb_id)
        .filter(Device.cmdb_id.like(f"{pattern}%"))
        .all()
    )

    max_num = 0
    for (cid,) in rows:
        if cid and cid.startswith(pattern):
            try:
                num = int(cid[len(pattern):])
                if num > max_num:
                    max_num = num
            except (ValueError, TypeError):
                pass

    next_num = max_num + 1
    cmdb_id = f"{prefix}-{next_num:0{digits}d}"
    logger.debug("Generated CMDB ID: %s (next=%d, prefix=%s, digits=%d)", cmdb_id, next_num, prefix, digits)
    return cmdb_id


def get_cmdb_settings(db: Session) -> tuple[str, int]:
    """Return (prefix, digits) from settings, with defaults."""

    def _get(key: str, default: str) -> str:
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row and row.value else default

    prefix = _get("cmdb_id_prefix", "DEV").strip().upper() or "DEV"
    try:
        digits = int(_get("cmdb_id_digits", "4"))
        digits = max(1, min(digits, 10))
    except (ValueError, TypeError):
        digits = 4
    return prefix, digits
