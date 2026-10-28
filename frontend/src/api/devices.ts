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

export interface ManualConnectEntry {
  id: number
  device_id: number
  label: string
  url: string
  protocol: 'http' | 'https' | 'ssh' | 'rdp' | 'vnc' | 'tcp'
  sort_order: number
  created_at: string
  updated_at: string
}

export interface ManualConnectEntryInput {
  label: string
  url: string
  protocol: ManualConnectEntry['protocol']
  sort_order?: number
}

export interface BulkPortScanStatus {
  job_id: string | null
  status: 'idle' | 'running' | 'cancelling' | 'cancelled' | 'completed'
  total: number
  completed: number
  succeeded: number
  failed: number
  skipped: number
  cancel_requested: boolean
  started_at: string | null
  finished_at: string | null
}

export interface DeviceIpHistoryEntry {
  id: number
  device_id: number
  ip_address: string
  first_seen: string
  last_seen: string
  seen_count: number
}

export interface DevicePingSample {
  id: number
  device_id: number
  checked_at: string
  success: boolean
  latency_ms: number | null
  source: string
}

export interface PassiveDiscoveryObservation {
  id: number
  protocol: string
  source_ip?: string | null
  source_mac?: string | null
  destination_ip?: string | null
  service_name?: string | null
  service_type?: string | null
  summary?: string | null
  metadata: Record<string, unknown>
  observed_at: string
  linked_device_id?: number | null
  linked_device_label?: string | null
  inferred_device_class?: string | null
  inference_confidence?: string | null
  inference_reasons?: string[]
}

export interface Device {
  id: number
  mac_address: string
  ip_address: string | null
  hostname: string | null
  preferred_name?: string | null
  preferred_name_mode?: 'automatic' | 'manual' | 'discovered'
  display_name?: string | null
  // Identification
  label: string | null
  device_class: string
  vendor: string | null
  vendor_detected?: string | null
  vendor_override?: string | null
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
  is_archived?: boolean
  archived_at?: string | null
  idoit_enabled?: boolean
  idoit_sync_enabled?: boolean
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
  manual_connect_entries: ManualConnectEntry[]
  ip_history?: DeviceIpHistoryEntry[]
  snmp_switch?: string | null
  snmp_switch_host?: string | null
  snmp_interface?: string | null
  snmp_interface_alias?: string | null
  snmp_vlan?: string | null
  snmp_last_seen_at?: string | null
  snmp_interface_speed_bps?: number | null
  snmp_interface_admin_status?: string | null
  snmp_interface_oper_status?: string | null
  snmp_interface_in_unicast_packets?: number | null
  snmp_interface_in_non_unicast_packets?: number | null
  snmp_interface_out_unicast_packets?: number | null
  snmp_interface_out_non_unicast_packets?: number | null
  snmp_interface_in_discards?: number | null
  snmp_interface_out_discards?: number | null
  snmp_interface_in_errors?: number | null
  snmp_interface_out_errors?: number | null
  snmp_interface_unknown_protocols?: number | null
  snmp_interface_crc_errors?: number | null
  snmp_interface_collision_errors?: number | null
  snmp_interface_fragment_errors?: number | null
}

export interface DeviceListResponse {
  items: Device[]
  total: number
  online: number
  offline: number
  unregistered: number
  archived: number
}

export interface DeviceUpdate {
  label?: string | null
  preferred_name?: string | null
  preferred_name_mode?: 'automatic' | 'manual' | 'discovered'
  device_class?: string
  vendor_override?: string | null
  is_registered?: boolean
  purpose?: string | null
  description?: string | null
  location?: string | null
  responsible?: string | null
  password_location?: string | null
  os_info?: string | null
  asset_tag?: string | null
  notes?: string | null
  cmdb_id?: string | null
  idoit_sync_enabled?: boolean
  idoit_sysid?: string | null
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
    archived_only?: boolean
  }) => apiClient.get<DeviceListResponse>('/devices', { params }).then((r) => r.data),

  get: (id: number) => apiClient.get<Device>(`/devices/${id}`).then((r) => r.data),

  getIpHistory: (id: number) =>
    apiClient.get<DeviceIpHistoryEntry[]>(`/devices/${id}/ip-history`).then((r) => r.data),

  getPingHistory: (id: number, limit = 120) =>
    apiClient.get<DevicePingSample[]>(`/devices/${id}/ping-history`, { params: { limit } }).then((r) => r.data),

  getPassiveDiscovery: (id: number, limit = 50) =>
    apiClient.get<PassiveDiscoveryObservation[]>(`/devices/${id}/passive-discovery`, { params: { limit } }).then((r) => r.data),

  getTimeline: (id: number) =>
    apiClient.get<ChangeEvent[]>(`/devices/${id}/timeline`).then((r) => r.data),

  markViewed: (id: number) => apiClient.post(`/devices/${id}/mark-viewed`).then((r) => r.data),

  update: (id: number, data: DeviceUpdate) =>
    apiClient.put<Device>(`/devices/${id}`, data).then((r) => r.data),


  delete: (id: number) => apiClient.delete(`/devices/${id}`),

  bulkDelete: (deviceIds: number[]) =>
    apiClient.post('/devices/bulk-delete', { device_ids: deviceIds }).then((r) => r.data),

  bulkUpdate: (deviceIds: number[], data: Pick<DeviceUpdate, 'device_class' | 'responsible' | 'location' | 'description'>) =>
    apiClient.post<{ updated: number; message: string }>('/devices/bulk-update', { device_ids: deviceIds, ...data }).then((r) => r.data),

  startBulkPortScan: (deviceIds?: number[]) =>
    apiClient.post<BulkPortScanStatus>('/devices/bulk-port-scan', deviceIds?.length ? { device_ids: deviceIds } : {}).then((r) => r.data),

  getBulkPortScanStatus: () =>
    apiClient.get<BulkPortScanStatus>('/devices/bulk-port-scan/status').then((r) => r.data),

  cancelBulkPortScan: () =>
    apiClient.post<BulkPortScanStatus>('/devices/bulk-port-scan/cancel').then((r) => r.data),

  listManualConnectEntries: (id: number) =>
    apiClient.get<ManualConnectEntry[]>(`/devices/${id}/manual-connect`).then((r) => r.data),

  createManualConnectEntry: (id: number, data: ManualConnectEntryInput) =>
    apiClient.post<ManualConnectEntry>(`/devices/${id}/manual-connect`, data).then((r) => r.data),

  updateManualConnectEntry: (id: number, entryId: number, data: ManualConnectEntryInput) =>
    apiClient.put<ManualConnectEntry>(`/devices/${id}/manual-connect/${entryId}`, data).then((r) => r.data),

  deleteManualConnectEntry: (id: number, entryId: number) =>
    apiClient.delete(`/devices/${id}/manual-connect/${entryId}`),

  archive: (id: number) =>
    apiClient.post<Device>(`/devices/${id}/archive`).then((r) => r.data),

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
