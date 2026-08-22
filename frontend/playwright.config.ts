import { defineConfig } from "@playwright/test";

/**
 * E2E test expects the backend on :8000 and the frontend on :3000
 * (see README: `npm run start` + `uvicorn app.main:app`).
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  use: {
    baseURL: "http://localhost:3000",
    headless: true,
    launchOptions: {
      // The CI/dev container pre-installs Chromium here; override if local.
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH ?? "/opt/pw-browsers/chromium",
    },
  },
});
