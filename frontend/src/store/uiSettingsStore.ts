import { create } from 'zustand'
import { settingsApi } from '../api/settings'

interface UiSettingsState {
  advancedViewEnabled: boolean
  showCmdbIntegrations: boolean
  showServicesNav: boolean
  showDhcpMonitorNav: boolean
  showNetworkTopologyNav: boolean
  showPluginApi: boolean
  showPassiveDiscovery: boolean
  showMdnsDiscovery: boolean
  showSsdpDiscovery: boolean
  showTlsChecks: boolean
  showPingHistory: boolean
  showBuildInfo: boolean
  showDebugTools: boolean
  debugLogLevel: 'info' | 'warning' | 'error' | 'debug' | 'trace'
  appVersion: string
  buildCode: string
  buildCommit: string
  buildBranch: string
  buildCreated: string
  loading: boolean
  setAdvancedViewEnabled: (advancedViewEnabled: boolean) => void
  setShowCmdbIntegrations: (showCmdbIntegrations: boolean) => void
  setShowServicesNav: (showServicesNav: boolean) => void
  setShowDhcpMonitorNav: (showDhcpMonitorNav: boolean) => void
  setShowNetworkTopologyNav: (showNetworkTopologyNav: boolean) => void
  setShowPluginApi: (showPluginApi: boolean) => void
  setShowPassiveDiscovery: (showPassiveDiscovery: boolean) => void
  setShowMdnsDiscovery: (showMdnsDiscovery: boolean) => void
  setShowSsdpDiscovery: (showSsdpDiscovery: boolean) => void
  setShowTlsChecks: (showTlsChecks: boolean) => void
  setShowPingHistory: (showPingHistory: boolean) => void
  setShowBuildInfo: (showBuildInfo: boolean) => void
  setShowDebugTools: (showDebugTools: boolean) => void
  fetchUiSettings: () => Promise<void>
}

function normalizeFeatureGates(input: {
  advancedViewEnabled: boolean
  showPluginApi: boolean
  showPassiveDiscovery: boolean
  showMdnsDiscovery: boolean
  showSsdpDiscovery: boolean
}) {
  const showPluginApi = input.advancedViewEnabled && input.showPluginApi
  const showPassiveDiscovery = showPluginApi && input.showPassiveDiscovery
  return {
    showPluginApi,
    showPassiveDiscovery,
    showMdnsDiscovery: showPassiveDiscovery && input.showMdnsDiscovery,
    showSsdpDiscovery: showPassiveDiscovery && input.showSsdpDiscovery,
  }
}

