import { expect, test } from '@playwright/test'

const now = '2026-06-25T18:55:00Z'

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
  port_scan_background_enabled: false,
  port_scan_interval_minutes: 60,
  snmp_poll_enabled: true,
  snmp_poll_interval_minutes: 60,
  telegram_bot_token: '',
  telegram_chat_id: '',
  telegram_enabled: false,
  notify_telegram_update: false,
  network_interface: '',
  notify_on_device_online: false,
  notify_on_device_offline: false,
  notify_on_new_device: false,
  notify_on_network_changes: false,
  notify_on_ip_address_change: true,
  notify_on_hostname_change: true,
  notify_on_device_archive_change: true,
  notify_on_mac_drift: true,
  notify_on_unknown_dhcp_server: true,
  telegram_notify_new_device: true,
  telegram_notify_network_changes: false,
  webhook_notify_new_device: true,
  webhook_notify_network_changes: false,
  smtp_notify_new_device: false,
  smtp_notify_network_changes: false,
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
  show_services_nav: true,
  show_dhcp_monitor_nav: true,
  show_network_topology_nav: true,
  show_plugin_api: true,
  show_passive_discovery: true,
  show_mdns_discovery: true,
  show_ssdp_discovery: true,
  show_tls_checks: false,
  show_ping_history: false,
  show_build_info: false,
  show_debug_tools: false,
  debug_log_level: 'warning',
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

const topology = {
  nodes: [
    {
      id: 1,
      label: 'Edge Firewall',
      ip_address: '10.0.0.1',
      device_class: 'Firewall',
      is_online: true,
      segment_id: 10,
      segment_name: 'Mgmt',
      service_count: 2,
      snmp_switch: null,
      snmp_interface: null,
      snmp_vlan: null,
    },
    {
      id: 2,
      label: 'Core Switch',
      ip_address: '10.0.0.2',
      device_class: 'Switch',
      is_online: true,
      segment_id: 10,
      segment_name: 'Mgmt',
      service_count: 1,
      snmp_switch: 'Core Switch',
      snmp_interface: null,
      snmp_vlan: '10',
    },
    {
      id: 3,
      label: 'Access Switch 1',
      ip_address: '10.0.30.2',
      device_class: 'Switch',
      is_online: true,
      segment_id: 30,
      segment_name: 'Users',
      service_count: 0,
      snmp_switch: 'Core Switch',
      snmp_interface: 'ge-0/3/1',
      snmp_vlan: '30',
    },
    {
      id: 4,
      label: 'NAS-01',
      ip_address: '10.0.10.10',
      device_class: 'NAS',
      is_online: true,
      segment_id: 20,
      segment_name: 'Servers',
      service_count: 4,
      snmp_switch: 'Core Switch',
      snmp_interface: 'ge-0/1/1',
      snmp_vlan: '20',
    },
    {
      id: 5,
      label: 'Workstation',
      ip_address: '10.0.30.44',
      device_class: 'Client',
      is_online: false,
      segment_id: 30,
      segment_name: 'Users',
      service_count: 0,
      snmp_switch: 'Access Switch 1',
      snmp_interface: 'eth1',
      snmp_vlan: '30',
    },
    ...Array.from({ length: 16 }, (_, index) => ({
      id: 10 + index,
      label: `Desk Client ${String(index + 1).padStart(2, '0')}`,
      ip_address: `10.0.40.${20 + index}`,
      device_class: 'Client',
      is_online: index % 4 !== 0,
      segment_id: 40,
      segment_name: 'Clients',
      service_count: 0,
      snmp_switch: 'Access Switch 1',
      snmp_interface: `eth${index + 2}`,
      snmp_vlan: '40',
    })),
  ],
  edges: [
    { source: 1, target: 2, relationship_type: 'snmp_port', label: 'ge-0/0/1', metadata: { vlan: '10' } },
    { source: 2, target: 3, relationship_type: 'snmp_port', label: 'ge-0/3/1', metadata: { vlan: '30' } },
    { source: 2, target: 4, relationship_type: 'snmp_port', label: 'ge-0/1/1', metadata: { vlan: '20' } },
    { source: 3, target: 5, relationship_type: 'snmp_port', label: 'eth1', metadata: { vlan: '30' } },
    { source: 1, target: 2, relationship_type: 'ospf_neighbor', label: '10.0.0.2', metadata: { router_id: '10.0.0.1' } },
    ...Array.from({ length: 16 }, (_, index) => ({
      source: 3,
      target: 10 + index,
      relationship_type: 'snmp_port',
      label: `eth${index + 2}`,
      metadata: { vlan: '40' },
    })),
  ],
}

