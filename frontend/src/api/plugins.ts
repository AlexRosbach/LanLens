import apiClient from './client'

export interface PluginManifest {
  key: string
  name: string
  category: string
  description: string
  enabled: boolean
  status: string
  setting_key: string
  dependencies: string[]
  related_issues: number[]
  config_hint?: string | null
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
}

export interface PassiveDiscoveryHaMember {
  source_ip?: string | null
  source_mac?: string | null
  device_id?: number | null
  device_label?: string | null
  observed_at: string
}

export interface PassiveDiscoveryHaGroup {
  protocol: string
  group_key: string
  destination_ip?: string | null
  virtual_ip?: string | null
  active_device_id?: number | null
  active_device_label?: string | null
  member_count: number
  observed_at: string
  members: PassiveDiscoveryHaMember[]
}

export interface PassiveDiscoveryCaptureReport {
  filter: string
  protocols: string[]
  packets_seen: number
  packets_parsed: number
  observations_stored: number
  observations_linked: number
  duplicates_skipped: number
  errors: string[]
}

export const pluginsApi = {
  list: () => apiClient.get<PluginManifest[]>('/plugins').then((r) => r.data),
  setEnabled: (key: string, enabled: boolean) =>
    apiClient.put(`/plugins/${key}`, { enabled }).then((r) => r.data),
}

export const passiveDiscoveryApi = {
  observations: (protocol?: string) =>
    apiClient.get<PassiveDiscoveryObservation[]>('/passive-discovery/observations', { params: { protocol } }).then((r) => r.data),
  haGroups: () =>
    apiClient.get<PassiveDiscoveryHaGroup[]>('/passive-discovery/ha-groups').then((r) => r.data),
  capture: (seconds = 30) =>
    apiClient.post('/passive-discovery/capture', null, { params: { seconds } }).then((r) => r.data),
  diagnostics: (seconds = 10) =>
    apiClient.post<PassiveDiscoveryCaptureReport>('/passive-discovery/capture/diagnostics', null, { params: { seconds } }).then((r) => r.data),
  status: () => apiClient.get<{ is_capturing: boolean }>('/passive-discovery/status').then((r) => r.data),
}
