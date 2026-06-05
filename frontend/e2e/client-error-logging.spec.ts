import { expect, test } from '@playwright/test'

test('login UI errors are forwarded to the backend log endpoint', async ({ page }) => {
  const clientErrors: Array<Record<string, unknown>> = []

  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ status: 401, json: { detail: 'Not authenticated' } })
  })
  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({ status: 401, json: { detail: 'Invalid username or password' } })
  })
  await page.route('**/api/client-errors', async (route) => {
    clientErrors.push(route.request().postDataJSON())
    await route.fulfill({ json: { success: true } })
  })

  await page.goto('/login')
  await page.getByPlaceholder('admin').fill('admin')
  await page.getByPlaceholder('••••••••').fill('wrong-password')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect.poll(() => clientErrors.length).toBeGreaterThanOrEqual(2)
  await expect(page.getByText('Invalid username or password')).toBeVisible()

  expect(clientErrors).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        kind: 'api',
        message: 'Invalid username or password',
        endpoint: '/auth/login',
        status: 401,
      }),
      expect.objectContaining({
        kind: 'toast',
        message: 'Invalid username or password',
        source: 'toast.error',
      }),
    ]),
  )
  expect(clientErrors.some((entry) => entry.endpoint === '/auth/me')).toBe(false)
})
