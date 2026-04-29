import { create } from 'zustand'
import { settingsApi } from '../api/settings'

interface UiSettingsState {
  showServicesNav: boolean
  loading: boolean
  setShowServicesNav: (showServicesNav: boolean) => void
  fetchUiSettings: () => Promise<void>
}

export const useUiSettingsStore = create<UiSettingsState>((set) => ({
  showServicesNav: false,
  loading: false,

  setShowServicesNav: (showServicesNav) => set({ showServicesNav }),

  fetchUiSettings: async () => {
    set({ loading: true })
    try {
      const settings = await settingsApi.get()
      set({ showServicesNav: settings.show_services_nav })
    } finally {
      set({ loading: false })
    }
  },
}))
