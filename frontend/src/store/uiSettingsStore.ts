import { create } from 'zustand'
import { settingsApi } from '../api/settings'

interface UiSettingsState {
  advancedViewEnabled: boolean
  showServicesNav: boolean
  showDhcpMonitorNav: boolean
  loading: boolean
  setAdvancedViewEnabled: (advancedViewEnabled: boolean) => void
  setShowServicesNav: (showServicesNav: boolean) => void
  setShowDhcpMonitorNav: (showDhcpMonitorNav: boolean) => void
  fetchUiSettings: () => Promise<void>
}

export const useUiSettingsStore = create<UiSettingsState>((set) => ({
  advancedViewEnabled: false,
  showServicesNav: false,
  showDhcpMonitorNav: false,
  loading: false,

  setAdvancedViewEnabled: (advancedViewEnabled) => set({ advancedViewEnabled }),
  setShowServicesNav: (showServicesNav) => set({ showServicesNav }),
  setShowDhcpMonitorNav: (showDhcpMonitorNav) => set({ showDhcpMonitorNav }),

  fetchUiSettings: async () => {
    set({ loading: true })
    try {
      const settings = await settingsApi.get()
      set({
        advancedViewEnabled: settings.advanced_view_enabled,
        showServicesNav: settings.advanced_view_enabled && settings.show_services_nav,
        showDhcpMonitorNav: settings.advanced_view_enabled && settings.show_dhcp_monitor_nav,
      })
    } finally {
      set({ loading: false })
    }
  },
}))
