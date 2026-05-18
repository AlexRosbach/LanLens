import apiClient from './client'

export interface ScanNode {
  id: number
  name: string
  site: string
  segment_label: string
  enabled: boolean
  status: string
  last_seen?: string | null
  last_ip?: string | null
  version?: string | null
  last_error?: string | null
  created_at: string
}

export interface ScanNodeProvisioning extends ScanNode {
  token: string
  install_command: string
}

export const scanNodesApi = {
  list: () => apiClient.get<ScanNode[]>('/scan-nodes').then((r) => r.data),

  create: (data: { name: string; site?: string; segment_label?: string }) =>
    apiClient.post<ScanNodeProvisioning>('/scan-nodes', data).then((r) => r.data),

  rotateToken: (id: number) =>
    apiClient.post<ScanNodeProvisioning>(`/scan-nodes/${id}/rotate-token`).then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/scan-nodes/${id}`).then((r) => r.data),
}
