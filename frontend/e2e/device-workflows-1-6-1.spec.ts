import { expect, test } from '@playwright/test'

const now = '2026-10-28T10:00:00Z'
const baseDevice = {
  id: 1,
  mac_address: 'AA:BB:CC:DD:EE:01',
  ip_address: '192.0.2.10',
  hostname: 'nas-01',
  label: 'NAS',
  device_class: 'NAS',
  vendor: 'Corrected Vendor',
  vendor_detected: 'Detected Vendor',
  vendor_override: 'Corrected Vendor',
  segment_id: null,
  segment_name: null,
  segment_color: null,
  is_dhcp: false,
  purpose: null,
  description: null,
  location: 'Rack A',
  responsible: 'Alex',
  password_location: null,
  os_info: null,
  asset_tag: null,
  notes: null,
  cmdb_id: null,
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
  manual_connect_entries: [{
    id: 11,
    device_id: 1,
    label: 'NAS Portal',
    url: 'https://nas.example.com',
    protocol: 'https',
    sort_order: 0,
    created_at: now,
    updated_at: now,
  }],
  ip_history: [],
}

const settings = {
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
  app_version: '1.6.1',
  build_code: 'test',
  build_commit: 'test',
  build_branch: 'test',
  build_created: now,
}

async function mockShell(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/me', (route) => route.fulfill({ json: { username: 'admin', force_password_change: false } }))
  await page.route('**/api/settings', (route) => route.fulfill({ json: settings }))
  await page.route('**/api/settings/update/check', (route) => route.fulfill({ json: { current_version: '1.6.1', latest_version: '1.6.1', update_available: false } }))
  await page.route('**/api/notifications/unread-count', (route) => route.fulfill({ json: { count: 0 } }))
  await page.route('**/api/client-errors', (route) => route.fulfill({ json: { ok: true } }))
}

test('dashboard bulk edits devices, starts a selected extended scan, and shows manual links', async ({ page }) => {
  const devices = [baseDevice, { ...baseDevice, id: 2, mac_address: 'AA:BB:CC:DD:EE:02', ip_address: '192.0.2.11', label: 'Server', manual_connect_entries: [] }]
  let bulkUpdatePayload: Record<string, unknown> | null = null
  let scanPayload: Record<string, unknown> | null = null
  let scanStatus = { job_id: null, status: 'idle', total: 0, completed: 0, succeeded: 0, failed: 0, skipped: 0, cancel_requested: false, started_at: null, finished_at: null }

  await mockShell(page)
  await page.route('**/api/segments', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/devices/bulk-update', async (route) => {
    bulkUpdatePayload = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({ json: { updated: 2, message: 'Updated 2 devices' } })
  })
  await page.route('**/api/devices/bulk-port-scan/status', (route) => route.fulfill({ json: scanStatus }))
  await page.route('**/api/devices/bulk-port-scan', async (route) => {
    scanPayload = route.request().postDataJSON() as Record<string, unknown>
    scanStatus = { ...scanStatus, job_id: 'job-1', status: 'running', total: 2, completed: 0, started_at: now }
    await route.fulfill({ status: 202, json: scanStatus })
  })
  await page.route('**/api/devices**', (route) => {
    if (new URL(route.request().url()).pathname !== '/api/devices') return route.fallback()
    return route.fulfill({ json: { items: devices, total: 2, online: 2, offline: 0, unregistered: 0, archived: 0 } })
  })

  await page.goto('/')
  await expect(page.getByRole('link', { name: 'NAS Portal' })).toBeVisible()
  await page.getByRole('checkbox', { name: 'Select all visible devices' }).check()
  await page.getByRole('button', { name: 'Edit selected (2)' }).click()
  await page.getByRole('checkbox', { name: 'Responsible' }).check()
  await page.getByPlaceholder('e.g. IT Admin').fill('Network Team')
  await page.getByRole('button', { name: 'Apply changes' }).click()

  await expect.poll(() => bulkUpdatePayload).toEqual({ device_ids: [1, 2], responsible: 'Network Team' })
  await page.getByRole('button', { name: 'Scan selected (2)' }).click()
  await expect.poll(() => scanPayload).toEqual({ device_ids: [1, 2] })
  await expect(page.getByText('Extended scan: 0 / 2 devices')).toBeVisible()
})

test('device detail adds a manual connection link', async ({ page }) => {
  let createPayload: Record<string, unknown> | null = null
  const device = { ...baseDevice, manual_connect_entries: [] }

  await mockShell(page)
  await page.route('**/api/devices/1/mark-viewed', (route) => route.fulfill({ json: { message: 'ok' } }))
  await page.route('**/api/devices/1/ip-history', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/devices/1/timeline', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/devices/1/deep-scan/**', (route) => route.fulfill({ json: route.request().url().includes('/config') ? {} : [] }))
  await page.route('**/api/credentials', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/dns-names/config', (route) => route.fulfill({ json: { dns_names_enabled: false, enabled: false, zones: [] } }))
  await page.route('**/api/devices/1/manual-connect', async (route) => {
    createPayload = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({ status: 201, json: { id: 22, device_id: 1, ...createPayload, sort_order: 0, created_at: now, updated_at: now } })
  })
  await page.route('**/api/devices/1', (route) => route.fulfill({ json: device }))
  await page.route('**/api/devices**', (route) => {
    if (new URL(route.request().url()).pathname !== '/api/devices') return route.fallback()
    return route.fulfill({ json: { items: [device], total: 1, online: 1, offline: 0, unregistered: 0, archived: 0 } })
  })

  await page.goto('/devices/1')
  await page.getByLabel('Label', { exact: true }).fill('Reverse proxy')
  await page.getByLabel('Connection URL').fill('https://lanlens.example.com')
  await page.getByRole('button', { name: 'Add', exact: true }).click()

  await expect.poll(() => createPayload).toMatchObject({ label: 'Reverse proxy', url: 'https://lanlens.example.com', protocol: 'https' })
  await expect(page.getByRole('link', { name: 'Reverse proxy', exact: true })).toBeVisible()
})
