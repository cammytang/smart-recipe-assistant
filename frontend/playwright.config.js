import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests', testMatch: '**/*.spec.js', workers: 1,
  use: { baseURL: 'http://localhost:5187', channel: 'chrome', headless: true },
  webServer: { command: 'npm run dev -- --host localhost --port 5187 --strictPort', url: 'http://localhost:5187', reuseExistingServer: false },
})
