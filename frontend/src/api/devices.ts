import apiClient from './client'
import type { ChangeEvent } from './inventory'
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

export interface DeviceIpHistoryEntry {
  id: number
  device_id: number
  ip_address: string
  first_seen: string
  last_seen: string
  seen_count: number
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
  // CMDB
  cmdb_id?: string | null
  ignored?: boolean
  notifications_muted?: boolean
  maintenance_until?: string | null
  maintenance_note?: string | null
  idoit_enabled?: boolean
  idoit_sync_status?: string | null
  idoit_object_id?: string | null
  idoit_sysid?: string | null
  idoit_object_url?: string | null
  idoit_last_sync_at?: string | null
  idoit_last_validation_at?: string | null
  idoit_last_error?: string | null
  // State
  is_registered: boolean
  is_new: boolean
  is_online: boolean
  first_seen: string
  last_seen: string
  // Deep scan summary
  hardware_summary?: string | null
  // VM host
  host_label?: string | null
  // Relations
  latest_scan: PortScanResult | null
  services: Service[]
  ip_history?: DeviceIpHistoryEntry[]
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
  purpose?: string
  description?: string
  location?: string
  responsible?: string
  password_location?: string
  os_info?: string
  asset_tag?: string
  notes?: string
  cmdb_id?: string
  ignored?: boolean
  notifications_muted?: boolean
  maintenance_until?: string | null
  maintenance_note?: string | null
}

export const devicesApi = {
  list: (params?: {
    online_only?: boolean
    unregistered_only?: boolean
    device_class?: string
    search?: string
  }) => apiClient.get<DeviceListResponse>('/devices', { params }).then((r) => r.data),

  get: (id: number) => apiClient.get<Device>(`/devices/${id}`).then((r) => r.data),

  getIpHistory: (id: number) =>
    apiClient.get<DeviceIpHistoryEntry[]>(`/devices/${id}/ip-history`).then((r) => r.data),

  getTimeline: (id: number) =>
    apiClient.get<ChangeEvent[]>(`/devices/${id}/timeline`).then((r) => r.data),

  markViewed: (id: number) => apiClient.post(`/devices/${id}/mark-viewed`).then((r) => r.data),

  update: (id: number, data: DeviceUpdate) =>
    apiClient.put<Device>(`/devices/${id}`, data).then((r) => r.data),

  updateMaintenance: (id: number, data: Pick<DeviceUpdate, 'ignored' | 'notifications_muted' | 'maintenance_until' | 'maintenance_note'>) =>
    apiClient.put<Device>(`/devices/${id}/maintenance`, data).then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/devices/${id}`),

  refreshStatus: (id: number) =>
    apiClient.post<Device>(`/devices/${id}/refresh-status`).then((r) => r.data),

  scanPorts: (id: number) => apiClient.post(`/devices/${id}/scan-ports`).then((r) => r.data),

  getPorts: (id: number) =>
    apiClient.get<PortScanResult[]>(`/devices/${id}/ports`).then((r) => r.data),

  scanSinglePort: (id: number, port: number) =>
    apiClient.post(`/devices/${id}/scan-single-port`, { port }).then((r) => r.data),

  scanPortRange: (id: number, portRange: string) =>
    apiClient.post(`/devices/${id}/scan-port-range`, { port_range: portRange }).then((r) => r.data),

  getRdpUrl: (id: number) => withBasePath(`/api/connect/${id}/rdp`),

  generateCmdbId: (id: number) =>
    apiClient.post<Device>(`/devices/${id}/generate-cmdb-id`).then((r) => r.data),
}
