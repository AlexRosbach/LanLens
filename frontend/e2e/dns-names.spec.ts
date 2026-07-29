import { expect, test } from '@playwright/test'

const now = '2026-07-29T12:00:00Z'
const baseSettings = {
  advanced_view_enabled: false,
  show_cmdb_integrations: false,
  show_services_nav: false,
  show_dhcp_monitor_nav: false,
  show_network_topology_nav: false,
  show_plugin_api: false,
  show_passive_discovery: false,
  show_mdns_discovery: false,
  show_ssdp_discovery: false,
  show_tls_checks: false,
  show_ping_history: false,
  show_build_info: false,
  show_debug_tools: false,
  app_version: '1.5.9',
  build_code: '20260729.0007',
  build_commit: 'test',
  build_branch: 'feature/1.5.9-dns-names',
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
  hostname: 'server01.example.test',
  preferred_name: 'application-server',
  preferred_name_mode: 'manual',
  display_name: 'application-server',
  label: null,
  device_class: 'Server',
  vendor: 'Example Devices',
  segment_id: null,
  segment_name: 'Server Network',
  segment_color: '#6366f1',
  is_dhcp: false,
  purpose: 'Application hosting',
  description: '',
  location: 'Datacenter A',
  responsible: 'Platform Team',
  password_location: '',
  os_info: 'Linux',
  asset_tag: 'SRV-001',
  notes: '',
  cmdb_id: 'DEV-0001',
  ignored: false,
  notifications_muted: false,
  maintenance_until: null,
  maintenance_note: null,
  is_archived: false,
  archived_at: null,
  idoit_enabled: false,
  idoit_sync_enabled: false,
  is_registered: true,
  is_new: false,
  is_online: true,
  first_seen: now,
  last_seen: now,
  latest_scan: null,
  services: [],
  ip_history: [],
}

async function commonRoutes(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/me', (route) => route.fulfill({ json: { username: 'admin', force_password_change: false } }))
  await page.route('**/api/settings', (route) => route.fulfill({ json: baseSettings }))
  await page.route('**/api/settings/update/check', (route) => route.fulfill({ json: { current_version: '1.5.9', latest_version: '1.5.9', release_url: '', update_available: false } }))
  await page.route('**/api/notifications/unread-count', (route) => route.fulfill({ json: { count: 0 } }))
  await page.route('**/api/client-errors', (route) => route.fulfill({ json: { ok: true } }))
  await page.route('**/api/devices', (route) => route.fulfill({ json: { items: [device], total: 1, online: 1, offline: 0, unregistered: 0, archived: 0 } }))
}

test('device shows DNS aliases separately and uses only the preferred name', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1100 })
  await commonRoutes(page)
  await page.route('**/api/devices/1/mark-viewed', (route) => route.fulfill({ json: { message: 'ok' } }))
  await page.route('**/api/devices/1/ip-history', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/devices/1/timeline', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/devices/1/deep-scan/**', (route) => route.fulfill({ json: route.request().url().includes('/config') ? {} : [] }))
  await page.route('**/api/credentials', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/devices/1', (route) => route.fulfill({ json: device }))
  await page.route('**/api/dns-names/config', (route) => route.fulfill({ json: {
    dns_names_enabled: true, enabled: false, server: '', zones: [], credential_id: null,
    interval_minutes: 60, last_sync_at: null, last_error: '',
  } }))
  await page.route('**/api/dns-names/devices/1**', (route) => route.fulfill({ json: [
    { id: 1, device_id: 1, name: 'server01.example.test', record_type: 'A', source: 'microsoft_dns', canonical_name: null, address: '192.0.2.40', status: 'active', first_seen: now, last_seen: now },
    { id: 2, device_id: 1, name: 'portal.example.test', record_type: 'CNAME', source: 'microsoft_dns', canonical_name: 'server01.example.test', address: null, status: 'active', first_seen: now, last_seen: now },
  ] }))

  await page.goto('/devices/1')
  await expect(page.getByRole('heading', { name: 'application-server' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'DNS names and aliases' })).toBeVisible()
  await expect(page.getByText('portal.example.test')).toBeVisible()
  await expect(page.getByText('→ server01.example.test')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('device-dns-names.png'), fullPage: true })
})

test('settings exposes optional read-only Microsoft DNS configuration', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1100 })
  await commonRoutes(page)
  await page.route('**/api/credentials', (route) => route.fulfill({ json: [
    { id: 7, name: 'DNS read-only', credential_type: 'windows_winrm', auth_method: 'password', username: 'svc_dns_reader', description: 'Synthetic test credential', created_at: now, updated_at: now },
  ] }))
  await page.route('**/api/dns-names/config', (route) => route.fulfill({ json: {
    dns_names_enabled: true, enabled: true, server: 'dns01.example.test',
    zones: ['example.test'], credential_id: 7, interval_minutes: 60,
    last_sync_at: now, last_error: '',
  } }))

  await page.goto('/settings')
  await page.getByRole('button', { name: 'Network Discovery' }).click()
  await expect(page.getByRole('heading', { name: 'DNS names and Microsoft DNS' })).toBeVisible()
  await expect(page.locator('input[value="dns01.example.test"]')).toBeVisible()
  await expect(page.locator('textarea[placeholder*="example.local"]')).toHaveValue('example.test')
  await page.screenshot({ path: testInfo.outputPath('settings-microsoft-dns.png'), fullPage: true })
})
