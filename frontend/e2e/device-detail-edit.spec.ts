import { expect, test } from '@playwright/test'

const now = '2026-06-16T05:51:00Z'

const settings = {
  advanced_view_enabled: false,
  show_cmdb_integrations: false,
  show_services_nav: false,
  show_dhcp_monitor_nav: false,
  show_plugin_api: false,
  show_passive_discovery: false,
  show_mdns_discovery: false,
  show_ssdp_discovery: false,
  show_tls_checks: false,
  show_ping_history: false,
  show_build_info: false,
  cmdb_id_prefix: 'LL',
  cmdb_id_digits: 5,
  app_version: '1.5.7',
  build_code: 'test',
  build_commit: 'test',
  build_branch: 'test',
  build_created: now,
  https_enabled: false,
  https_configured: false,
  https_port: 443,
  https_redirect_http: false,
}

const device = {
  id: 1,
  mac_address: 'AA:BB:CC:DD:EE:FF',
  ip_address: '192.0.2.40',
  hostname: 'asset-01',
  label: 'Asset Label',
  device_class: 'Workstation',
  vendor: 'Example Devices',
  segment_id: null,
  segment_name: null,
  segment_color: null,
  is_dhcp: true,
  purpose: '',
  description: '',
  location: '',
  responsible: '',
  password_location: '',
  os_info: '',
  asset_tag: 'ASSET-123',
  notes: '',
  cmdb_id: null,
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
}

test('device detail saves cleared label and asset tag as null values', async ({ page }) => {
  let updatePayload: Record<string, unknown> | null = null

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
    await route.fulfill({ json: { current_version: '1.5.7', latest_version: '1.5.7', release_url: '', update_available: false } })
  })
  await page.route('**/api/client-errors', async (route) => {
    await route.fulfill({ json: { ok: true } })
  })
  await page.route('**/api/devices', async (route) => {
    await route.fulfill({ json: { items: [device], total: 1, online: 1, offline: 0, unregistered: 0, archived: 0 } })
  })
  await page.route('**/api/devices/1/mark-viewed', async (route) => {
    await route.fulfill({ json: { message: 'ok' } })
  })
  await page.route('**/api/devices/1/ip-history', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/devices/1/timeline', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/devices/1/deep-scan/**', async (route) => {
    await route.fulfill({ json: route.request().url().includes('/config') ? {} : [] })
  })
  await page.route('**/api/credentials', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/devices/1', async (route) => {
    if (route.request().method() === 'PUT') {
      updatePayload = route.request().postDataJSON() as Record<string, unknown>
      await route.fulfill({ json: { ...device, label: null, asset_tag: null } })
      return
    }
    await route.fulfill({ json: device })
  })

  await page.goto('/devices/1')
  await page.getByRole('button', { name: 'Edit' }).click()
  await page.getByPlaceholder('e.g. NAS Server, Living Room Pi').fill('')
  await page.getByPlaceholder('e.g. SRV-001').fill('')
  await page.getByRole('button', { name: 'Save' }).click()

  await expect.poll(() => updatePayload).not.toBeNull()
  expect(updatePayload?.label).toBeNull()
  expect(updatePayload?.asset_tag).toBeNull()
})
