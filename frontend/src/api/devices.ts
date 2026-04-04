import apiClient from './client'

export interface PortInfo { port: number; protocol: string; service: string; state: string }
export interface PortScanResult {
  id: number
  scanned_at: string
  open_ports: PortInfo[]
  ssh_available: boolean
  rdp_available: boolean
  http_available: boolean
  https_available: boolean
}
export interface Device {
  id: number
  mac_address: string
  ip_address: string | null
  hostname: string | null
  label: string | null
  device_class: string
  vendor: string | null
  notes: string | null
  is_registered: boolean
  is_online: boolean
  first_seen: string
  last_seen: string
  latest_scan: PortScanResult | null
}
export interface DeviceListResponse {
  items: Device[]
  total: number
  online: number
  offline: number
  unregistered: number
}
export interface DeviceUpdate {
  label?: string
  device_class?: string
  notes?: string
  is_registered?: boolean
}

export const devicesApi = {
  list: (params?: {
    online_only?: boolean
    unregistered_only?: boolean
    device_class?: string
    search?: string
  }) => apiClient.get<DeviceListResponse>('/devices', { params }).then((r) => r.data),

  get: (id: number) => apiClient.get<Device>(`/devices/${id}`).then((r) => r.data),

  update: (id: number, data: DeviceUpdate) =>
    apiClient.put<Device>(`/devices/${id}`, data).then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/devices/${id}`),

  scanPorts: (id: number) => apiClient.post(`/devices/${id}/scan-ports`).then((r) => r.data),

  getPorts: (id: number) =>
    apiClient.get<PortScanResult[]>(`/devices/${id}/ports`).then((r) => r.data),

  getRdpUrl: (id: number) => `/api/connect/${id}/rdp`,
}
