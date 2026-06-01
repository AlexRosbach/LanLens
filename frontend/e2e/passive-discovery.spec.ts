import { expect, test } from '@playwright/test'

const now = '2026-05-31T20:30:00Z'
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
  port_scan_range: '1-1024',
  telegram_bot_token: '',
  telegram_chat_id: '',
  telegram_enabled: false,
  notify_telegram_update: false,
  network_interface: '',
  notify_on_device_online: false,
  notify_on_device_offline: false,
  notify_on_new_device: false,
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
  show_services_nav: false,
  show_dhcp_monitor_nav: false,
  show_plugin_api: false,
  show_passive_discovery: true,
  show_mdns_discovery: true,
  show_ssdp_discovery: true,
  show_tls_checks: false,
  show_ping_history: false,
  show_build_info: false,
  app_version: '1.5.4',
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
  hostname: 'printer-01',
  label: 'Printer 01',
  device_class: 'printer',
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
  asset_tag: '',
  notes: '',
  cmdb_id: null,
  ignored: false,
  notifications_muted: false,
  maintenance_until: null,
  maintenance_note: null,
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

test('device multicast discovery shows one row for repeated observations', async ({ page }) => {
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
    await route.fulfill({ json: { current_version: '1.5.4', latest_version: '1.5.4', release_url: '', update_available: false } })
  })
  await page.route('**/api/devices', async (route) => {
    await route.fulfill({ json: { items: [device], total: 1 } })
  })
  await page.route('**/api/devices/1', async (route) => {
    await route.fulfill({ json: device })
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
  await page.route('**/api/snmp/devices/1/ports', async (route) => {
    await route.fulfill({ status: 404, json: { detail: 'Not found' } })
  })
  await page.route('**/api/devices/1/passive-discovery?**', async (route) => {
    await route.fulfill({
      json: [
        {
          id: 1,
          protocol: 'multicast',
          source_ip: '192.0.2.40',
          source_mac: 'AA:BB:CC:DD:EE:FF',
          destination_ip: '239.1.1.1',
          service_name: null,
          service_type: null,
          summary: 'IPv4 multicast packet',
          metadata: { transport: 'udp', source_port: 42000, destination_port: 9999 },
          observed_at: '2026-05-31T20:25:00Z',
          linked_device_id: 1,
          linked_device_label: 'Printer 01',
        },
        {
          id: 2,
          protocol: 'multicast',
          source_ip: '192.0.2.40',
          source_mac: null,
          destination_ip: '239.1.1.1',
          service_name: null,
          service_type: null,
          summary: 'IPv4 multicast packet',
          metadata: { transport: 'udp', source_port: 43000, destination_port: 9999 },
          observed_at: now,
          linked_device_id: 1,
          linked_device_label: 'Printer 01',
        },
      ],
    })
  })

  await page.goto('/devices/1')

  await expect(page.getByText('1 unique observations')).toBeVisible()
  await expect(page.locator('#device-passive-discovery tbody tr')).toHaveCount(1)
  await page.locator('#device-passive-discovery').scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${screenshotDir}/passive-discovery-dedupe.png`, fullPage: true })
  await page.locator('#device-passive-discovery tbody tr').click()
  await expect(page.getByRole('dialog', { name: 'MULTICAST observation' })).toBeVisible()
  await expect(page.getByText('Multicast discovery detail')).toBeVisible()
  await expect(page.getByText('"destination_port": 9999')).toBeVisible()
  await expect(page.getByText('"source_port": 43000')).toBeVisible()
  await page.screenshot({ path: `${screenshotDir}/passive-discovery-detail.png`, fullPage: true })
})