const endpoints = [
  {
    mac_address: '00:11:22:33:44:55',
    device_id: 4,
    device_label: 'NAS-01',
    switch_name: 'Core Switch',
    switch_host: '10.0.0.2',
    if_index: 11,
    interface_name: 'ge-0/1/1',
    interface_alias: 'to-nas-01',
    vlan: '20',
    last_seen_at: now,
  },
]

const changes = [
  {
    id: 101,
    device_id: 4,
    event_type: 'online_state_changed',
    field_name: 'is_online',
    old_value: 'false',
    new_value: 'true',
    source: 'snmp',
    message: 'NAS-01 came online through switch-port evidence',
    created_at: now,
    device_label: 'NAS-01',
    device_ip: '10.0.10.10',
    device_mac: '00:11:22:33:44:55',
    device_class: 'NAS',
  },
]

test('network topology visualizes inventory and SNMP relationships', async ({ page }, testInfo) => {
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
  await page.route('**/api/settings/update/check', async (route) => {
    await route.fulfill({ json: { current_version: '1.5.8', latest_version: '1.5.8', release_url: '', update_available: false } })
  })
  await page.route(/\/api\/devices(?:$|\?)/, async (route) => {
    await route.fulfill({ json: { items: [], total: 21, online: 16, offline: 5, unregistered: 0, archived: 0 } })
  })
  await page.route('**/api/inventory/topology', async (route) => {
    await route.fulfill({ json: topology })
  })
  await page.route('**/api/snmp/topology/endpoints', async (route) => {
    await route.fulfill({ json: endpoints })
  })
  await page.route('**/api/inventory/changes**', async (route) => {
    await route.fulfill({ json: changes })
  })

  await page.goto('/topology')

  await expect(page.getByRole('heading', { name: 'Network Topology' })).toBeVisible()
  await expect(page.getByText('Core Switch').first()).toBeVisible()
  await expect(page.getByText('ge-0/1/1').first()).toBeVisible()
  await expect(page.getByText('SNMP context')).toBeVisible()
  await page.getByRole('button', { name: 'Zoom in' }).click()
  await expect(page.getByText('116%')).toBeVisible()
  await page.getByTestId('topology-map').hover()
  await page.mouse.wheel(0, 240)
  await expect(page.getByText('100%')).toBeVisible()
  const mapBox = await page.getByTestId('topology-map').boundingBox()
  if (!mapBox) throw new Error('Topology map did not render')
  await page.mouse.move(mapBox.x + mapBox.width / 2, mapBox.y + mapBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(mapBox.x + mapBox.width / 2 + 80, mapBox.y + mapBox.height / 2 + 40)
  await page.mouse.up()
  await page.getByRole('button', { name: 'Reset map view' }).click()
  const nodeBoxes = await page.getByTestId('topology-node').evaluateAll((nodes) => (
    nodes.map((node) => {
      const rect = node.getBoundingClientRect()
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
    }).filter((rect) => rect.right > 0 && rect.left < window.innerWidth && rect.bottom > 0 && rect.top < window.innerHeight)
  ))
  for (let index = 0; index < nodeBoxes.length; index += 1) {
    for (let otherIndex = index + 1; otherIndex < nodeBoxes.length; otherIndex += 1) {
      const a = nodeBoxes[index]
      const b = nodeBoxes[otherIndex]
      const overlaps = a.left < b.right - 4 && a.right > b.left + 4 && a.top < b.bottom - 4 && a.bottom > b.top + 4
      expect(overlaps, `Topology cards ${index} and ${otherIndex} should not overlap`).toBe(false)
    }
  }
  await page.getByText('NAS-01').first().click()
  await expect(page.getByText('Core Switch · ge-0/1/1')).toBeVisible()
  await expect(page.getByText('NAS-01 came online through switch-port evidence')).toBeVisible()

  await page.screenshot({ path: testInfo.outputPath('lanlens-network-topology.png'), fullPage: false })
})
