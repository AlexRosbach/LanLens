import apiClient from './client'

export interface IdoitConfig {
  idoit_enabled: boolean
  idoit_base_url: string
  idoit_jsonrpc_path: string
  idoit_portal_url: string
  idoit_api_key_configured: boolean
  idoit_basic_username: string
  idoit_basic_password_configured: boolean
  idoit_timeout_seconds: number
  idoit_default_object_type: string
  idoit_auto_sync_enabled: boolean
  idoit_sync_scope: 'all' | 'manual'
  idoit_create_policy: 'match_only' | 'create_missing'
  idoit_sync_interval_minutes: number
  idoit_offline_retire_days: number
  idoit_sync_status_field: string
  idoit_mapping_json: string
  idoit_mapping_raw: string
  idoit_mapping_parsed?: Record<string, unknown>
  idoit_mapping_parse_error?: string | null
  mapping_errors: string[]
  scheduler?: {
    running: boolean
    next_run_at?: string | null
  }
}

export interface IdoitConfigUpdate {
  idoit_enabled: boolean
  idoit_base_url: string
  idoit_jsonrpc_path: string
  idoit_portal_url: string
  idoit_api_key?: string
  idoit_basic_username?: string
  idoit_basic_password?: string
  idoit_timeout_seconds: number
  idoit_default_object_type: string
  idoit_auto_sync_enabled: boolean
  idoit_sync_scope: 'all' | 'manual'
  idoit_create_policy: 'match_only' | 'create_missing'
  idoit_sync_interval_minutes: number
  idoit_offline_retire_days: number
  idoit_sync_status_field: string
  idoit_mapping_json: string
}

export interface IdoitTestResult {
  ok?: boolean
  version?: string
  message?: string
  [key: string]: unknown
}

export interface IdoitBulkSyncResult {
  total: number
  success: number
  failure: number
  skipped: number
  results: unknown[]
}

export interface IdoitEnableSyncAllResult {
  total: number
  updated: number
}

export interface IdoitSyncLogEntry {
  id: number
  device_id?: number | null
  device_name?: string | null
  mode: string
  result: string
  idoit_object_id?: string | null
  message?: string | null
  details?: Record<string, unknown>
  created_at: string
}

export interface IdoitExportRow {
  include: boolean
  device_id?: number | null
  object_type: string
  title: string
  ip_address: string
  mac_address: string
  hostname: string
  manufacturer: string
  model: string
  serial: string
  os_info: string
  inventory_no: string
  cmdb_id: string
  location: string
  responsible: string
  notes: string
  lanlens_id: string
}

export interface IdoitExportPreview {
  rows: IdoitExportRow[]
  total: number
  registered_only: boolean
  include_offline: boolean
}

export const idoitApi = {
  getConfig: () => apiClient.get<IdoitConfig>('/idoit/config').then((r) => r.data),

  updateConfig: (data: IdoitConfigUpdate) =>
    apiClient.put<IdoitConfig>('/idoit/config', data).then((r) => r.data),

  testConnection: (data?: Partial<IdoitConfigUpdate>) => apiClient.post<IdoitTestResult>('/idoit/test-connection', data ?? {}).then((r) => r.data),

  testMapping: () => apiClient.post<IdoitTestResult>('/idoit/test-mapping').then((r) => r.data),

  syncDevice: (id: number) => apiClient.post<IdoitTestResult>(`/idoit/devices/${id}/sync`).then((r) => r.data),

  syncAll: () => apiClient.post<IdoitBulkSyncResult>('/idoit/sync-all').then((r) => r.data),

  enableSyncAll: () => apiClient.post<IdoitEnableSyncAllResult>('/idoit/devices/enable-sync-all').then((r) => r.data),

  getLogs: (limit = 50) => apiClient.get<IdoitSyncLogEntry[]>('/idoit/logs', { params: { limit } }).then((r) => r.data),

  previewExport: (params?: { registered_only?: boolean; include_offline?: boolean; limit?: number }) =>
    apiClient.get<IdoitExportPreview>('/idoit/export/preview', { params }).then((r) => r.data),

  exportCsv: (rows: IdoitExportRow[]) =>
    apiClient.post('/idoit/export/csv', { rows }, { responseType: 'blob' }).then((r) => r.data as Blob),
}
