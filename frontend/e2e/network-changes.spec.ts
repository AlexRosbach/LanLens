import { expect, test } from '@playwright/test'

const now = '2026-06-01T20:30:00Z'
const screenshotDir = process.env.LANLENS_E2E_OUTPUT_DIR ?? 'test-results'

const settings = {
  dhcp_start: '',
  dhcp_end: '',
  scan_start: '',
  scan_end: '',
  scan_additional_targets: '',
  scan_interval_minutes: 60,
  passive_discovery_background_enabled: false,
  passive_discovery_interval_minutes: 15,
  passive_discovery_capture_seconds: 30,
  ping_monitor_enabled: false,
  ping_monitor_interval_minutes: 5,
  device_archive_after_days: 30,
  device_delete_archived_after_days: 90,
  port_scan_range: '1-1024',
  telegram_bot_token: '',
  telegram_chat_id: '',
  telegram_enabled: false,
  notify_telegram_update: false,
  network_interface: '',
  notify_on_device_online: false,
  notify_on_device_offline: false,
  notify_on_new_device: false,
  notify_on_network_changes: false,
  server_url: '',
  smtp_host: '',
  smtp_port: 587,
  smtp_username: '',
  smtp_password: '',
  smtp_from_email: '',
  smtp_to_email: '',
  smtp_enabled: false,
  smtp_use_tls: true,
  webhook_url: '',
  webhook_url_configured: false,
  webhook_enabled: false,
  cmdb_id_prefix: 'LL',
  cmdb_id_digits: 5,
  advanced_view_enabled: true,
  show_cmdb_integrations: false,
  show_services_nav: true,
  show_dhcp_monitor_nav: true,
  show_plugin_api: true,
  show_passive_discovery: true,
  show_mdns_discovery: true,
  show_ssdp_discovery: true,
  show_tls_checks: false,
  show_ping_history: false,
  show_build_info: false,
  app_version: '1.5.6',
  build_code: 'test',
  build_commit: 'test',
  build_branch: 'test',
  build_created: now,
  https_enabled: false,
  https_configured: false,
  https_port: 443,
  https_redirect_http: false,
}

const devices = [
  {
    id: 1,
    mac_address: '00:11:22:33:44:55',
    ip_address: '192.0.2.10',
    hostname: 'nas-01.local',
    label: 'NAS-01',
    device_class: 'NAS',
    vendor: 'Example Storage',
    segment_id: null,
    segment_name: null,
    segment_color: null,
    is_dhcp: true,
    purpose: '',
    description: '',
    location: 'Rack',
    responsible: 'Platform Team',
    password_location: '',
    os_info: '',
    asset_tag: '',
    notes: '',
    cmdb_id: 'LL-00010',
    ignored: false,
    notifications_muted: false,
    maintenance_until: null,
    maintenance_note: null,
    is_archived: false,
    archived_at: null,
    idoit_enabled: false,
    idoit_sync_enabled: false,
    idoit_sync_status: null,
    idoit_object_id: null,
    idoit_sysid: null,
    idoit_object_url: null,
    idoit_last_sync_at: null,
    idoit_last_validation_at: null,
    idoit_last_error: null,
    is_registered: true,
    is_new: false,
    is_online: true,
    first_seen: now,
    last_seen: now,
    latest_scan: null,
    services: [],
    ip_history: [],
  },
  {
    id: 2,
    mac_address: '00:AA:BB:CC:DD:EE',
    ip_address: '192.0.2.1',
    hostname: 'gateway.local',
    label: 'Gateway',
    device_class: 'Router',
    vendor: 'Example Networks',
    segment_id: null,
    segment_name: null,
    segment_color: null,
    is_dhcp: false,
    purpose: '',
    description: '',
    location: 'Rack',
    responsible: 'Platform Team',
    password_location: '',
    os_info: '',
    asset_tag: '',
    notes: '',
    cmdb_id: 'LL-00001',
    ignored: false,
    notifications_muted: false,
    maintenance_until: null,
    maintenance_note: null,
    is_archived: false,
    archived_at: null,
    idoit_enabled: false,
    idoit_sync_enabled: false,
    idoit_sync_status: null,
    idoit_object_id: null,
    idoit_sysid: null,
    idoit_object_url: null,
    idoit_last_sync_at: null,
    idoit_last_validation_at: null,
    idoit_last_error: null,
    is_registered: true,
    is_new: false,
    is_online: false,
    first_seen: now,
    last_seen: now,
    latest_scan: null,
    services: [],
    ip_history: [],
  },
]

