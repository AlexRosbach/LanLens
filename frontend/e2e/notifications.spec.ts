import { expect, test } from '@playwright/test'

const screenshotDir = process.env.LANLENS_E2E_OUTPUT_DIR ?? 'test-results'

test('notifications can be deleted in bulk', async ({ page }) => {
  let deleteAllCalled = false
  let notifications = [
    {
      id: 1,
      device_id: 10,
      device_path: '/devices/10',
      device_url: 'https://lanlens.example/devices/10',
      event_type: 'new_device',
      message: 'New device detected: lab-switch-01',
      is_read: false,
      telegram_sent: false,
      webhook_sent: true,
      created_at: '2026-06-04T08:30:00Z',
    },
    {
      id: 2,
      device_id: null,
      device_path: null,
      device_url: null,
      event_type: 'network_change',
      message: 'Network change: hostname changed on 192.0.2.20',
      is_read: true,
      telegram_sent: true,
      webhook_sent: false,
      created_at: '2026-06-04T08:20:00Z',
    },
  ]

  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { username: 'admin', force_password_change: false } })
  })
  await page.route('**/api/settings', async (route) => {
    await route.fulfill({ json: { app_version: '1.5.6', build_code: 'test', advanced_view_enabled: true } })
  })
  await page.route('**/api/settings/update/check', async (route) => {
    await route.fulfill({ json: { current_version: '1.5.6', latest_version: '1.5.6', release_url: '', update_available: false } })
  })
  await page.route('**/api/notifications/unread-count', async (route) => {
    await route.fulfill({ json: { count: notifications.filter((item) => !item.is_read).length } })
  })
  await page.route('**/api/notifications', async (route) => {
    if (route.request().method() === 'DELETE') {
      deleteAllCalled = true
      notifications = []
      await route.fulfill({ json: { message: 'Deleted 2 notifications' } })
      return
    }
    await route.fulfill({ json: notifications })
  })

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('Delete all notifications')
    await dialog.accept()
  })

  await page.goto('/notifications')
  await expect(page.getByText('New device detected: lab-switch-01')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Delete all' })).toBeVisible()
  await page.screenshot({ path: `${screenshotDir}/lanlens-notifications-delete-all.png`, fullPage: true })
  await page.getByRole('button', { name: 'Delete all' }).click()

  await expect(page.getByText('No notifications yet')).toBeVisible()
  expect(deleteAllCalled).toBeTruthy()
  await page.screenshot({ path: `${screenshotDir}/notifications-delete-all-empty.png`, fullPage: true })
})
