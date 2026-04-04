import { create } from 'zustand'
import { devicesApi, Device, DeviceListResponse } from '../api/devices'

interface DeviceState {
  devices: Device[]
  stats: { total: number; online: number; offline: number; unregistered: number }
  loading: boolean
  fetchDevices: (params?: { online_only?: boolean; unregistered_only?: boolean; device_class?: string; search?: string }) => Promise<void>
  updateDevice: (id: number, data: Partial<Device>) => void
}

export const useDeviceStore = create<DeviceState>((set) => ({
  devices: [],
  stats: { total: 0, online: 0, offline: 0, unregistered: 0 },
  loading: false,

  fetchDevices: async (params) => {
    set({ loading: true })
    try {
      const data = await devicesApi.list(params)
      set({
        devices: data.items,
        stats: {
          total: data.total,
          online: data.online,
          offline: data.offline,
          unregistered: data.unregistered,
        },
      })
    } finally {
      set({ loading: false })
    }
  },

  updateDevice: (id, update) => {
    set((state) => ({
      devices: state.devices.map((d) => (d.id === id ? { ...d, ...update } : d)),
    }))
  },
}))
