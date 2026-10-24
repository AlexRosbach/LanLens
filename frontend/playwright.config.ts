import { defineConfig, devices } from '@playwright/test'

const port = process.env.PLAYWRIGHT_PORT || '5173'
const baseURL = `http://127.0.0.1:${port}`
const viteCacheDir = process.env.VITE_CACHE_DIR || '/tmp/lanlens-vite-cache'

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    launchOptions: process.env.LANLENS_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.LANLENS_CHROMIUM_EXECUTABLE }
      : undefined,
  },
  webServer: {
    command: `VITE_CACHE_DIR=${viteCacheDir} npm run dev -- --host 127.0.0.1 --port ${port}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
