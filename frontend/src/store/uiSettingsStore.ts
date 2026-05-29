import { create } from 'zustand'
import { settingsApi } from '../api/settings'

interface UiSettingsState {
  advancedViewEnabled: boolean
  showCmdbIntegrations: boolean
  showServicesNav: boolean
  showDhcpMonitorNav: boolean
  showPluginApi: boolean
  showPassiveDiscovery: boolean
  showMdnsDiscovery: boolean
  showSsdpDiscovery: boolean
  showTlsChecks: boolean
  showPingHistory: boolean
  showBuildInfo: boolean
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
  setShowPluginApi: (showPluginApi: boolean) => void
  setShowPassiveDiscovery: (showPassiveDiscovery: boolean) => void
  setShowMdnsDiscovery: (showMdnsDiscovery: boolean) => void
  setShowSsdpDiscovery: (showSsdpDiscovery: boolean) => void
  setShowTlsChecks: (showTlsChecks: boolean) => void
  setShowPingHistory: (showPingHistory: boolean) => void
  setShowBuildInfo: (showBuildInfo: boolean) => void
  fetchUiSettings: () => Promise<void>
}

export const useUiSettingsStore = create<UiSettingsState>((set) => ({
  advancedViewEnabled: false,
  showCmdbIntegrations: false,
  showServicesNav: false,
  showDhcpMonitorNav: false,
  showPluginApi: false,
  showPassiveDiscovery: false,
  showMdnsDiscovery: false,
  showSsdpDiscovery: false,
  showTlsChecks: false,
  showPingHistory: false,
  showBuildInfo: false,
  appVersion: '',
  buildCode: '',
  buildCommit: '',
  buildBranch: '',
  buildCreated: '',
  loading: false,

  setAdvancedViewEnabled: (advancedViewEnabled) => set({ advancedViewEnabled }),
  setShowCmdbIntegrations: (showCmdbIntegrations) => set({ showCmdbIntegrations }),
  setShowServicesNav: (showServicesNav) => set({ showServicesNav }),
  setShowDhcpMonitorNav: (showDhcpMonitorNav) => set({ showDhcpMonitorNav }),
  setShowPluginApi: (showPluginApi) => set({ showPluginApi }),
  setShowPassiveDiscovery: (showPassiveDiscovery) => set({ showPassiveDiscovery }),
  setShowMdnsDiscovery: (showMdnsDiscovery) => set({ showMdnsDiscovery }),
  setShowSsdpDiscovery: (showSsdpDiscovery) => set({ showSsdpDiscovery }),
  setShowTlsChecks: (showTlsChecks) => set({ showTlsChecks }),
  setShowPingHistory: (showPingHistory) => set({ showPingHistory }),
  setShowBuildInfo: (showBuildInfo) => set({ showBuildInfo }),

  fetchUiSettings: async () => {
    set({ loading: true })
    try {
      const settings = await settingsApi.get()
      set({
        advancedViewEnabled: settings.advanced_view_enabled,
        showCmdbIntegrations: settings.advanced_view_enabled && settings.show_cmdb_integrations,
        showServicesNav: settings.advanced_view_enabled && settings.show_services_nav,
        showDhcpMonitorNav: settings.advanced_view_enabled && settings.show_dhcp_monitor_nav,
        showPluginApi: settings.advanced_view_enabled && settings.show_plugin_api,
        showPassiveDiscovery: settings.advanced_view_enabled && settings.show_passive_discovery,
        showMdnsDiscovery: settings.advanced_view_enabled && settings.show_mdns_discovery,
        showSsdpDiscovery: settings.advanced_view_enabled && settings.show_ssdp_discovery,
        showTlsChecks: settings.advanced_view_enabled && settings.show_tls_checks,
        showPingHistory: settings.advanced_view_enabled && settings.show_ping_history,
        showBuildInfo: settings.show_build_info,
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
