import apiClient from './client'

export interface DebugLogEntry {
  id: string
  topic: 'cmdb' | 'idoit'
  source: string
  level: 'info' | 'warning' | 'error'
  device_id?: number | null
  device_name?: string | null
  mode: string
  result: string
  message?: string | null
  object_id?: string | null
  details: Record<string, unknown>
  created_at: string
}

export interface DebugLogResponse {
  topic: 'all' | 'cmdb' | 'idoit'
  level: 'info' | 'warning' | 'error' | 'debug' | 'trace'
  query: string
  entries: DebugLogEntry[]
}

export const debugApi = {
  getLogs: (params: {
    topic?: 'all' | 'cmdb' | 'idoit'
    level?: 'info' | 'warning' | 'error' | 'debug' | 'trace'
    q?: string
    limit?: number
  }) => apiClient.get<DebugLogResponse>('/debug/logs', { params }).then((r) => r.data),
}
