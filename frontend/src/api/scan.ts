import apiClient from './client'

export interface ScanRun {
  id: number
  started_at: string
  finished_at: string | null
  scan_type: string
  devices_found: number
  devices_new: number
  devices_offline: number
  status: string
  error_message: string | null
}
export interface ScanStatus { is_running: boolean; last_scan: ScanRun | null }

export const scanApi = {
  start: () => apiClient.post('/scan/start').then((r) => r.data),
  status: () => apiClient.get<ScanStatus>('/scan/status').then((r) => r.data),
  history: () => apiClient.get<ScanRun[]>('/scan/history').then((r) => r.data),
}
