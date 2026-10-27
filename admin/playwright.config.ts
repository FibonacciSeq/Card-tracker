import { defineConfig, devices } from "@playwright/test";

const API_URL = "http://127.0.0.1:8010";
const ADMIN_URL = "http://127.0.0.1:5173";

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
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npx vite --port 5173 --strictPort",
      url: ADMIN_URL,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { CARDTRACKER_API_URL: API_URL },
    },
  ],
});
