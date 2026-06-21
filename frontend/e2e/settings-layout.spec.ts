import { expect, test } from '@playwright/test'

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
  port_scan_background_enabled: true,
  port_scan_interval_minutes: 120,
  snmp_poll_enabled: true,
  snmp_poll_interval_minutes: 90,
  telegram_bot_token: '',
  telegram_chat_id: '',
  telegram_enabled: false,
  notify_telegram_update: false,
  network_interface: '',
  notify_on_device_online: false,
  notify_on_device_offline: false,
  notify_on_new_device: true,
  notify_on_network_changes: false,
  notify_on_ip_address_change: true,
  notify_on_hostname_change: true,
  notify_on_device_archive_change: true,
  notify_on_mac_drift: true,
  notify_on_unknown_dhcp_server: true,
  telegram_notify_new_device: true,
  telegram_notify_network_changes: false,
  webhook_notify_new_device: true,
  webhook_notify_network_changes: true,
  smtp_notify_new_device: false,
  smtp_notify_network_changes: true,
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
  show_debug_tools: false,
  debug_log_level: 'warning',
  app_version: '1.5.8',
  build_code: 'test',
  build_commit: 'test',
  build_branch: 'test',
  build_created: '2026-06-01T21:45:00Z',
  https_enabled: false,
  https_configured: false,
  https_port: 443,
  https_redirect_http: false,
}

const idoitConfig = {
  idoit_enabled: true,
  idoit_base_url: 'https://idoit.example.test',
  idoit_jsonrpc_path: '/src/jsonrpc.php',
  idoit_portal_url: 'https://idoit.example.test',
  idoit_api_key_configured: true,
  idoit_basic_username: '',
  idoit_basic_password_configured: false,
  idoit_timeout_seconds: 15,
  idoit_default_object_type: 'C__OBJTYPE__CLIENT',
  idoit_auto_sync_enabled: false,
  idoit_sync_scope: 'manual',
  idoit_create_policy: 'match_only',
  idoit_sync_interval_minutes: 60,
  idoit_offline_retire_days: 7,
  idoit_sync_status_field: '',
  idoit_mapping_json: JSON.stringify({
    name: 'Default i-doit mapping',
    objectType: 'C__OBJTYPE__CLIENT',
    identity: { externalIdField: 'C__CATG__ACCOUNTING.inventory_no' },
    fields: {
      hostname: 'C__CATG__IP.hostname',
      ip_address: 'C__CATG__IP.ipv4_address',
      cmdb_id: 'C__CATG__ACCOUNTING.inventory_no',
    },
  }, null, 2),
  idoit_mapping_raw: JSON.stringify({
    name: 'Default i-doit mapping',
    objectType: 'C__OBJTYPE__CLIENT',
    identity: { externalIdField: 'C__CATG__ACCOUNTING.inventory_no' },
    fields: {
      hostname: 'C__CATG__IP.hostname',
      ip_address: 'C__CATG__IP.ipv4_address',
      cmdb_id: 'C__CATG__ACCOUNTING.inventory_no',
    },
  }, null, 2),
  idoit_mapping_parsed: {},
  idoit_mapping_parse_error: null,
  mapping_errors: [],
  scheduler: { running: false, next_run_at: null },
}

const debugLogs = {
  topic: 'cmdb',
  level: 'debug',
  query: '',
  entries: [
    {
      id: 'idoit-101',
      topic: 'idoit',
      source: 'i-doit sync',
      level: 'error',
      device_id: 42,
      device_name: 'edge-fw-01',
      mode: 'manual',
      result: 'failure',
      message: 'i-doit sync skipped; no confident existing object match and create policy is match-only',
      object_id: null,
      details: {
        payload_hash: 'f7c33a',
        match_required: true,
        create_policy: 'match_only',
        payload: {
          title: 'edge-fw-01',
          identity: { cmdb_id: 'CMDB-0042', mac_address: '00:11:22:33:44:55' },
        },
      },
      created_at: '2026-06-11T07:35:00Z',
    },
  ],
}

const snmpProfiles = [
  {
    id: 10,
    name: 'Core v2c',
    version: '2c',
    community: '••••••••',
    username: '',
    security_level: 'noAuthNoPriv',
    auth_protocol: '',
    auth_password: '',
    privacy_protocol: '',
    privacy_password: '',
    port: 161,
    enabled: true,
  },
]

