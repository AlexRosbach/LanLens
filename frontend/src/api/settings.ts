import apiClient from './client'

export interface AllSettings {
  dhcp_start: string
  dhcp_end: string
  scan_start: string
  scan_end: string
  scan_interval_minutes: number
  port_scan_range: string
  telegram_bot_token: string
  telegram_chat_id: string
  telegram_enabled: boolean
  notify_telegram_update: boolean
  network_interface: string
  notify_on_device_online: boolean
  notify_on_device_offline: boolean
  server_url: string
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_password: string
  smtp_from_email: string
  smtp_to_email: string
  smtp_enabled: boolean
  smtp_use_tls: boolean
  cmdb_id_prefix: string
  cmdb_id_digits: number
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

  updateScanRange: (scan_start: string, scan_end: string) =>
    apiClient.put('/settings/scan-range', { scan_start, scan_end }).then((r) => r.data),

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

  updatePortScanSettings: (port_scan_range: string) =>
    apiClient.put('/settings/port-scan', { port_scan_range }).then((r) => r.data),

  updateServerUrl: (server_url: string) =>
    apiClient.put('/settings/server-url', { server_url }).then((r) => r.data),

  updateSmtp: (data: {
    smtp_host: string
    smtp_port: number
    smtp_username: string
    smtp_password: string
    smtp_from_email: string
    smtp_to_email: string
    smtp_enabled: boolean
    smtp_use_tls: boolean
  }) => apiClient.put('/settings/smtp', data).then((r) => r.data),

  testSmtp: () => apiClient.post('/settings/smtp/test').then((r) => r.data),

  updateCmdb: (prefix: string, digits: number) =>
    apiClient.put('/settings/cmdb', null, { params: { prefix, digits } }).then((r) => r.data),
}
