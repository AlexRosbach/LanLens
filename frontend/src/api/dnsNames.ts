import apiClient from './client'

export interface DeviceDnsName {
  id: number
  device_id: number
  name: string
  record_type: string
  source: string
  canonical_name: string | null
  address: string | null
  status: 'active' | 'stale' | 'conflicting'
  first_seen: string
  last_seen: string
}

export interface MicrosoftDnsConfig {
  dns_names_enabled: boolean
  enabled: boolean
  server: string
  zones: string[]
  credential_id: number | null
  interval_minutes: number
  last_sync_at: string | null
  last_error: string
}

export const dnsNamesApi = {
  getConfig: () => apiClient.get<MicrosoftDnsConfig>('/dns-names/config').then((r) => r.data),
  updateConfig: (data: Omit<MicrosoftDnsConfig, 'last_sync_at' | 'last_error'>) =>
    apiClient.put<MicrosoftDnsConfig>('/dns-names/config', data).then((r) => r.data),
  test: (data: Omit<MicrosoftDnsConfig, 'last_sync_at' | 'last_error'>) =>
    apiClient.post<{ ok: boolean; records: number; zones: number }>('/dns-names/test', data).then((r) => r.data),
  sync: () =>
    apiClient.post<{ ok: boolean; records: number; names: number; devices: number }>('/dns-names/sync').then((r) => r.data),
  listDeviceNames: (deviceId: number, refresh = false) =>
    apiClient.get<DeviceDnsName[]>(`/dns-names/devices/${deviceId}`, { params: { refresh } }).then((r) => r.data),
  setPreferred: (deviceId: number, mode: 'automatic' | 'manual' | 'discovered', name?: string) =>
    apiClient.put(`/dns-names/devices/${deviceId}/preferred`, { mode, name }).then((r) => r.data),
}
