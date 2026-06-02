import apiClient from './client'
import { withBasePath } from '../utils/basePath'

export interface TopologyNode {
  id: number
  label: string
  ip_address: string | null
  device_class: string
  is_online: boolean
  segment_id: number | null
  segment_name: string | null
  service_count: number
  snmp_switch?: string | null
  snmp_interface?: string | null
  snmp_vlan?: string | null
}

export interface TopologyEdge {
  source: number
  target: number
  relationship_type: string
  label?: string | null
  metadata?: Record<string, unknown> | null
}

export interface TopologyResponse {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

export interface IgnoreRule {
  id: number
  name: string
  rule_type: string
  pattern: string
  enabled: boolean
  mute_notifications: boolean
  ignore_discovery: boolean
  note?: string | null
  created_at: string
  updated_at?: string | null
}

export interface ChangeEvent {
  id: number
  device_id: number
  event_type: string
  field_name?: string | null
  old_value?: string | null
  new_value?: string | null
  source: string
  message?: string | null
  created_at: string
}

export interface NetworkChangeEvent extends ChangeEvent {
  device_label: string
  device_ip?: string | null
  device_mac?: string | null
  device_class?: string | null
}

export interface MergePreview {
  source_device_id: number
  target_device_id: number
  source_label: string
  target_label: string
  conflicts: Record<string, { source?: string | null; target?: string | null }>
  move_counts: Record<string, number>
  write_performed: boolean
}

export const inventoryApi = {
  topology: () => apiClient.get<TopologyResponse>('/inventory/topology').then((r) => r.data),
  changes: (params?: {
    event_type?: string
    device_id?: number
    source?: string
    since_hours?: number
    search?: string
    limit?: number
  }) => apiClient.get<NetworkChangeEvent[]>('/inventory/changes', { params }).then((r) => r.data),
  changesAuditExportUrl: (params?: {
    format?: 'csv' | 'json'
    event_type?: string
    device_id?: number
    source?: string
    since_hours?: number
    search?: string
    limit?: number
  }) => {
    const query = new URLSearchParams()
    query.set('format', params?.format ?? 'csv')
    Object.entries(params ?? {}).forEach(([key, value]) => {
      if (key === 'format' || value === undefined || value === null || value === '') return
      query.set(key, String(value))
    })
    return withBasePath(`/api/inventory/changes/export?${query.toString()}`)
  },
  reportUrl: (format: 'markdown' | 'csv' | 'json' = 'markdown') => withBasePath(`/api/inventory/report?format=${format}`),
  selectiveBackupUrl: () => withBasePath('/api/backups/selective'),
  ignoreRules: () => apiClient.get<IgnoreRule[]>('/ignore-rules').then((r) => r.data),
  createIgnoreRule: (data: Omit<IgnoreRule, 'id' | 'created_at' | 'updated_at'>) =>
    apiClient.post<IgnoreRule>('/ignore-rules', data).then((r) => r.data),
  updateIgnoreRule: (id: number, data: Partial<IgnoreRule>) =>
    apiClient.put<IgnoreRule>(`/ignore-rules/${id}`, data).then((r) => r.data),
  deleteIgnoreRule: (id: number) => apiClient.delete(`/ignore-rules/${id}`).then((r) => r.data),
  previewMerge: (source_device_id: number, target_device_id: number, field_strategy = 'keep_target') =>
    apiClient.post<MergePreview>('/devices/merge/preview', { source_device_id, target_device_id, field_strategy }).then((r) => r.data),
  mergeDevices: (source_device_id: number, target_device_id: number, field_strategy = 'keep_target') =>
    apiClient.post<MergePreview>('/devices/merge', { source_device_id, target_device_id, field_strategy }).then((r) => r.data),
  importPreview: (payload: unknown) => apiClient.post('/backups/selective/import-preview', payload).then((r) => r.data),
}
