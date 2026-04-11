import apiClient from './client'

export type CredentialType = 'linux_ssh' | 'windows_winrm'

export interface Credential {
  id: number
  name: string
  credential_type: CredentialType
  username: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface CredentialCreate {
  name: string
  credential_type: CredentialType
  username: string
  secret: string
  description?: string
}

export interface CredentialUpdate {
  name?: string
  credential_type?: CredentialType
  username?: string
  secret?: string
  description?: string
}

export interface CredentialTestResult {
  success: boolean
  message: string
  latency_ms: number | null
}

export const credentialsApi = {
  list: () =>
    apiClient.get<Credential[]>('/credentials'),

  create: (data: CredentialCreate) =>
    apiClient.post<Credential>('/credentials', data),

  get: (id: number) =>
    apiClient.get<Credential>(`/credentials/${id}`),

  update: (id: number, data: CredentialUpdate) =>
    apiClient.put<Credential>(`/credentials/${id}`, data),

  delete: (id: number) =>
    apiClient.delete(`/credentials/${id}`),

  test: (id: number, targetIp: string) =>
    apiClient.post<CredentialTestResult>(`/credentials/${id}/test`, { target_ip: targetIp }),
}
