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
  await page.route('**/api/devices**', async (route) => {
    if (!new URL(route.request().url()).pathname.endsWith('/api/devices')) return route.fallback()
    await route.fulfill({ json: { items: [device], total: 1, online: 1, offline: 0, unregistered: 0, archived: 0 } })
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
          inferred_device_class: 'Workstation',
          inference_confidence: 'low',
          inference_reasons: ['Generic mDNS multicast traffic'],
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
          inferred_device_class: 'Workstation',
          inference_confidence: 'low',
          inference_reasons: ['Generic mDNS multicast traffic'],
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
  await expect(page.locator('#device-passive-discovery').getByText('Workstation · low')).toBeVisible()
  await expect(page.locator('#device-passive-discovery').getByRole('button', { name: /multicast.*details/i })).toBeVisible()
  await page.locator('#device-passive-discovery').scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${screenshotDir}/passive-discovery-dedupe.png`, fullPage: true })
  await page.locator('#device-passive-discovery').getByRole('button', { name: /multicast.*details/i }).click()
  await expect(page.getByRole('dialog', { name: 'MULTICAST observation' })).toBeVisible()
  await expect(page.getByText('Multicast discovery detail')).toBeVisible()
  await expect(page.getByText('Generic mDNS multicast traffic').first()).toBeVisible()
  await expect(page.getByText('"destination_port": 9999')).toBeVisible()
  await expect(page.getByText('"source_port": 43000')).toBeVisible()
  await page.screenshot({ path: `${screenshotDir}/passive-discovery-detail.png`, fullPage: true })
})

test('device detail danger zone can archive a device manually', async ({ page }) => {
  let archived = false

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
  await page.route('**/api/devices**', async (route) => {
    const url = new URL(route.request().url())
    if (!url.pathname.endsWith('/api/devices')) return route.fallback()
    await route.fulfill({ json: { items: [device], total: 1, online: 1, offline: 0, unregistered: 0, archived: 0 } })
  })
  await page.route('**/api/devices/1/archive', async (route) => {
    archived = true
    await route.fulfill({ json: { ...device, is_archived: true, is_online: false, archived_at: now } })
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
    await route.fulfill({ json: [] })
  })

  page.once('dialog', (dialog) => dialog.accept())
  await page.goto('/devices/1')
  await page.getByRole('button', { name: 'Archive Device' }).click()

  await expect.poll(() => archived).toBe(true)
  await expect(page.getByRole('button', { name: 'Already archived' })).toBeVisible()
  await page.screenshot({ path: `${screenshotDir}/device-danger-zone-archive.png`, fullPage: true })
})

test('enabling i-doit feature does not load i-doit config before settings are saved', async ({ page }) => {
  let idoitConfigRequests = 0

  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { username: 'admin', force_password_change: false } })
  })
  await page.route('**/api/settings', async (route) => {
    await route.fulfill({ json: { ...settings, advanced_view_enabled: false, show_cmdb_integrations: false } })
  })
  await page.route('**/api/settings/ui', async (route) => {
    await route.fulfill({ json: { message: 'UI settings updated' } })
  })
  await page.route('**/api/notifications/unread-count', async (route) => {
    await route.fulfill({ json: { count: 0 } })
  })
  await page.route('**/api/settings/update/check', async (route) => {
    await route.fulfill({ json: { current_version: '1.5.4', latest_version: '1.5.4', release_url: '', update_available: false } })
  })
  await page.route('**/api/idoit/config', async (route) => {
    idoitConfigRequests += 1
    await route.fulfill({
      json: {
        idoit_enabled: false,
        idoit_base_url: '',
        idoit_jsonrpc_path: '/src/jsonrpc.php',
        idoit_portal_url: '',
        idoit_api_key_configured: false,
        idoit_basic_username: '',
        idoit_basic_password_configured: false,
        idoit_timeout_seconds: 15,
        idoit_default_object_type: 'C__OBJTYPE__CLIENT',
        idoit_auto_sync_enabled: false,
        idoit_sync_scope: 'all',
        idoit_create_policy: 'match_only',
        idoit_sync_interval_minutes: 60,
        idoit_offline_retire_days: 7,
        idoit_sync_status_field: '',
        idoit_mapping_json: '{}',
        idoit_mapping_raw: '{}',
        idoit_mapping_parsed: {},
        idoit_mapping_parse_error: null,
        mapping_errors: [],
        scheduler: { running: false, next_run_at: null },
      },
    })
  })
  await page.route('**/api/idoit/logs**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/devices**', async (route) => {
    if (!new URL(route.request().url()).pathname.endsWith('/api/devices')) return route.fallback()
    await route.fulfill({ json: { items: [], total: 0, online: 0, offline: 0, unregistered: 0, archived: 0 } })
  })
  await page.route('**/api/scan-nodes**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/**', async (route) => {
    await route.fulfill({ json: [] })
  })

  await page.goto('/settings')
  await page.getByRole('button', { name: 'Features' }).click()
  await page.getByRole('button', { name: /Enable advanced view/ }).click()
  await page.getByRole('button', { name: /Show CMDB and i-doit features/ }).click()
  await page.screenshot({ path: `${screenshotDir}/idoit-feature-toggle-before-save.png`, fullPage: true })

  await expect.poll(() => idoitConfigRequests).toBe(0)

  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect.poll(() => idoitConfigRequests).toBe(1)
})

test('settings expose device retention archive and delete controls', async ({ page }) => {
  let savedRetention: Record<string, unknown> | null = null

  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { username: 'admin', force_password_change: false } })
  })
  await page.route('**/api/settings', async (route) => {
    await route.fulfill({ json: settings })
  })
  await page.route('**/api/settings/device-retention', async (route) => {
    savedRetention = await route.request().postDataJSON()
    await route.fulfill({ json: { message: 'Device retention settings updated' } })
  })
  await page.route('**/api/notifications/unread-count', async (route) => {
    await route.fulfill({ json: { count: 0 } })
  })
  await page.route('**/api/settings/update/check', async (route) => {
    await route.fulfill({ json: { current_version: '1.5.4', latest_version: '1.5.4', release_url: '', update_available: false } })
  })
  await page.route('**/api/devices**', async (route) => {
    if (!new URL(route.request().url()).pathname.endsWith('/api/devices')) return route.fallback()
    const archivedOnly = new URL(route.request().url()).searchParams.get('archived_only') === 'true'
    await route.fulfill({
      json: {
        items: archivedOnly ? [{ ...device, id: 2, label: 'Archived NAS', is_archived: true, archived_at: '2026-05-01T12:00:00Z' }] : [device],
        total: 1,
        online: 1,
        offline: 0,
        unregistered: 0,
        archived: 1,
      },
    })
  })
  await page.route('**/api/scan-nodes**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/**', async (route) => {
    await route.fulfill({ json: [] })
  })

  await page.goto('/settings')
  await page.getByRole('button', { name: 'Network Discovery' }).click()
  await expect(page.getByRole('heading', { name: 'Device retention' })).toBeVisible()
  await page.getByText('Archive after inactive days').locator('..').getByRole('spinbutton').fill('14')
  await page.getByText('Delete archived after days').locator('..').getByRole('spinbutton').fill('60')
  await page.screenshot({ path: `${screenshotDir}/device-retention-settings.png`, fullPage: true })
  await page.getByRole('button', { name: 'Save device retention' }).click()
  await expect.poll(() => savedRetention).toEqual({
    device_archive_after_days: 14,
    device_delete_archived_after_days: 60,
  })

  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Archived' })).toBeVisible()
  await page.getByRole('button', { name: 'Archived' }).click()
  await expect(page.getByText('Archived NAS')).toBeVisible()
  await page.screenshot({ path: `${screenshotDir}/device-retention-archived-filter.png`, fullPage: true })
})
