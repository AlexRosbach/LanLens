import apiClient from './client'

export interface IdoitConfig {
  idoit_enabled: boolean
  idoit_base_url: string
  idoit_jsonrpc_path: string
  idoit_portal_url: string
  idoit_api_key_configured: boolean
  idoit_timeout_seconds: number
  idoit_default_object_type: string
  idoit_auto_sync_enabled: boolean
  idoit_sync_status_field: string
  idoit_mapping_json: string
  idoit_mapping_raw: string
  idoit_mapping_parsed?: Record<string, unknown>
  idoit_mapping_parse_error?: string | null
  mapping_errors: string[]
}

export interface IdoitConfigUpdate {
  idoit_enabled: boolean
  idoit_base_url: string
  idoit_jsonrpc_path: string
  idoit_portal_url: string
  idoit_api_key?: string
  idoit_timeout_seconds: number
  idoit_default_object_type: string
  idoit_auto_sync_enabled: boolean
  idoit_sync_status_field: string
  idoit_mapping_json: string
}

export interface IdoitTestResult {
  ok?: boolean
  version?: string
  message?: string
  [key: string]: unknown
}

export const idoitApi = {
  getConfig: () => apiClient.get<IdoitConfig>('/idoit/config').then((r) => r.data),

  updateConfig: (data: IdoitConfigUpdate) =>
    apiClient.put<IdoitConfig>('/idoit/config', data).then((r) => r.data),

  testConnection: () => apiClient.post<IdoitTestResult>('/idoit/test-connection').then((r) => r.data),

  testMapping: () => apiClient.post<IdoitTestResult>('/idoit/test-mapping').then((r) => r.data),
}
