import { expect, test, type Page } from '@playwright/test'

const now = '2026-06-04T19:30:00Z'
const screenshotDir = process.env.LANLENS_E2E_OUTPUT_DIR ?? 'test-results'

const settings = {
  dhcp_start: '192.0.2.1',
  dhcp_end: '192.0.2.254',
  scan_start: '192.0.2.1',
  scan_end: '192.0.2.254',
  scan_additional_targets: '198.51.100.0/28',
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
  notify_on_new_device: true,
  notify_on_network_changes: true,
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
  show_cmdb_integrations: true,
  show_services_nav: true,
  show_dhcp_monitor_nav: true,
  show_network_topology_nav: true,
  show_plugin_api: true,
  show_passive_discovery: true,
  show_mdns_discovery: true,
  show_ssdp_discovery: true,
  show_tls_checks: true,
  show_ping_history: true,
  show_build_info: true,
  app_version: '1.5.8',
  build_code: 'docs',
  build_commit: 'docs',
  build_branch: 'docs',
  build_created: now,
  https_enabled: false,
  https_configured: false,
  https_port: 443,
  https_redirect_http: false,
}

const segments = [
  { id: 1, name: 'Core Infrastructure', color: '#6366f1', ip_start: '192.0.2.1', ip_end: '192.0.2.63', description: 'Routers, switches and core services', created_at: now },
  { id: 2, name: 'Servers', color: '#22c55e', ip_start: '192.0.2.64', ip_end: '192.0.2.127', description: 'Self-hosted applications and compute', created_at: now },
  { id: 3, name: 'Client Devices', color: '#f59e0b', ip_start: '192.0.2.128', ip_end: '192.0.2.199', description: 'Workstations and mobile clients', created_at: now },
  { id: 4, name: 'IoT / Cameras', color: '#06b6d4', ip_start: '192.0.2.200', ip_end: '192.0.2.254', description: 'Sensors, cameras and appliances', created_at: now },
]

