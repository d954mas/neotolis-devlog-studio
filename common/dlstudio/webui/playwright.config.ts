import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: {
    timeout: 7_000,
  },
  globalSetup: "./e2e/global-setup.mjs",
  globalTeardown: "./e2e/global-teardown.mjs",
  outputDir: join(tmpdir(), "dlstudio-playwright-results"),
  reporter: process.env.CI ? "line" : "list",
  use: {
    browserName: "chromium",
    headless: true,
    locale: "ru-RU",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
});
