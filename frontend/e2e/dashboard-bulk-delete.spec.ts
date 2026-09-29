import { expect, test } from '@playwright/test'

const now = '2026-09-29T09:00:00Z'
const devices = [
  {
    id: 1,
    mac_address: 'ip:00000000000001',
    ip_address: '192.0.2.10',
    hostname: null,
    label: null,
    device_class: 'Unknown',
    vendor: null,
    segment_id: null,
    segment_name: null,
    segment_color: null,
    is_dhcp: false,
    is_registered: false,
    is_new: true,
    is_online: true,
    first_seen: now,
    last_seen: now,
    latest_scan: null,
    services: [],
  },
  {
    id: 2,
    mac_address: 'ip:00000000000002',
    ip_address: '192.0.2.11',
    hostname: null,
    label: null,
    device_class: 'Unknown',
    vendor: null,
    segment_id: null,
    segment_name: null,
    segment_color: null,
    is_dhcp: false,
    is_registered: false,
    is_new: true,
    is_online: true,
    first_seen: now,
    last_seen: now,
    latest_scan: null,
    services: [],
  },
]

test('dashboard bulk deletes selected devices in one request', async ({ page }) => {
  let remaining = [...devices]
  let deletePayload: { device_ids: number[] } | null = null

  await page.route('**/api/auth/me', (route) => route.fulfill({ json: { username: 'admin', force_password_change: false } }))
  await page.route('**/api/settings', (route) => route.fulfill({
    json: {
      advanced_view_enabled: false,
      show_cmdb_integrations: false,
      show_services_nav: false,
      show_dhcp_monitor_nav: false,
      show_network_topology_nav: false,
      show_plugin_api: false,
      show_build_info: false,
      app_version: '1.6.0',
      build_code: 'test',
      build_commit: 'test',
      build_branch: 'test',
      build_created: now,
    },
  }))
  await page.route('**/api/settings/update/check', (route) => route.fulfill({ json: { current_version: '1.6.0', latest_version: '1.6.0', update_available: false } }))
  await page.route('**/api/notifications/unread-count', (route) => route.fulfill({ json: { count: 0 } }))
  await page.route('**/api/segments', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/devices/bulk-delete', async (route) => {
    deletePayload = route.request().postDataJSON() as { device_ids: number[] }
    remaining = remaining.filter((device) => !deletePayload?.device_ids.includes(device.id))
    await route.fulfill({ json: { message: `Deleted ${deletePayload.device_ids.length} devices`, success: true } })
  })
  await page.route('**/api/devices**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (!pathname.endsWith('/api/devices')) return route.fallback()
    await route.fulfill({ json: { items: remaining, total: remaining.length, online: remaining.length, offline: 0, unregistered: remaining.length, archived: 0 } })
  })

  page.on('dialog', (dialog) => dialog.accept())
  await page.goto('/')
  await expect(page.getByText('192.0.2.10', { exact: true })).toBeVisible()

  await page.getByRole('checkbox', { name: 'Select all visible devices' }).check()
  await page.getByRole('button', { name: 'Delete selected (2)' }).click()

  await expect.poll(() => deletePayload).toEqual({ device_ids: [1, 2] })
  await expect(page.getByText('No devices found')).toBeVisible()
})
