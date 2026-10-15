import { defineConfig } from '@playwright/test'

const apiTarget = process.env.E2E_API_TARGET ?? 'http://127.0.0.1:8080'

export default defineConfig({
  globalSetup: './tests/e2e/global-setup.ts',
  testDir: './tests/e2e',
  use: { baseURL: 'http://127.0.0.1:4173', headless: true },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4173',
    env: {
      VITE_USE_MOCK: 'false',
      VITE_AUTH_USE_MOCK: 'false',
      VITE_ORDERS_USE_MOCK: 'false',
      VITE_API_PROXY_TARGET: apiTarget,
    },
    port: 4173,
    reuseExistingServer: true,
  },
})
