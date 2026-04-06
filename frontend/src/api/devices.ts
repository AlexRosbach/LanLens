import apiClient from './client'
import type { Service } from './services'
import { withBasePath } from '../utils/basePath'

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
  // Identification
  label: string | null
  device_class: string
  vendor: string | null
  // Segment
  segment_id: number | null
  segment_name: string | null
  segment_color: string | null
  // DHCP
  is_dhcp: boolean
  // Documentation
  purpose: string | null
  description: string | null
  location: string | null
  responsible: string | null
  password_location: string | null
  os_info: string | null
  asset_tag: string | null
  notes: string | null
  // State
  is_registered: boolean
  is_new: boolean
  is_online: boolean
  first_seen: string
  last_seen: string
  // Relations
  latest_scan: PortScanResult | null
  services: Service[]
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
  is_registered?: boolean
  segment_id?: number | null
  purpose?: string
  description?: string
  location?: string
  responsible?: string
  password_location?: string
  os_info?: string
  asset_tag?: string
  notes?: string
}

export const devicesApi = {
  list: (params?: {
    online_only?: boolean
    unregistered_only?: boolean
    device_class?: string
    search?: string
  }) => apiClient.get<DeviceListResponse>('/devices', { params }).then((r) => r.data),

  get: (id: number) => apiClient.get<Device>(`/devices/${id}`).then((r) => r.data),

  markViewed: (id: number) => apiClient.post(`/devices/${id}/mark-viewed`).then((r) => r.data),

  update: (id: number, data: DeviceUpdate) =>
    apiClient.put<Device>(`/devices/${id}`, data).then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/devices/${id}`),

  scanPorts: (id: number) => apiClient.post(`/devices/${id}/scan-ports`).then((r) => r.data),

  getPorts: (id: number) =>
    apiClient.get<PortScanResult[]>(`/devices/${id}/ports`).then((r) => r.data),

  getRdpUrl: (id: number) => withBasePath(`/api/connect/${id}/rdp`),
}
