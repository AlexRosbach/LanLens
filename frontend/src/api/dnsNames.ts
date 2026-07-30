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

export interface AxfrDnsConfig {
  dns_names_enabled: boolean
  enabled: boolean
  server: string
  zones: string[]
  port: number
  timeout_seconds: number
  tsig_key_name: string
  tsig_secret?: string
  clear_tsig_secret?: boolean
  tsig_algorithm: string
  tsig_configured: boolean
  interval_minutes: number
  last_sync_at: string | null
  last_error: string
}

export const dnsNamesApi = {
  getConfig: () => apiClient.get<AxfrDnsConfig>('/dns-names/config').then((r) => r.data),
  updateConfig: (data: Omit<AxfrDnsConfig, 'last_sync_at' | 'last_error' | 'tsig_configured'>) =>
    apiClient.put<AxfrDnsConfig>('/dns-names/config', data).then((r) => r.data),
  test: (data: Omit<AxfrDnsConfig, 'last_sync_at' | 'last_error' | 'tsig_configured'>) =>
    apiClient.post<{ ok: boolean; records: number; zones: number }>('/dns-names/test', data).then((r) => r.data),
  sync: () =>
    apiClient.post<{ ok: boolean; records: number; names: number; devices: number }>('/dns-names/sync').then((r) => r.data),
  listDeviceNames: (deviceId: number, refresh = false) =>
    apiClient.get<DeviceDnsName[]>(`/dns-names/devices/${deviceId}`, { params: { refresh } }).then((r) => r.data),
  setPreferred: (deviceId: number, mode: 'automatic' | 'manual' | 'discovered', name?: string) =>
    apiClient.put(`/dns-names/devices/${deviceId}/preferred`, { mode, name }).then((r) => r.data),
}