const devices = [
  {
    id: 1,
    mac_address: '02:00:00:00:00:01',
    ip_address: '192.0.2.1',
    hostname: 'gateway.demo',
    label: 'Core Gateway',
    device_class: 'Router',
    vendor: 'Demo Networks',
    segment_id: 1,
    segment_name: 'Core Infrastructure',
    segment_color: '#6366f1',
    is_dhcp: false,
    purpose: 'Internet edge and routing for the demo network.',
    description: 'Gateway device with DHCP and VRRP awareness.',
    location: 'Network rack',
    responsible: 'NetOps Team',
    password_location: 'Vault',
    os_info: 'RouterOS',
    asset_tag: 'NET-RTR-01',
    notes: 'Authorized DHCP server.',
    cmdb_id: 'LL-00001',
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
    first_seen: '2026-05-17T17:59:00Z',
    last_seen: now,
    latest_scan: {
      id: 1,
      scanned_at: now,
      open_ports: [
        { port: 80, protocol: 'tcp', service: 'http', state: 'open' },
        { port: 443, protocol: 'tcp', service: 'https', state: 'open' },
      ],
      ssh_available: false,
      rdp_available: false,
      http_available: true,
      https_available: true,
    },
    services: [],
    ip_history: [],
  },
  {
    id: 2,
    mac_address: '02:00:00:00:00:02',
    ip_address: '192.0.2.10',
    hostname: 'switch-core.demo',
    label: 'Core Switch',
    device_class: 'Switch',
    vendor: 'Demo Networks',
    segment_id: 1,
    segment_name: 'Core Infrastructure',
    segment_color: '#6366f1',
    is_dhcp: false,
    purpose: 'Aggregation switch for lab and office devices.',
    description: 'SNMP target with interface and endpoint inventory.',
    location: 'Network rack',
    responsible: 'NetOps Team',
    password_location: 'Vault',
    os_info: 'Switch OS',
    asset_tag: 'NET-SW-01',
    notes: 'SNMP polling enabled.',
    cmdb_id: 'LL-00002',
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
    first_seen: '2026-05-17T18:00:00Z',
    last_seen: now,
    latest_scan: {
      id: 2,
      scanned_at: now,
      open_ports: [{ port: 22, protocol: 'tcp', service: 'ssh', state: 'open' }],
      ssh_available: true,
      rdp_available: false,
      http_available: false,
      https_available: false,
    },
    services: [],
    ip_history: [],
  },
  {
    id: 3,
    mac_address: '02:00:00:00:00:10',
    ip_address: '192.0.2.70',
    hostname: 'docker01.demo',
    label: 'Docker Host',
    device_class: 'Server',
    vendor: 'Demo Labs',
    segment_id: 2,
    segment_name: 'Servers',
    segment_color: '#22c55e',
    is_dhcp: false,
    purpose: 'Self-hosted application runtime.',
    description: 'Container host for internal tools and monitoring.',
    location: 'Rack B',
    responsible: 'Platform Team',
    password_location: 'Vault: Demo/Docker',
    os_info: 'Debian 12',
    asset_tag: 'SRV-0101',
    notes: 'Runs monitored demo services.',
    cmdb_id: 'LL-00010',
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
    first_seen: '2026-05-24T17:59:00Z',
    last_seen: now,
    latest_scan: {
      id: 3,
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
  },
  {
    id: 4,
    mac_address: '02:00:00:00:00:20',
    ip_address: '192.0.2.130',
    hostname: 'workstation-01.demo',
    label: 'Workstation 01',
    device_class: 'Workstation',
    vendor: 'Demo Devices',
    segment_id: 3,
    segment_name: 'Client Devices',
    segment_color: '#f59e0b',
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
    is_registered: false,
    is_new: true,
    is_online: true,
    first_seen: now,
    last_seen: now,
    latest_scan: {
      id: 4,
      scanned_at: now,
      open_ports: [{ port: 3389, protocol: 'tcp', service: 'rdp', state: 'open' }],
      ssh_available: false,
      rdp_available: true,
      http_available: false,
      https_available: false,
    },
    services: [],
    ip_history: [],
  },
  {
    id: 5,
    mac_address: '02:00:00:00:00:30',
    ip_address: '192.0.2.210',
    hostname: 'entry-camera.demo',
    label: 'Entry Camera',
    device_class: 'IoT',
    vendor: 'Demo IoT',
    segment_id: 4,
    segment_name: 'IoT / Cameras',
    segment_color: '#06b6d4',
    is_dhcp: false,
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
    is_online: false,
    first_seen: '2026-05-27T08:00:00Z',
    last_seen: '2026-06-04T15:30:00Z',
    latest_scan: {
      id: 5,
      scanned_at: '2026-06-04T15:30:00Z',
      open_ports: [{ port: 80, protocol: 'tcp', service: 'http', state: 'open' }],
      ssh_available: false,
      rdp_available: false,
      http_available: true,
      https_available: false,
    },
    services: [],
    ip_history: [],
  },
]

async function mockCommon(page: Page) {
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { username: 'admin', force_password_change: false } })
  })
  await page.route('**/api/settings', async (route) => {
    await route.fulfill({ json: settings })
  })
  await page.route('**/api/settings/update/check', async (route) => {
    await route.fulfill({ json: { current_version: '1.5.8', latest_version: '1.5.8', release_url: '', update_available: false } })
  })
  await page.route('**/api/notifications/unread-count', async (route) => {
    await route.fulfill({ json: { count: 0 } })
  })
  await page.route('**/api/segments', async (route) => {
    await route.fulfill({ json: segments })
  })
  await page.route('**/api/devices**', async (route) => {
    if (!new URL(route.request().url()).pathname.endsWith('/api/devices')) return route.fallback()
    await route.fulfill({ json: { items: devices, total: 5, online: 4, offline: 1, unregistered: 1, archived: 0 } })
  })
}

test('README dashboard screenshot', async ({ page }) => {
  await mockCommon(page)
  await page.goto('/')
  await expect(page.getByRole('button', { name: /Core Gateway/ })).toBeVisible()
  await page.screenshot({ path: `${screenshotDir}/lanlens-dashboard.png`, fullPage: false })
})

test('README device detail screenshot', async ({ page }) => {
  await mockCommon(page)
  await page.route('**/api/devices/3', async (route) => {
    await route.fulfill({ json: devices[2] })
  })
  await page.route('**/api/devices/3/mark-viewed', async (route) => {
    await route.fulfill({ json: { message: 'ok' } })
  })
  await page.route('**/api/devices/3/ip-history', async (route) => {
    await route.fulfill({ json: [{ id: 1, device_id: 3, ip_address: '192.0.2.70', first_seen: '2026-05-24T17:59:00Z', last_seen: now, seen_count: 15 }] })
  })
  await page.route('**/api/devices/3/timeline', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/devices/3/deep-scan/**', async (route) => {
    await route.fulfill({ json: route.request().url().includes('/config') ? {} : [] })
  })
  await page.route('**/api/devices/3/passive-discovery?**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/credentials', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/devices/3/ports', async (route) => {
    await route.fulfill({ status: 404, json: { detail: 'Not found' } })
  })

  await page.goto('/devices/3')
  await expect(page.getByRole('heading', { name: 'Docker Host' })).toBeVisible()
  await page.screenshot({ path: `${screenshotDir}/lanlens-device-detail.png`, fullPage: false })
})

test('README segments screenshot', async ({ page }) => {
  await mockCommon(page)
  await page.goto('/segments')
  await expect(page.getByRole('heading', { name: 'Segments' })).toBeVisible()
  await expect(page.getByText('Core Infrastructure')).toBeVisible()
  await page.screenshot({ path: `${screenshotDir}/lanlens-segments.png`, fullPage: false })
})
