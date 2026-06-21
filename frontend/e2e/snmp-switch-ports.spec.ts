import { expect, test, type Page } from '@playwright/test'

const now = '2026-06-01T19:45:00Z'
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
  show_services_nav: false,
  show_dhcp_monitor_nav: false,
  show_plugin_api: true,
  show_passive_discovery: true,
  show_mdns_discovery: true,
  show_ssdp_discovery: true,
  show_tls_checks: false,
  show_ping_history: false,
  show_build_info: false,
  app_version: '1.5.8',
  build_code: 'test',
  build_commit: 'test',
  build_branch: 'test',
  build_created: now,
  https_enabled: false,
  https_configured: false,
  https_port: 443,
  https_redirect_http: false,
}

const switchDevice = {
  id: 1,
  mac_address: '70:A7:41:00:10:02',
  ip_address: '192.168.10.2',
  hostname: 'core-switch.local',
  label: 'Core Switch',
  device_class: 'Switch',
  vendor: 'Ubiquiti',
  segment_id: 1,
  segment_name: 'Infrastructure',
  segment_color: '#2563eb',
  is_dhcp: false,
  purpose: 'PoE access switch for office, lab and media devices.',
  description: 'UniFi 24-port switch with SNMP topology polling enabled.',
  location: 'Network rack',
  responsible: 'NetOps Team',
  password_location: 'Vault',
  os_info: 'UniFi Switch OS',
  asset_tag: 'NET-SW-01',
  notes: 'SNMP profile polls interfaces, MAC table and VLAN membership.',
  cmdb_id: 'LL-00042',
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
  first_seen: '2026-05-18T12:00:00Z',
  last_seen: now,
  latest_scan: {
    id: 7,
    scanned_at: now,
    open_ports: [
      { port: 22, protocol: 'tcp', service: 'ssh', state: 'open' },
      { port: 443, protocol: 'tcp', service: 'https', state: 'open' },
    ],
    ssh_available: true,
    rdp_available: false,
    http_available: false,
    https_available: true,
  },
  services: [],
  ip_history: [],
}

const switchPorts = {
  switch: {
    id: 1,
    name: 'Core Switch',
    host: '192.168.10.2',
    device_id: 1,
    profile_id: 1,
    enabled: true,
    sys_name: 'USW-24-Core',
    sys_descr: 'Ubiquiti UniFi Switch 24 PoE',
    sys_object_id: '1.3.6.1.4.1.41112.1.6',
    vendor: 'UniFi / Ubiquiti',
    vendor_key: 'ubiquiti',
    vendor_notes: null,
    last_poll_at: now,
    last_error: null,
    interface_count: 24,
    mac_count: 11,
  },
  has_visualization: true,
  ports: Array.from({ length: 24 }, (_, index) => {
    const portNumber = index + 1
    const endpointMap: Record<number, Array<Record<string, string | number>>> = {
      1: [{ mac_address: '3C:52:82:10:00:01', vlan: '10', device_id: 2, device_label: 'Office AP', last_seen_at: now }],
      2: [{ mac_address: 'AA:BB:CC:00:00:02', vlan: '10', last_seen_at: now }],
      3: [{ mac_address: '00:11:32:44:55:66', vlan: '20', device_id: 3, device_label: 'NAS-01', last_seen_at: now }],
      5: [{ mac_address: 'B8:27:EB:AA:BB:CC', vlan: '30', device_id: 4, device_label: 'Home Assistant', last_seen_at: now }],
      8: [{ mac_address: 'D8:3A:DD:44:55:66', vlan: '40', device_id: 5, device_label: 'Media Bridge', last_seen_at: now }],
      12: [{ mac_address: 'F4:92:BF:10:20:30', vlan: '10', device_id: 6, device_label: 'Desk Dock', last_seen_at: now }],
      16: [{ mac_address: 'AC:DE:48:00:11:22', vlan: '50', device_id: 7, device_label: 'Lab Node', last_seen_at: now }],
    }
    const endpoints = endpointMap[portNumber] ?? []
    return {
      if_index: portNumber,
      name: `Port ${portNumber}`,
      description: portNumber <= 16 ? `Gi1/0/${portNumber}` : `SFP${portNumber - 16}`,
      alias: endpoints[0]?.device_label ? String(endpoints[0].device_label) : '',
      admin_status: 'up',
      oper_status: endpoints.length > 0 ? 'up' : 'down',
      speed_bps: portNumber <= 16 ? 1_000_000_000 : 10_000_000_000,
      in_unicast_packets: 12000 + portNumber,
      in_non_unicast_packets: 120 + portNumber,
      out_unicast_packets: 18000 + portNumber,
      out_non_unicast_packets: 240 + portNumber,
      in_discards: portNumber === 3 ? 2 : 0,
      out_discards: 0,
      in_errors: portNumber === 3 ? 1 : 0,
      out_errors: 0,
      unknown_protocols: 0,
      crc_errors: portNumber === 3 ? 4 : 0,
      collision_errors: portNumber === 3 ? 2 : 0,
      fragment_errors: 0,
      is_active: endpoints.length > 0,
      endpoints,
      last_seen_at: now,
    }
  }),
}

