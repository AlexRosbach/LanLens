import apiClient from './client'

export interface AllSettings {
  dhcp_start: string
  dhcp_end: string
  scan_interval_minutes: number
  telegram_bot_token: string
  telegram_chat_id: string
  telegram_enabled: boolean
  notify_telegram_update: boolean
  network_interface: string
  notify_on_device_online: boolean
  notify_on_device_offline: boolean
  server_url: string
}

export interface UpdateCheckResponse {
  current_version: string
  latest_version: string
  release_url: string
  update_available: boolean
}

export const settingsApi = {
  get: () => apiClient.get<AllSettings>('/settings').then((r) => r.data),

  updateDhcp: (dhcp_start: string, dhcp_end: string) =>
    apiClient.put('/settings/dhcp', { dhcp_start, dhcp_end }).then((r) => r.data),

  updateScanSchedule: (scan_interval_minutes: number) =>
    apiClient.put('/settings/scan-schedule', { scan_interval_minutes }).then((r) => r.data),

  updateTelegram: (data: {
    telegram_bot_token: string
    telegram_chat_id: string
    telegram_enabled: boolean
    notify_telegram_update: boolean
  }) => apiClient.put('/settings/telegram', data).then((r) => r.data),

  testTelegram: () => apiClient.post('/settings/telegram/test').then((r) => r.data),

  checkUpdate: () => apiClient.get<UpdateCheckResponse>('/settings/update/check').then((r) => r.data),

  notifyUpdateAvailable: () =>
    apiClient.post('/settings/telegram/notify-update').then((r) => r.data),

  updateServerUrl: (server_url: string) =>
    apiClient.put('/settings/server-url', { server_url }).then((r) => r.data),
}
