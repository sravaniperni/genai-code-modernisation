import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests against the REAL backend: scripts/e2e-backend.sh migrates a dedicated database
 * (modernisation_e2e), creates a sample git repository and starts the API; Vite serves the UI and
 * proxies /api to it. Nothing is mocked.
 *
 * @playwright/test is pinned to 1.56.1, whose Chromium build (1194) is the one pre-installed under
 * PLAYWRIGHT_BROWSERS_PATH. Set E2E_CHROMIUM_PATH to use a different Chromium binary.
 */
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8000);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 5173);
// Reusing already-running servers is opt-in: by default each run gets a freshly migrated database.
const reuse = process.env.E2E_REUSE_SERVERS === '1';

export default defineConfig({
  testDir: './e2e',
  // The scenarios share one backend database, so they run one at a time.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.E2E_CHROMIUM_PATH
      ? { executablePath: process.env.E2E_CHROMIUM_PATH }
      : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'bash scripts/e2e-backend.sh',
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      env: { E2E_BACKEND_PORT: String(BACKEND_PORT) },
      reuseExistingServer: reuse,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${FRONTEND_PORT} --strictPort`,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      env: { VITE_API_PROXY_TARGET: `http://127.0.0.1:${BACKEND_PORT}` },
      reuseExistingServer: reuse,
      timeout: 60_000,
    },
  ],
});
