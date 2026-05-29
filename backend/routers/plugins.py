import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import PassiveDiscoveryObservation, Setting, User
from ..schemas import (
    MessageResponse,
    PassiveDiscoveryObservationResponse,
    PassiveDiscoveryStatusResponse,
    PluginManifestResponse,
    PluginToggleRequest,
)
from ..services.passive_discovery import (
    capture_passive_discovery,
    is_capture_running,
    observation_to_response,
    try_begin_capture,
)
from ..services.plugin_registry import get_plugin, list_plugins

router = APIRouter(prefix="/api/plugins", tags=["plugins"])
passive_router = APIRouter(prefix="/api/passive-discovery", tags=["passive-discovery"])


def _set(db: Session, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


@router.get("", response_model=list[PluginManifestResponse])
def get_plugins(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list_plugins(db)


@router.put("/{plugin_key}", response_model=MessageResponse)
def set_plugin_enabled(
    plugin_key: str,
    data: PluginToggleRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    plugin = get_plugin(plugin_key)
    if not plugin:
        raise HTTPException(status_code=404, detail="Unknown plugin")
    _set(db, plugin.setting_key, "true" if data.enabled else "false")
    db.commit()
    return MessageResponse(message=f"{plugin.name} {'enabled' if data.enabled else 'disabled'}")


@passive_router.get("/observations", response_model=list[PassiveDiscoveryObservationResponse])
def list_passive_observations(
    protocol: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(PassiveDiscoveryObservation)
    if protocol:
        query = query.filter(PassiveDiscoveryObservation.protocol == protocol)
    rows = query.order_by(PassiveDiscoveryObservation.observed_at.desc()).limit(limit).all()
    return [observation_to_response(row) for row in rows]


@passive_router.post("/capture", response_model=MessageResponse)
def start_passive_capture(
    seconds: int = Query(30, ge=3, le=120),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    plugins = {plugin["key"]: plugin for plugin in list_plugins(db)}
    if not plugins.get("passive-discovery", {}).get("enabled"):
        raise HTTPException(status_code=403, detail="Passive discovery is disabled")

    enabled_protocols: set[str] = {"multicast"}
    if plugins.get("mdns-discovery", {}).get("enabled"):
        enabled_protocols.add("mdns")
    if plugins.get("ssdp-discovery", {}).get("enabled"):
        enabled_protocols.add("ssdp")

    if not try_begin_capture():
        return MessageResponse(message="Passive discovery capture already running", success=False)

    threading.Thread(
        target=capture_passive_discovery,
        args=(seconds, 100, enabled_protocols, True),
        name="lanlens-passive-discovery",
        daemon=True,
    ).start()
    return MessageResponse(message=f"Passive discovery capture started for {seconds} seconds")


@passive_router.get("/status", response_model=PassiveDiscoveryStatusResponse)
def get_passive_status(_: User = Depends(get_current_user)):
    return PassiveDiscoveryStatusResponse(is_capturing=is_capture_running())
