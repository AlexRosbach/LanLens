import apiClient from './client'

export interface LoginRequest { username: string; password: string }
export interface TokenResponse { access_token: string; token_type: string; force_password_change: boolean }
export interface UserResponse { id: number; username: string; force_password_change: boolean; last_login: string | null }

export const authApi = {
  login: (data: LoginRequest) =>
    apiClient.post<TokenResponse>('/auth/login', data).then((r) => r.data),

  logout: () => apiClient.post('/auth/logout'),

  me: () => apiClient.get<UserResponse>('/auth/me').then((r) => r.data),

  changePassword: (currentPassword: string, newPassword: string) =>
    apiClient.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    }).then((r) => r.data),
}