const snmpSwitches = [
  {
    id: 7,
    name: 'Core Switch',
    host: '192.168.1.2',
    device_id: null,
    profile_id: 10,
    enabled: true,
    sys_name: 'core-sw-01',
    sys_descr: 'Cisco IOS XE',
    sys_object_id: '1.3.6.1.4.1.9',
    vendor: 'Cisco',
    vendor_key: 'cisco',
    vendor_notes: 'Cisco enterprise OID',
    last_poll_at: '2026-06-04T08:30:00Z',
    last_error: null,
    last_diagnostics: 'SNMP poll target: target=192.168.1.2:161, switch=Core Switch, profile=Core v2c, version=2c\nSNMP poll steps:\n- OK: System description (1.3.6.1.2.1.1.1.0) returned 1 rows\n- OK: IF-MIB interface names (1.3.6.1.2.1.31.1.1.1.1) returned 48 rows\n- FAILED: BRIDGE-MIB MAC forwarding table (1.3.6.1.2.1.17.4.3.1.2): No Such Object available on this agent',
    interface_count: 48,
    mac_count: 24,
  },
]

test('settings groups routine jobs, lifecycle, and network discovery separately', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 980 })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { username: 'admin', force_password_change: false } })
  })
  await page.route(/\/api\/settings(?:$|\?|\/update\/check)/, async (route) => {
    if (route.request().url().includes('/api/settings/update/check')) {
      await route.fulfill({ json: { current_version: '1.5.8', latest_version: '1.5.8', release_url: '', update_available: false } })
      return
    }
    await route.fulfill({ json: settings })
  })
  await page.route(/\/api\/devices(?:$|\?|\/)/, async (route) => {
    await route.fulfill({ json: { items: [], total: 0, online: 0, offline: 0, unregistered: 0, archived: 0 } })
  })
  await page.route('**/api/notifications/unread-count', async (route) => {
    await route.fulfill({ json: { count: 0 } })
  })
  await page.route('**/api/passive-discovery/observations**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/passive-discovery/ha-groups**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/client-errors', async (route) => {
    await route.fulfill({ json: { ok: true } })
  })
  await page.route('**/api/scan-nodes**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/ignore-rules**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/profiles**', async (route) => {
    await route.fulfill({ json: snmpProfiles })
  })
  await page.route(/\/api\/snmp\/switches(?:$|\/)/, async (route) => {
    if (route.request().method() === 'PUT') {
      const payload = route.request().postDataJSON()
      await route.fulfill({
        json: {
          ...snmpSwitches[0],
          ...payload,
          id: 7,
          profile_id: Number(payload.profile_id),
        },
      })
      return
    }
    await route.fulfill({ json: snmpSwitches })
  })
  await page.route('**/api/snmp/endpoints**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/topology/endpoints**', async (route) => {
    await route.fulfill({ json: [] })
  })

  await page.goto('/settings')

  await expect(page.getByRole('button', { name: 'Automation' })).toBeVisible()
  await page.getByRole('button', { name: 'Automation' }).click()
  await expect(page.getByRole('heading', { name: 'Automation', exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Device retention' })).not.toBeVisible()
  await expect(page.getByRole('heading', { name: 'Passive discovery background job' })).not.toBeVisible()

  await page.screenshot({ path: testInfo.outputPath('settings-automation.png'), fullPage: false })

  await page.getByRole('button', { name: 'Lifecycle' }).click()
  await expect(page.getByRole('heading', { name: 'Device lifecycle' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Device retention' })).toBeVisible()

  await page.screenshot({ path: testInfo.outputPath('settings-lifecycle.png'), fullPage: false })

  await page.getByRole('button', { name: 'Network Discovery' }).click()
  await expect(page.getByRole('heading', { name: 'Address ranges' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Device retention' })).not.toBeVisible()
  await expect(page.getByRole('heading', { name: 'Passive discovery background job' })).toBeVisible()
  await expect(page.getByLabel('Cycle interval in minutes')).toHaveValue('15')
  await expect(page.getByLabel('Capture duration in seconds')).toHaveValue('30')
  await expect(page.getByLabel('SNMP poll interval in minutes')).toHaveValue('90')
  await expect(page.getByRole('heading', { name: 'SNMP targets and switch topology' })).toBeVisible()
  await expect(page.getByText('Core Switch', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Details' }).click()
  await expect(page.getByText('SNMP poll steps:')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('settings-snmp-poll-diagnostics.png'), fullPage: false })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Edit' }).click()
  await expect(page.getByLabel('SNMP target name')).toHaveValue('Core Switch')
  await page.screenshot({ path: testInfo.outputPath('settings-snmp-switch-edit.png'), fullPage: false })
  await page.getByLabel('SNMP target name').fill('Distribution Switch')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByLabel('Port range / list')).toHaveValue('top:1000')
  await expect(page.getByLabel('Port scan interval in minutes')).toHaveValue('120')

  await page.screenshot({ path: testInfo.outputPath('settings-network-discovery.png'), fullPage: false })
  await page.getByRole('heading', { name: 'Port Scan Range' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('settings-port-scan-cadence.png'), fullPage: false })

  await page.getByRole('button', { name: 'Notifications' }).click()
  await expect(page.getByRole('heading', { name: 'Notification rules' })).toBeVisible()
  await expect(page.getByTitle('Master switch for creating and delivering this notification event.')).toBeVisible()
  await expect(page.getByText('Device goes offline').first()).toBeVisible()
  await expect(page.getByText('Unknown DHCP servers').first()).toBeVisible()
  await expect(page.getByLabel('IP address changes: telegram_notify_ip_address_change').first()).toBeVisible()
  await expect(page.getByLabel('IP address changes: webhook_notify_ip_address_change').first()).toBeVisible()
  await expect(page.getByLabel('Unknown DHCP servers: smtp_notify_unknown_dhcp_server').first()).toBeVisible()
  await expect(page.getByTitle('Bot messages sent to the configured chat.')).toBeVisible()
  await expect(page.getByTitle('HTTP delivery to Gotify or another webhook receiver.')).toBeVisible()
  await expect(page.getByTitle('SMTP delivery to the configured recipient.')).toBeVisible()
  await page.waitForTimeout(4500)
  await page.screenshot({ path: testInfo.outputPath('settings-notification-rules.png'), fullPage: false })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByText('Device goes offline').nth(1)).toBeVisible()
  await expect(page.getByText('Unknown DHCP servers').nth(1)).toBeVisible()
  const notificationRulesWidth = await page.getByRole('heading', { name: 'Notification rules' }).evaluate((node) => {
    const card = node.parentElement?.parentElement ?? document.body
    return {
      scrollWidth: card.scrollWidth,
      clientWidth: card.clientWidth,
    }
  })
  expect(notificationRulesWidth.scrollWidth).toBeLessThanOrEqual(notificationRulesWidth.clientWidth + 1)
  await page.screenshot({ path: testInfo.outputPath('settings-notification-rules-mobile.png'), fullPage: false })
})

test('settings debug tab filters diagnostics and cmdb mapping is collapsible', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { username: 'admin', force_password_change: false } })
  })
  await page.route(/\/api\/settings(?:$|\?|\/update\/check)/, async (route) => {
    if (route.request().url().includes('/api/settings/update/check')) {
      await route.fulfill({ json: { current_version: '1.5.8', latest_version: '1.5.8', release_url: '', update_available: false } })
      return
    }
    await route.fulfill({
      json: {
        ...settings,
        show_cmdb_integrations: true,
        show_plugin_api: false,
        show_passive_discovery: false,
        show_mdns_discovery: false,
        show_ssdp_discovery: false,
        show_debug_tools: true,
        debug_log_level: 'debug',
      },
    })
  })
  await page.route('**/api/idoit/config', async (route) => {
    await route.fulfill({ json: idoitConfig })
  })
  await page.route('**/api/idoit/logs**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/debug/logs**', async (route) => {
    await route.fulfill({ json: debugLogs })
  })
  await page.route(/\/api\/devices(?:$|\?|\/)/, async (route) => {
    await route.fulfill({ json: { items: [], total: 0, online: 0, offline: 0, unregistered: 0, archived: 0 } })
  })
  await page.route('**/api/notifications/unread-count', async (route) => {
    await route.fulfill({ json: { count: 0 } })
  })
  await page.route('**/api/client-errors', async (route) => {
    await route.fulfill({ json: { ok: true } })
  })
  await page.route('**/api/scan-nodes**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/profiles**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route(/\/api\/snmp\/switches(?:$|\/)/, async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/endpoints**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/snmp/topology/endpoints**', async (route) => {
    await route.fulfill({ json: [] })
  })

  await page.goto('/settings')
  await page.getByRole('button', { name: 'Debug' }).click()
  await expect(page.getByRole('heading', { name: 'Debug logs' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'edge-fw-01' })).toBeVisible()
  await expect(page.getByText('match-only')).toBeVisible()
  await page.locator('summary', { hasText: 'Details' }).click()
  await expect(page.getByText('CMDB-0042')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('settings-debug-tab.png'), fullPage: false })

  await page.getByRole('button', { name: 'CMDB' }).click()
  await expect(page.getByText('Field mapping')).toBeVisible()
  await expect(page.locator('td', { hasText: 'Hostname' })).not.toBeVisible()
  await page.getByRole('button', { name: 'Expand' }).click()
  await expect(page.locator('td', { hasText: 'Hostname' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('settings-cmdb-mapping-expanded.png'), fullPage: false })
})
