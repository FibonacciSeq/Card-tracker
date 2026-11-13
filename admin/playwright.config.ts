import { defineConfig, devices } from "@playwright/test";

function configuredPort(name: string, defaultPort: string): string {
  const port = process.env[name] ?? defaultPort;
  const numericPort = Number(port);
  if (!/^\d+$/.test(port) || numericPort < 1 || numericPort > 65_535) {
    throw new Error(`${name} must be a valid TCP port number.`);
  }
  return port;
}

const API_PORT = configuredPort("CARDTRACKER_E2E_API_PORT", "8011");
const ADMIN_PORT = configuredPort("CARDTRACKER_E2E_ADMIN_PORT", "5174");
const API_URL = `http://127.0.0.1:${API_PORT}`;
const ADMIN_URL = `http://127.0.0.1:${ADMIN_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: ADMIN_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "bash e2e/api-server.sh",
      url: `${API_URL}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        ...process.env,
        CARDTRACKER_E2E_API_PORT: API_PORT,
        CARDTRACKER_E2E_PYTHON: process.env.CARDTRACKER_E2E_PYTHON ?? "python3",
      },
    },
    {
      // Bind explicitly to IPv4 so the readiness probe for ADMIN_URL
      // (127.0.0.1) works on CI hosts that resolve localhost to ::1 first.
      command: `npx vite --host 127.0.0.1 --port ${ADMIN_PORT} --strictPort`,
      url: ADMIN_URL,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        CARDTRACKER_API_URL: API_URL,
      },
    },
  ],
});