const changes = [
  {
    id: 3,
    device_id: 1,
    device_label: 'NAS-01',
    device_ip: '192.0.2.10',
    device_mac: '00:11:22:33:44:55',
    device_class: 'NAS',
    event_type: 'ip_changed',
    field_name: 'ip_address',
    old_value: '192.0.2.9',
    new_value: '192.0.2.10',
    source: 'scan',
    message: null,
    created_at: now,
  },
  {
    id: 2,
    device_id: 2,
    device_label: 'Gateway',
    device_ip: '192.0.2.1',
    device_mac: '00:AA:BB:CC:DD:EE',
    device_class: 'Router',
    event_type: 'online_state_changed',
    field_name: 'is_online',
    old_value: 'true',
    new_value: 'false',
    source: 'ping_monitor',
    message: null,
    created_at: '2026-06-01T19:15:00Z',
  },
  {
    id: 1,
    device_id: 1,
    device_label: 'NAS-01',
    device_ip: '192.0.2.10',
    device_mac: '00:11:22:33:44:55',
    device_class: 'NAS',
    event_type: 'device_updated',
    field_name: 'responsible',
    old_value: null,
    new_value: 'Platform Team',
    source: 'user',
    message: null,
    created_at: '2026-06-01T18:05:00Z',
  },
]

test('network changes page lists and filters inventory history', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 980 })
  let changesRequests = 0
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { username: 'admin', force_password_change: false } })
  })
  await page.route('**/api/settings', async (route) => {
    await route.fulfill({ json: settings })
  })
  await page.route('**/api/notifications/unread-count', async (route) => {
    await route.fulfill({ json: { count: 0 } })
  })
  await page.route('**/api/settings/update/check', async (route) => {
    await route.fulfill({ json: { current_version: '1.5.6', latest_version: '1.5.6', release_url: '', update_available: false } })
  })
  await page.route('**/api/devices**', async (route) => {
    if (!new URL(route.request().url()).pathname.endsWith('/api/devices')) return route.fallback()
    await route.fulfill({ json: { items: devices, total: 2, online: 1, offline: 1, unregistered: 0, archived: 0 } })
  })
  await page.route('**/api/inventory/changes**', async (route) => {
    changesRequests += 1
    const url = new URL(route.request().url())
    const eventType = url.searchParams.get('event_type')
    const search = url.searchParams.get('search')?.toLowerCase() ?? ''
    const filtered = changes.filter((item) => {
      if (eventType && item.event_type !== eventType) return false
      if (search && !`${item.device_label} ${item.device_ip} ${item.event_type} ${item.field_name} ${item.source}`.toLowerCase().includes(search)) return false
      return true
    })
    await route.fulfill({ json: filtered })
  })

  await page.goto('/changes')
  await expect(page.getByRole('heading', { name: 'Network changes' })).toBeVisible()
  await expect(page.getByText('NAS-01').first()).toBeVisible()
  await expect(page.getByText('Gateway').first()).toBeVisible()
  await expect(page.getByRole('button', { name: /NAS-01 192\.0\.2\.10 ip changed/ })).toBeVisible()
  await expect.poll(() => changesRequests).toBeGreaterThanOrEqual(1)

  await page.screenshot({ path: `${screenshotDir}/lanlens-network-changes.png`, fullPage: false })

  const requestsBeforeSearch = changesRequests
  await page.getByPlaceholder('Search devices, fields, sources').fill('g')
  await page.getByPlaceholder('Search devices, fields, sources').fill('ga')
  await page.getByPlaceholder('Search devices, fields, sources').fill('gateway')
  await expect(page.getByText('Gateway').first()).toBeVisible()
  await expect(page.getByText('NAS-01').first()).not.toBeVisible()
  await expect.poll(() => changesRequests).toBe(requestsBeforeSearch + 1)

  const auditExportUrl = await page.getByRole('link', { name: 'Export audit CSV' }).getAttribute('href')
  expect(auditExportUrl).not.toBeNull()
  expect(auditExportUrl).toContain('/api/inventory/changes/export')
  const exportUrl = new URL(auditExportUrl!, 'http://127.0.0.1:5173')
  expect(exportUrl.searchParams.get('format')).toBe('csv')
  expect(exportUrl.searchParams.get('search')).toBe('gateway')
  expect(exportUrl.searchParams.get('since_hours')).toBe('168')
  expect(exportUrl.searchParams.get('limit')).toBe('1000')
})