export const useUiSettingsStore = create<UiSettingsState>((set) => ({
  advancedViewEnabled: false,
  showCmdbIntegrations: false,
  showServicesNav: false,
  showDhcpMonitorNav: false,
  showNetworkTopologyNav: false,
  showPluginApi: false,
  showPassiveDiscovery: false,
  showMdnsDiscovery: false,
  showSsdpDiscovery: false,
  showTlsChecks: false,
  showPingHistory: false,
  showBuildInfo: false,
  showDebugTools: false,
  debugLogLevel: 'warning',
  appVersion: '',
  buildCode: '',
  buildCommit: '',
  buildBranch: '',
  buildCreated: '',
  loading: false,

  setAdvancedViewEnabled: (advancedViewEnabled) => set((state) => ({
    advancedViewEnabled,
    showCmdbIntegrations: advancedViewEnabled && state.showCmdbIntegrations,
    showServicesNav: advancedViewEnabled && state.showServicesNav,
    showDhcpMonitorNav: advancedViewEnabled && state.showDhcpMonitorNav,
    showNetworkTopologyNav: advancedViewEnabled && state.showNetworkTopologyNav,
    showTlsChecks: advancedViewEnabled && state.showTlsChecks,
    showPingHistory: advancedViewEnabled && state.showPingHistory,
    showDebugTools: advancedViewEnabled && state.showDebugTools,
    ...normalizeFeatureGates({
      advancedViewEnabled,
      showPluginApi: state.showPluginApi,
      showPassiveDiscovery: state.showPassiveDiscovery,
      showMdnsDiscovery: state.showMdnsDiscovery,
      showSsdpDiscovery: state.showSsdpDiscovery,
    }),
  })),
  setShowCmdbIntegrations: (showCmdbIntegrations) => set({ showCmdbIntegrations }),
  setShowServicesNav: (showServicesNav) => set({ showServicesNav }),
  setShowDhcpMonitorNav: (showDhcpMonitorNav) => set({ showDhcpMonitorNav }),
  setShowNetworkTopologyNav: (showNetworkTopologyNav) => set({ showNetworkTopologyNav }),
  setShowPluginApi: (showPluginApi) => set((state) => normalizeFeatureGates({
    advancedViewEnabled: state.advancedViewEnabled,
    showPluginApi,
    showPassiveDiscovery: state.showPassiveDiscovery,
    showMdnsDiscovery: state.showMdnsDiscovery,
    showSsdpDiscovery: state.showSsdpDiscovery,
  })),
  setShowPassiveDiscovery: (showPassiveDiscovery) => set((state) => normalizeFeatureGates({
    advancedViewEnabled: state.advancedViewEnabled,
    showPluginApi: state.showPluginApi,
    showPassiveDiscovery,
    showMdnsDiscovery: state.showMdnsDiscovery,
    showSsdpDiscovery: state.showSsdpDiscovery,
  })),
  setShowMdnsDiscovery: (showMdnsDiscovery) => set((state) => normalizeFeatureGates({
    advancedViewEnabled: state.advancedViewEnabled,
    showPluginApi: state.showPluginApi,
    showPassiveDiscovery: state.showPassiveDiscovery,
    showMdnsDiscovery,
    showSsdpDiscovery: state.showSsdpDiscovery,
  })),
  setShowSsdpDiscovery: (showSsdpDiscovery) => set((state) => normalizeFeatureGates({
    advancedViewEnabled: state.advancedViewEnabled,
    showPluginApi: state.showPluginApi,
    showPassiveDiscovery: state.showPassiveDiscovery,
    showMdnsDiscovery: state.showMdnsDiscovery,
    showSsdpDiscovery,
  })),
  setShowTlsChecks: (showTlsChecks) => set({ showTlsChecks }),
  setShowPingHistory: (showPingHistory) => set({ showPingHistory }),
  setShowBuildInfo: (showBuildInfo) => set({ showBuildInfo }),
  setShowDebugTools: (showDebugTools) => set({ showDebugTools }),

  fetchUiSettings: async () => {
    set({ loading: true })
    try {
      const settings = await settingsApi.get()
      const featureGates = normalizeFeatureGates({
        advancedViewEnabled: settings.advanced_view_enabled,
        showPluginApi: settings.show_plugin_api,
        showPassiveDiscovery: settings.show_passive_discovery,
        showMdnsDiscovery: settings.show_mdns_discovery,
        showSsdpDiscovery: settings.show_ssdp_discovery,
      })
      set({
        advancedViewEnabled: settings.advanced_view_enabled,
        showCmdbIntegrations: settings.advanced_view_enabled && settings.show_cmdb_integrations,
        showServicesNav: settings.advanced_view_enabled && settings.show_services_nav,
        showDhcpMonitorNav: settings.advanced_view_enabled && settings.show_dhcp_monitor_nav,
        showNetworkTopologyNav: settings.advanced_view_enabled && settings.show_network_topology_nav,
        showPluginApi: featureGates.showPluginApi,
        showPassiveDiscovery: featureGates.showPassiveDiscovery,
        showMdnsDiscovery: featureGates.showMdnsDiscovery,
        showSsdpDiscovery: featureGates.showSsdpDiscovery,
        showTlsChecks: settings.advanced_view_enabled && settings.show_tls_checks,
        showPingHistory: settings.advanced_view_enabled && settings.show_ping_history,
        showBuildInfo: settings.show_build_info,
        showDebugTools: settings.advanced_view_enabled && settings.show_debug_tools,
        debugLogLevel: settings.debug_log_level,
        appVersion: settings.app_version,
        buildCode: settings.build_code,
        buildCommit: settings.build_commit,
        buildBranch: settings.build_branch,
        buildCreated: settings.build_created,
      })
    } finally {
      set({ loading: false })
    }
  },
}))
