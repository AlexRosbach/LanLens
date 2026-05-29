"""Built-in extension registry.

LanLens intentionally starts with built-in optional modules instead of loading
third-party code. This keeps the first plugin API useful for feature gating and
metadata without adding a runtime execution surface.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .settings_helpers import get_setting_value


@dataclass(frozen=True)
class PluginManifest:
    key: str
    name: str
    category: str
    description: str
    setting_key: str
    dependencies: tuple[str, ...] = ()
    related_issues: tuple[int, ...] = ()
    config_hint: str | None = None
    status: str = "experimental"


BUILTIN_PLUGINS: tuple[PluginManifest, ...] = (
    PluginManifest(
        key="plugin-api",
        name="Plugin API",
        category="platform",
        description="Lightweight registry for optional LanLens extension modules.",
        setting_key="show_plugin_api",
        related_issues=(90,),
        config_hint="Enable Advanced View first. This exposes extension metadata only, not third-party code loading.",
        status="preview",
    ),
    PluginManifest(
        key="passive-discovery",
        name="Multicast protocol discovery",
        category="discovery",
        description="Optional packet-observation surface for multicast and control-plane protocols.",
        setting_key="show_passive_discovery",
        dependencies=("plugin-api",),
        related_issues=(80,),
        config_hint="Requires host networking/raw packet permissions for live capture.",
    ),
    PluginManifest(
        key="mdns-discovery",
        name="mDNS analysis",
        category="discovery",
        description="Observe mDNS/Bonjour packets and store host, service and TXT metadata when visible.",
        setting_key="show_mdns_discovery",
        dependencies=("plugin-api", "passive-discovery"),
        related_issues=(70,),
        config_hint="Disabled by default. Captures UDP/5353 multicast traffic when explicitly started.",
    ),
    PluginManifest(
        key="ssdp-discovery",
        name="SSDP / UPnP discovery",
        category="discovery",
        description="Observe SSDP/UPnP multicast traffic and store device/service advertisement metadata.",
        setting_key="show_ssdp_discovery",
        dependencies=("plugin-api", "passive-discovery"),
        related_issues=(82,),
        config_hint="Disabled by default. Captures UDP/1900 multicast traffic when explicitly started.",
    ),
)


def list_plugins(db: Session) -> list[dict]:
    advanced_enabled = get_setting_value(db, "advanced_view_enabled", "false") == "true"
    enabled_keys = {
        plugin.key
        for plugin in BUILTIN_PLUGINS
        if advanced_enabled and get_setting_value(db, plugin.setting_key, "false") == "true"
    }

    plugins: list[dict] = []
    for plugin in BUILTIN_PLUGINS:
        dependencies_enabled = all(dep in enabled_keys for dep in plugin.dependencies)
        enabled = plugin.key in enabled_keys and dependencies_enabled
        status = plugin.status
        if not advanced_enabled:
            status = "disabled_advanced_view_required"
        elif plugin.key in enabled_keys and not dependencies_enabled:
            status = "disabled_dependency_missing"
        elif enabled:
            status = "enabled"
        plugins.append({
            "key": plugin.key,
            "name": plugin.name,
            "category": plugin.category,
            "description": plugin.description,
            "enabled": enabled,
            "status": status,
            "setting_key": plugin.setting_key,
            "dependencies": list(plugin.dependencies),
            "related_issues": list(plugin.related_issues),
            "config_hint": plugin.config_hint,
        })
    return plugins


def get_plugin(key: str) -> PluginManifest | None:
    return next((plugin for plugin in BUILTIN_PLUGINS if plugin.key == key), None)


def is_plugin_enabled(db: Session, key: str) -> bool:
    return any(plugin["key"] == key and plugin["enabled"] for plugin in list_plugins(db))
