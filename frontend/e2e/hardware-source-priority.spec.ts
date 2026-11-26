import { expect, test, type Page } from '@playwright/test'

const now = '2026-11-26T08:00:00Z'
const vmware = {
  name: 'Demo VM', external_id: 'vm-7', kind: 'vm', match_status: 'existing',
  observed_at: now, custom_fields: [],
  fields: { cpu_count: 8, memory_size_mib: 32768, disks: [{ disk_id: '2000', label: 'Virtual disk 1', capacity_bytes: 107374182400 }] },
}
const guestFindings = [
  { key: 'computer_system', value: { Name: 'demo-vm', Model: 'VMware Virtual Platform', NumberOfLogicalProcessors: 2, TotalPhysicalMemory: 4294967296 } },
  { key: 'processor', value: { Name: 'Guest CPU model', NumberOfCores: 2, MaxClockSpeed: 2400 } },
  { key: 'physical_memory', value: [{ Capacity: 4294967296, Speed: 3200, Manufacturer: 'Memory vendor' }] },
  { key: 'disk_drives', value: [{ Model: 'Guest disk model', Size: 42949672960, SerialNumber: 'demo-disk' }] },
].map((finding, index) => ({
  id: index + 1, device_id: 1, run_id: 1, finding_type: 'hardware', source: 'lanlens_windows_agent', collection_source: 'windows_agent', observed_at: '2026-11-26T09:00:00Z', ...finding,
}))

async function openDevice(page: Page, observations: unknown[] = [vmware], findings: unknown[] = guestFindings) {
  await page.addInitScript(() => localStorage.setItem('lanlens.language', 'en'))
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.fallback()
    let json: unknown = []
    if (path === '/api/auth/me') json = { username: 'admin', force_password_change: false }
    if (path === '/api/settings') json = { advanced_view_enabled: false, show_vsphere: true, show_cmdb_integrations: false, show_services_nav: false, show_ping_history: false, show_tls_checks: false }
    if (path === '/api/notifications/unread-count') json = { count: 0 }
    if (path === '/api/devices') json = { items: [], total: 0, online: 0, offline: 0, unregistered: 0, archived: 0 }
    if (path === '/api/dns-names/config') json = { dns_names_enabled: false, enabled: false, zones: [] }
    if (path === '/api/devices/1') json = {
      id: 1, mac_address: '02:00:00:00:00:07', ip_address: '192.0.2.7', hostname: 'demo-vm',
      label: 'Demo VM', device_class: 'Server', vendor: 'VMware', is_registered: true, is_new: false,
      is_online: true, first_seen: now, last_seen: now, latest_scan: null, services: [], manual_connect_entries: [], vsphere_inventory: observations,
    }
    if (path === '/api/devices/1/deep-scan/config') json = { device_id: 1, enabled: true, credential_id: 4, scan_profile: 'hardware_only', auto_scan_enabled: false, interval_minutes: 60, last_scan_at: null }
    if (path === '/api/credentials') json = [{ id: 4, name: 'Demo WinRM', credential_type: 'windows_winrm' }]
    if (path === '/api/devices/1/deep-scan/findings') json = findings
    if (path === '/api/devices/1/deep-scan/agent-status') json = { device_id: 1, platform: 'windows', revoked: false, last_seen_at: now, last_sequence: 2, last_run_id: 1, summary: null }
    return route.fulfill({ json })
  })
  await page.goto('/devices/1')
  const panel = page.locator('#device-deep-scan')
  await expect(panel.getByRole('button', { name: 'Hardware', exact: true })).toBeVisible()
  return panel
}

