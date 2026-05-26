import { create } from 'zustand'
import { settingsApi } from '../api/settings'

interface UiSettingsState {
  advancedViewEnabled: boolean
  showServicesNav: boolean
  showDhcpMonitorNav: boolean
  showBuildInfo: boolean
  appVersion: string
  buildCode: string
  buildCommit: string
  buildBranch: string
  buildCreated: string
  loading: boolean
  setAdvancedViewEnabled: (advancedViewEnabled: boolean) => void
  setShowServicesNav: (showServicesNav: boolean) => void
  setShowDhcpMonitorNav: (showDhcpMonitorNav: boolean) => void
  setShowBuildInfo: (showBuildInfo: boolean) => void
  fetchUiSettings: () => Promise<void>
}

export const useUiSettingsStore = create<UiSettingsState>((set) => ({
  advancedViewEnabled: false,
  showServicesNav: false,
  showDhcpMonitorNav: false,
  showBuildInfo: false,
  appVersion: '',
  buildCode: '',
  buildCommit: '',
  buildBranch: '',
  buildCreated: '',
  loading: false,

  setAdvancedViewEnabled: (advancedViewEnabled) => set({ advancedViewEnabled }),
  setShowServicesNav: (showServicesNav) => set({ showServicesNav }),
  setShowDhcpMonitorNav: (showDhcpMonitorNav) => set({ showDhcpMonitorNav }),
  setShowBuildInfo: (showBuildInfo) => set({ showBuildInfo }),

  fetchUiSettings: async () => {
    set({ loading: true })
    try {
      const settings = await settingsApi.get()
      set({
        advancedViewEnabled: settings.advanced_view_enabled,
        showServicesNav: settings.advanced_view_enabled && settings.show_services_nav,
        showDhcpMonitorNav: settings.advanced_view_enabled && settings.show_dhcp_monitor_nav,
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
