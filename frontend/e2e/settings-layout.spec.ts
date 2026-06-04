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
      await route.fulfill({ json: { current_version: '1.5.6', latest_version: '1.5.6', release_url: '', update_available: false } })
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
  await expect(page.getByText('Global', { exact: true })).toBeVisible()
  await expect(page.getByTitle('Bot messages sent to the configured chat.')).toBeVisible()
  await expect(page.getByText('Webhook', { exact: true })).toBeVisible()
  await expect(page.getByText('Email', { exact: true })).toBeVisible()
  await page.waitForTimeout(4500)
  await page.screenshot({ path: testInfo.outputPath('settings-notification-rules.png'), fullPage: false })
})