const ciscoIpScanDevice = {
  ...switchDevice,
  id: 1,
  mac_address: 'ip:cisco-sg500x',
  ip_address: '192.168.10.30',
  hostname: 'sg500x-01',
  label: 'Cisco SG500X',
  device_class: 'Switch',
  vendor: 'Cisco',
  purpose: 'Access switch found by IP scan and enriched by SNMP identity.',
  description: 'Cisco SG500X with IF-MIB inventory but no exposed bridge MAC table.',
  location: 'Lab rack',
  os_info: 'Cisco Small Business SG500X',
  asset_tag: 'NET-SW-30',
  notes: 'SNMP poll found interfaces; endpoint mapping waits for BRIDGE-MIB/Q-BRIDGE-MIB.',
}

const ciscoInterfaceOnlyPorts = {
  switch: {
    id: 10,
    name: 'Cisco SG500X',
    host: '192.168.10.30',
    device_id: null,
    profile_id: 1,
    enabled: true,
    sys_name: 'sg500x-01',
    sys_descr: 'Cisco SG500X-24P 24-Port Gigabit Stackable Managed Switch',
    sys_object_id: '1.3.6.1.4.1.9.6.1.89.24',
    vendor: 'Cisco',
    vendor_key: 'cisco',
    vendor_notes: null,
    last_poll_at: now,
    last_error: null,
    interface_count: 12,
    mac_count: 0,
  },
  has_visualization: true,
  ports: Array.from({ length: 12 }, (_, index) => {
    const portNumber = index + 1
    return {
      if_index: portNumber,
      name: `Gi1/1/${portNumber}`,
      description: `GigabitEthernet1/1/${portNumber}`,
      alias: portNumber === 1 ? 'uplink' : '',
      admin_status: 'up',
      oper_status: portNumber <= 4 ? 'up' : 'down',
      speed_bps: 1_000_000_000,
      in_unicast_packets: 2500 + portNumber,
      in_non_unicast_packets: 20 + portNumber,
      out_unicast_packets: 3600 + portNumber,
      out_non_unicast_packets: 22 + portNumber,
      in_discards: 0,
      out_discards: 0,
      in_errors: 0,
      out_errors: 0,
      unknown_protocols: 0,
      crc_errors: portNumber === 2 ? 3 : 0,
      collision_errors: 0,
      fragment_errors: 0,
      is_active: portNumber <= 4,
      endpoints: [],
      last_seen_at: now,
    }
  }),
}

async function mockDeviceDetail(page: Page, device: Record<string, unknown>, ports: Record<string, unknown>) {
  await page.setViewportSize({ width: 1440, height: 1150 })
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
    await route.fulfill({ json: { current_version: '1.5.8', latest_version: '1.5.8', release_url: '', update_available: false } })
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
  await page.route('**/api/devices/1/passive-discovery?**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/credentials', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/devices/1/ports', async (route) => {
    await route.fulfill({ json: ports })
  })
}

test('device overview shows SNMP switch ports in context', async ({ page }) => {
  await mockDeviceDetail(page, switchDevice, switchPorts)

  await page.goto('/devices/1')
  await expect(page.getByRole('heading', { name: 'Core Switch' })).toBeVisible()
  await expect(page.locator('#device-switch-ports')).toBeVisible()
  await expect(page.locator('#device-switch-ports').getByText('Office AP')).toBeVisible()
  await expect(page.locator('#device-switch-ports').getByText('Err 4/2/0')).toBeVisible()
  const unlabeledPortTitle = await page.locator('#device-switch-ports button').filter({ hasText: 'Gi1/0/2' }).getAttribute('title')
  expect(unlabeledPortTitle).toContain('- AA:BB:CC:00:00:02 · VLAN 10')
  expect((unlabeledPortTitle?.match(/AA:BB:CC:00:00:02/g) ?? []).length).toBe(1)
  await page.screenshot({ path: `${screenshotDir}/lanlens-snmp-switch-ports.png`, fullPage: false })
})

test('device overview shows interface-only SNMP ports for IP scan switches', async ({ page }) => {
  await mockDeviceDetail(page, ciscoIpScanDevice, ciscoInterfaceOnlyPorts)

  await page.goto('/devices/1')
  await expect(page.getByRole('heading', { name: 'Cisco SG500X' })).toBeVisible()
  await expect(page.locator('#device-switch-ports')).toBeVisible()
  await expect(page.locator('#device-switch-ports').getByText('MAC/VLAN endpoints appear when bridge tables are available.')).toBeVisible()
  await expect(page.locator('#device-switch-ports').getByText('Gi1/1/1', { exact: true })).toBeVisible()
  await page.screenshot({ path: `${screenshotDir}/lanlens-snmp-interface-only-ports.png`, fullPage: false })
})
