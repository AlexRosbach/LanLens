import { expect, test } from '@playwright/test'

const now = '2026-11-25T12:00:00Z'
const settings = {
  advanced_view_enabled: true,
  show_cmdb_integrations: true,
  show_services_nav: true,
  show_applications_nav: true,
  show_dhcp_monitor_nav: false,
  show_network_topology_nav: true,
  show_plugin_api: false,
  show_passive_discovery: false,
  show_mdns_discovery: false,
  show_ssdp_discovery: false,
  show_tls_checks: true,
  show_ping_history: true,
  show_build_info: true,
  show_debug_tools: false,
  show_vsphere: true,
  debug_log_level: 'warning',
  app_version: '1.7.0',
  build_code: 'test',
  build_commit: 'test',
  build_branch: 'test',
  build_created: now,
}

test('applications inventory remains discoverable, filterable and drillable', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 980 })
  await page.route('**/api/auth/me', route => route.fulfill({ json: { username: 'admin', force_password_change: false } }))
  await page.route('**/api/settings', route => route.fulfill({ json: settings }))
  await page.route('**/api/notifications/unread-count', route => route.fulfill({ json: { count: 0 } }))
  await page.route('**/api/client-errors', route => route.fulfill({ json: { ok: true } }))
  await page.route('**/api/inventory/applications**', route => {
    const url = new URL(route.request().url())
    if (url.searchParams.get('application_id')) {
      return route.fulfill({ json: {
        products: [], devices: [], total: 1, product_count: 1, device_count: 1, installation_count: 1,
        installations: [{ device_id: 7, device_name: 'Demo Linux Server', ip_address: '192.0.2.70', version: '1.7.0', architecture: 'x64', observed_at: now, source: 'agent' }],
      } })
    }
    return route.fulfill({ json: {
      total: 1, product_count: 1, device_count: 1, installation_count: 1, devices: [], installations: [],
      products: [{ id: 'lanlens', name: 'LanLens Agent', publisher: 'LanLens', versions: ['1.7.0'], device_count: 1, installation_count: 1 }],
    } })
  })

  await page.goto('/applications')
  await expect(page.getByRole('heading', { name: 'Applications' })).toBeVisible()
  await expect(page.getByRole('button', { name: /LanLens Agent/ })).toBeVisible()
  await expect(page.getByText('1 / 1 Device')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('applications-inventory.png'), fullPage: true })

  await page.getByRole('button', { name: /LanLens Agent/ }).click()
  await expect(page.getByText('Demo Linux Server', { exact: true })).toBeVisible()
  await expect(page.getByText('192.0.2.70', { exact: true })).toBeVisible()
})
