import apiClient from './client'

export interface AllSettings {
  dhcp_start: string
  dhcp_end: string
  scan_start: string
  scan_end: string
  scan_additional_targets: string
  scan_interval_minutes: number
  passive_discovery_background_enabled: boolean
  passive_discovery_interval_minutes: number
  passive_discovery_capture_seconds: number
  port_scan_range: string
  telegram_bot_token: string
  telegram_chat_id: string
  telegram_enabled: boolean
  notify_telegram_update: boolean
  network_interface: string
  notify_on_device_online: boolean
  notify_on_device_offline: boolean
  notify_on_new_device: boolean
  server_url: string
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_password: string
  smtp_from_email: string
  smtp_to_email: string
  smtp_enabled: boolean
  smtp_use_tls: boolean
  webhook_url: string
  webhook_url_configured: boolean
  webhook_enabled: boolean
  cmdb_id_prefix: string
  cmdb_id_digits: number
  advanced_view_enabled: boolean
  show_cmdb_integrations: boolean
  show_services_nav: boolean
  show_dhcp_monitor_nav: boolean
  show_plugin_api: boolean
  show_passive_discovery: boolean
  show_mdns_discovery: boolean
  show_ssdp_discovery: boolean
  show_tls_checks: boolean
  show_ping_history: boolean
  show_build_info: boolean
  app_version: string
  build_code: string
  build_commit: string
  build_branch: string
  build_created: string
  https_enabled: boolean
  https_configured: boolean
  https_port: number
  https_redirect_http: boolean
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

  updateScanRange: (scan_start: string, scan_end: string, scan_additional_targets: string) =>
    apiClient.put('/settings/scan-range', { scan_start, scan_end, scan_additional_targets }).then((r) => r.data),

  updateScanSchedule: (scan_interval_minutes: number) =>
    apiClient.put('/settings/scan-schedule', { scan_interval_minutes }).then((r) => r.data),

  updatePassiveDiscovery: (data: {
    passive_discovery_background_enabled: boolean
    passive_discovery_interval_minutes: number
    passive_discovery_capture_seconds: number
  }) => apiClient.put('/settings/passive-discovery', data).then((r) => r.data),

  updateTelegram: (data: {
    telegram_bot_token: string
    telegram_chat_id: string
    telegram_enabled: boolean
    notify_telegram_update: boolean
    notify_on_new_device: boolean
  }) => apiClient.put('/settings/telegram', data).then((r) => r.data),

  testTelegram: () => apiClient.post('/settings/telegram/test').then((r) => r.data),

  checkUpdate: () => apiClient.get<UpdateCheckResponse>('/settings/update/check').then((r) => r.data),

  notifyUpdateAvailable: () =>
    apiClient.post('/settings/telegram/notify-update').then((r) => r.data),

  updatePortScanSettings: (port_scan_range: string) =>
    apiClient.put('/settings/port-scan', { port_scan_range }).then((r) => r.data),

  updateServerUrl: (server_url: string) =>
    apiClient.put('/settings/server-url', { server_url }).then((r) => r.data),

  updateHttps: (data: {
    enabled: boolean
    https_port: number
    redirect_http: boolean
    certificate?: File | null
    private_key?: File | null
    ca_chain?: File | null
  }) => {
    const form = new FormData()
    form.append('enabled', String(data.enabled))
    form.append('https_port', String(data.https_port))
    form.append('redirect_http', String(data.redirect_http))
    if (data.certificate) form.append('certificate', data.certificate)
    if (data.private_key) form.append('private_key', data.private_key)
    if (data.ca_chain) form.append('ca_chain', data.ca_chain)
    return apiClient.put('/settings/https', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data)
  },

  updateUi: (
    advanced_view_enabled: boolean,
    show_cmdb_integrations: boolean,
    show_services_nav: boolean,
    show_dhcp_monitor_nav: boolean,
    show_plugin_api: boolean,
    show_passive_discovery: boolean,
    show_mdns_discovery: boolean,
    show_ssdp_discovery: boolean,
    show_tls_checks: boolean,
    show_ping_history: boolean,
    show_build_info: boolean,
  ) =>
    apiClient.put('/settings/ui', {
      advanced_view_enabled,
      show_cmdb_integrations,
      show_services_nav,
      show_dhcp_monitor_nav,
      show_plugin_api,
      show_passive_discovery,
      show_mdns_discovery,
      show_ssdp_discovery,
      show_tls_checks,
      show_ping_history,
      show_build_info,
    }).then((r) => r.data),

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

  updateWebhook: (data: {
    webhook_url: string
    webhook_enabled: boolean
  }) => apiClient.put('/settings/webhook', data).then((r) => r.data),

  testWebhook: () => apiClient.post('/settings/webhook/test').then((r) => r.data),

  updateCmdb: (prefix: string, digits: number) =>
    apiClient.put('/settings/cmdb', null, { params: { prefix, digits } }).then((r) => r.data),
}
