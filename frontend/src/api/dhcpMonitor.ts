import apiClient from './client'

export interface DhcpObservation {
  id: number
  message_type: string | null
  server_ip: string | null
  server_mac: string | null
  client_mac: string | null
  client_hostname: string | null
  offered_ip: string | null
  requested_ip: string | null
  lease_time: number | null
  options: Record<string, unknown>
  observed_at: string
}

export interface DhcpMonitorStatus {
  is_capturing: boolean
}

export interface MessageResponse {
  message: string
  success: boolean
}

export const dhcpMonitorApi = {
  async list(limit = 100): Promise<DhcpObservation[]> {
    const res = await apiClient.get<DhcpObservation[]>('/dhcp-monitor/observations', { params: { limit } })
    return res.data
  },

  async capture(seconds = 20): Promise<MessageResponse> {
    const res = await apiClient.post<MessageResponse>('/dhcp-monitor/capture', null, { params: { seconds } })
    return res.data
  },

  async status(): Promise<DhcpMonitorStatus> {
    const res = await apiClient.get<DhcpMonitorStatus>('/dhcp-monitor/status')
    return res.data
  },
}
