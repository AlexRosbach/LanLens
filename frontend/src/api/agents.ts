import apiClient from './client'

export interface EnrollmentToken {
  id: number
  name: string
  expires_at: string | null
  revoked_at: string | null
  created_at: string
  last_used_at: string | null
}

export interface CreatedEnrollmentToken extends EnrollmentToken { token: string }

export const agentsApi = {
  listTokens: () => apiClient.get<EnrollmentToken[]>('/agents/enrollment-tokens'),
  createToken: (data: { name: string; expires_in_minutes: number | null }) =>
    apiClient.post<CreatedEnrollmentToken>('/agents/enrollment-tokens', data),
  revokeToken: (id: number) => apiClient.post<EnrollmentToken>(`/agents/enrollment-tokens/${id}/revoke`),
}
