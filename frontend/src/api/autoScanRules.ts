import apiClient from './client'

export interface AutoScanRule {
  id: number
  name: string
  device_class: string | null   // null = all device classes
  credential_id: number
  scan_profile: string
  interval_minutes: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface AutoScanRuleCreate {
  name: string
  device_class?: string | null
  credential_id: number
  scan_profile: string
  interval_minutes: number
  enabled?: boolean
}

export interface AutoScanRuleUpdate {
  name?: string
  device_class?: string | null
  credential_id?: number
  scan_profile?: string
  interval_minutes?: number
  enabled?: boolean
}

export const autoScanRulesApi = {
  list: () => apiClient.get<AutoScanRule[]>('/auto-scan-rules').then((r) => r.data),

  create: (data: AutoScanRuleCreate) =>
    apiClient.post<AutoScanRule>('/auto-scan-rules', data).then((r) => r.data),

  update: (id: number, data: AutoScanRuleUpdate) =>
    apiClient.put<AutoScanRule>(`/auto-scan-rules/${id}`, data).then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/auto-scan-rules/${id}`),
}
