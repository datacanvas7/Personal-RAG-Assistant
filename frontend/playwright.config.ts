import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests run against a real frontend build and the real API with stand-ins for the
 * model (see backend/tests/e2e_server.py). They expect both servers to be running already:
 *
 *   backend:  python -m tests.e2e_server                 (port 8000)
 *   frontend: npm run build && npm start -- -p 3100      (BACKEND_INTERNAL_URL set at build)
 *   then:     npm run e2e
 *
 * CI does exactly that; see .github/workflows/ci.yml.
 */
export default defineConfig({
  testDir: "./e2e",
  // One journey runs against one database: keep tests in a file in order, files serial.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  // "github" turns each failure into an annotation, which stays readable without signing in.
  reporter: process.env.CI
    ? [["list"], ["github"], ["html", { open: "never" }]]
    : "list",
  use: {
    baseURL: process.env.PW_BASE_URL ?? "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop",
      testIgnore: /responsive.spec.ts/,
      // PW_CHANNEL=msedge (or chrome) uses a browser already installed on the machine,
      // so no download is needed locally. CI installs Playwright's own Chromium.
      use: { ...devices["Desktop Chrome"], channel: process.env.PW_CHANNEL || undefined },
    },
    {
      name: "mobile",
      testMatch: /responsive\.spec\.ts/,
      use: { ...devices["Pixel 7"], channel: process.env.PW_CHANNEL || undefined },
    },
  ],
});
