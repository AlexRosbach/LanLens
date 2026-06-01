import { expect, test } from '@playwright/test'

const screenshotDir = 'test-results'

const settings = {
  dhcp_start: '192.168.1.10',
  dhcp_end: '192.168.1.200',
  scan_start: '192.168.1.1',
  scan_end: '192.168.1.254',
  scan_additional_targets: '10.10.20.0/24',
  scan_interval_minutes: 30,
  passive_discovery_background_enabled: true,
  passive_discovery_interval_minutes: 15,
  passive_discovery_capture_seconds: 30,
  ping_monitor_enabled: true,
  ping_monitor_interval_minutes: 5,
  device_archive_after_days: 45,
  device_delete_archived_after_days: 180,
  port_scan_range: 'top:1000',
  telegram_bot_token: '',
  telegram_chat_id: '',
  telegram_enabled: false,
  notify_telegram_update: false,
  network_interface: '',
  notify_on_device_online: false,
  notify_on_device_offline: false,
  notify_on_new_device: false,
  server_url: 'https://lanlens.example.test',
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
  show_tls_checks: true,
  show_ping_history: true,
  show_build_info: false,
  app_version: '1.5.5',
  build_code: 'test',
  build_commit: 'test',
  build_branch: 'test',
  build_created: '2026-06-01T21:45:00Z',
  https_enabled: false,
  https_configured: false,
  https_port: 443,
  https_redirect_http: false,
}

test('settings groups automation and keeps network discovery focused', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 980 })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { username: 'admin', force_password_change: false } })
  })
  await page.route('**/api/settings', async (route) => {
    await route.fulfill({ json: settings })
  })
  await page.route('**/api/notifications/unread-count', async (route) => {
    await route.fulfill({ json: { count: 0 } })
  })
  await page.route('**/api/passive-discovery/observations**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/scan-nodes**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/profiles**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/switches**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/endpoints**', async (route) => {
    await route.fulfill({ json: [] })
  })

  await page.goto('/settings')

  await expect(page.getByRole('button', { name: 'Automation' })).toBeVisible()
  await page.getByRole('button', { name: 'Automation' }).click()
  await expect(page.getByRole('heading', { name: 'Automation and retention' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Device retention' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Passive discovery background job' })).toBeVisible()

  await page.screenshot({ path: `${screenshotDir}/settings-automation.png`, fullPage: false })

  await page.getByRole('button', { name: 'Network Discovery' }).click()
  await expect(page.getByRole('heading', { name: 'Discovery ranges' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Device retention' })).not.toBeVisible()

  await page.screenshot({ path: `${screenshotDir}/settings-network-discovery.png`, fullPage: false })
})
