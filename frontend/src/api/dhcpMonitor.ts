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
  is_authorized: boolean
  authorized_server_id: number | null
  authorized_server_name: string | null
  observed_at: string
}

export interface DhcpAuthorizedServer {
  id: number
  name: string
  server_ip: string | null
  server_mac: string | null
  enabled: boolean
  note: string | null
  created_at: string
  updated_at: string | null
}

export interface DhcpAuthorizedServerPayload {
  name: string
  server_ip?: string | null
  server_mac?: string | null
  enabled?: boolean
  note?: string | null
}

export type DhcpAuthorizedServerUpdatePayload = Partial<DhcpAuthorizedServerPayload>

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

  async authorizedServers(): Promise<DhcpAuthorizedServer[]> {
    const res = await apiClient.get<DhcpAuthorizedServer[]>('/dhcp-monitor/authorized-servers')
    return res.data
  },

  async createAuthorizedServer(payload: DhcpAuthorizedServerPayload): Promise<DhcpAuthorizedServer> {
    const res = await apiClient.post<DhcpAuthorizedServer>('/dhcp-monitor/authorized-servers', payload)
    return res.data
  },

  async updateAuthorizedServer(id: number, payload: DhcpAuthorizedServerUpdatePayload): Promise<DhcpAuthorizedServer> {
    const res = await apiClient.put<DhcpAuthorizedServer>(`/dhcp-monitor/authorized-servers/${id}`, payload)
    return res.data
  },

  async deleteAuthorizedServer(id: number): Promise<MessageResponse> {
    const res = await apiClient.delete<MessageResponse>(`/dhcp-monitor/authorized-servers/${id}`)
    return res.data
  },

  async capture(seconds = 20): Promise<MessageResponse> {
    const res = await apiClient.post<MessageResponse>('/dhcp-monitor/capture', null, { params: { seconds } })
    return res.data
  },

  async sniffRequests(seconds = 30): Promise<MessageResponse> {
    const res = await apiClient.post<MessageResponse>('/dhcp-monitor/sniff-requests', null, { params: { seconds } })
    return res.data
  },

  async status(): Promise<DhcpMonitorStatus> {
    const res = await apiClient.get<DhcpMonitorStatus>('/dhcp-monitor/status')
    return res.data
  },
}
