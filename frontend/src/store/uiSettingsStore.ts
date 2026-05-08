import { create } from 'zustand'
import { settingsApi } from '../api/settings'

interface UiSettingsState {
  showServicesNav: boolean
  showDhcpMonitorNav: boolean
  loading: boolean
  setShowServicesNav: (showServicesNav: boolean) => void
  setShowDhcpMonitorNav: (showDhcpMonitorNav: boolean) => void
  fetchUiSettings: () => Promise<void>
}

export const useUiSettingsStore = create<UiSettingsState>((set) => ({
  showServicesNav: false,
  showDhcpMonitorNav: false,
  loading: false,

  setShowServicesNav: (showServicesNav) => set({ showServicesNav }),
  setShowDhcpMonitorNav: (showDhcpMonitorNav) => set({ showDhcpMonitorNav }),

  fetchUiSettings: async () => {
    set({ loading: true })
    try {
      const settings = await settingsApi.get()
      set({
        showServicesNav: settings.show_services_nav,
        showDhcpMonitorNav: settings.show_dhcp_monitor_nav,
      })
    } finally {
      set({ loading: false })
    }
  },
}))
