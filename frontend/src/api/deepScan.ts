import apiClient from './client'

export type ScanProfile =
  | 'hardware_only'
  | 'os_services'
  | 'linux_container_host'
  | 'windows_audit'
  | 'hypervisor_inventory'
  | 'full'

export type DeepScanStatus = 'running' | 'done' | 'error' | 'skipped'

export interface DeepScanConfig {
  device_id: number
  enabled: boolean
  credential_id: number | null
  scan_profile: ScanProfile
  auto_scan_enabled: boolean
  interval_minutes: number
  last_scan_at: string | null
}

export interface DeepScanConfigUpdate {
  enabled?: boolean
  credential_id?: number | null
  scan_profile?: ScanProfile
  auto_scan_enabled?: boolean
  interval_minutes?: number
}

export interface DeepScanRun {
  id: number
  device_id: number
  credential_id: number | null
  profile: ScanProfile
  status: DeepScanStatus
  started_at: string
  finished_at: string | null
  summary: Record<string, unknown> | null
  error_message: string | null
  triggered_by: 'manual' | 'scheduled'
}

export interface DeepScanFinding {
  id: number
  device_id: number
  run_id: number
  finding_type: string
  key: string
  value: unknown
  source: string | null
  observed_at: string
}

export interface DeviceHostRelationship {
  id: number
  child_device_id: number
  host_device_id: number
  relationship_type: string
  match_source: string | null
  vm_identifier: string | null
  observed_at: string
  last_confirmed_at: string
}

export const deepScanApi = {
  getConfig: (deviceId: number) =>
    apiClient.get<DeepScanConfig>(`/devices/${deviceId}/deep-scan/config`),

  updateConfig: (deviceId: number, data: DeepScanConfigUpdate) =>
    apiClient.put<DeepScanConfig>(`/devices/${deviceId}/deep-scan/config`, data),

  triggerScan: (deviceId: number) =>
    apiClient.post<{ message: string }>(`/devices/${deviceId}/deep-scan/run`),

  listRuns: (deviceId: number, limit = 10) =>
    apiClient.get<DeepScanRun[]>(`/devices/${deviceId}/deep-scan/runs`, { params: { limit } }),

  getRun: (deviceId: number, runId: number) =>
    apiClient.get<DeepScanRun>(`/devices/${deviceId}/deep-scan/runs/${runId}`),

  getFindings: (deviceId: number, findingType?: string) =>
    apiClient.get<DeepScanFinding[]>(`/devices/${deviceId}/deep-scan/findings`, {
      params: findingType ? { finding_type: findingType } : {},
    }),

  getRelationships: (deviceId: number) =>
    apiClient.get<DeviceHostRelationship[]>(`/devices/${deviceId}/deep-scan/relationships`),

  createRelationship: (guestDeviceId: number, hostDeviceId: number, vmIdentifier?: string) =>
    apiClient.post<DeviceHostRelationship>(`/devices/${guestDeviceId}/deep-scan/relationships`, {
      host_device_id: hostDeviceId,
      vm_identifier: vmIdentifier ?? null,
    }),

  deleteRelationship: (deviceId: number, relId: number) =>
    apiClient.delete(`/devices/${deviceId}/deep-scan/relationships/${relId}`),
}