test('VMware wins hardware despite a newer guest report; source filters retain raw values', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1100 })
  const panel = await openDevice(page)
  await expect(panel.getByText(/hardware values take precedence/)).toBeVisible()
  await expect(panel.getByText('32.00 GiB', { exact: true })).toBeVisible()
  await expect(panel.getByText(/Virtual disk 1 · 100.00 GiB/)).toBeVisible()
  await expect(panel.getByText('Guest CPU model', { exact: true })).toBeVisible()
  await expect(panel).not.toContainText('2 threads')
  await expect(panel).not.toContainText('4.00 GB')
  await expect(panel).not.toContainText('40.0 GB')
  await expect(panel.getByRole('button', { name: 'VMware / vSphere · 1', exact: true }).locator('span').first()).toHaveClass(/bg-success-dim/)
  await expect(panel.getByRole('button', { name: 'WinRM · 0', exact: true })).toHaveAttribute('title', 'Active, no data yet')
  await expect(panel.getByRole('button', { name: 'WinRM · 0', exact: true }).locator('span').first()).toHaveClass(/bg-surface2/)

  await panel.scrollIntoViewIfNeeded()
  await panel.screenshot({ path: testInfo.outputPath('vmware-hardware-priority.png') })
  await panel.getByRole('button', { name: 'Windows Agent · 4', exact: true }).click()
  await expect(panel).toContainText('2 threads')
  await expect(panel).toContainText('4.00 GB')
  await expect(panel).toContainText('40.0 GB')
  await expect(panel.getByText('32.00 GiB', { exact: true })).toHaveCount(0)
  await panel.getByRole('button', { name: 'All', exact: true }).click()
  await expect(panel.getByText('32.00 GiB', { exact: true })).toBeVisible()
  await expect(panel).not.toContainText('4.00 GB')
})

test('missing VMware fields use guest hardware without replacing VMware CPU', async ({ page }) => {
  const panel = await openDevice(page, [{ ...vmware, fields: { cpu_count: 8 } }])
  await expect(panel.getByText('8', { exact: true })).toBeVisible()
  await expect(panel).toContainText('4.00 GB')
  await expect(panel).toContainText('40.0 GB')
  await expect(panel).not.toContainText('2 threads')
})

for (const [name, observations] of [
  ['stale', [{ ...vmware, match_status: 'stale' }]],
  ['ambiguous', [vmware, { ...vmware, external_id: 'vm-8' }]],
  ['invalid', [{ ...vmware, fields: { cpu_count: 0, memory_size_mib: -1, disks: [] } }]],
] as const) {
  test(`${name} VMware data leaves guest hardware authoritative`, async ({ page }) => {
    const panel = await openDevice(page, [...observations])
    await expect(panel).toContainText('2 threads')
    await expect(panel).toContainText('4.00 GB')
    await expect(panel).toContainText('40.0 GB')
    await expect(panel.getByText(/hardware values take precedence/)).toHaveCount(0)
  })
}

test('incomplete VMware disks keep guest disk sizes as fallback', async ({ page }) => {
  const panel = await openDevice(page, [{ ...vmware, fields: { cpu_count: 8, disks: [{ disk_id: '2000' }] } }])
  await expect(panel).toContainText('40.0 GB')
  await expect(panel).not.toContainText('2 threads')
})

test('Linux text findings retain hardware details without conflicting totals', async ({ page }) => {
  const findings = [
    { key: 'cpu', value: 'CPU(s): 2\nOn-line CPU(s) list: 0-1\nModel name: Demo CPU' },
    { key: 'memory', value: '               total        used        free\nMem:           4.0Gi       1.0Gi       3.0Gi' },
    { key: 'physical_memory', value: 'Memory Device\n  Size: 4096 MB\n  Speed: 3200 MT/s' },
    { key: 'disks', value: 'NAME  SIZE  TYPE  MODEL\nsda   40G   disk  Demo Drive' },
  ].map((finding, index) => ({ ...guestFindings[0], ...finding, id: index + 1, source: 'lanlens_linux_agent', collection_source: 'linux_agent' }))
  const panel = await openDevice(page, [vmware], findings)
  await expect(panel).toContainText('Demo CPU')
  await panel.getByRole('button', { name: /Show all|Expand/ }).click()
  await expect(panel).toContainText('3200 MT/s')
  await expect(panel).toContainText('Demo Drive')
  await expect(panel).not.toContainText('CPU(s): 2')
  await expect(panel).not.toContainText('4096 MB')
  await expect(panel).not.toContainText('40G')
  await panel.getByRole('button', { name: 'Linux Agent · 4 · History', exact: true }).click()
  await expect(panel).toContainText('CPU(s): 2')
  await expect(panel).toContainText('4096 MB')
  await expect(panel).toContainText('40G')
})
