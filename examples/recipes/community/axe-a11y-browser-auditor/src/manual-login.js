#!/usr/bin/env node
// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "patchright";

const PROFILE_ENABLED = process.env.AXE_A11Y_PROFILE_ENABLED === "true";
const PROFILE_DIR = process.env.AXE_A11Y_PROFILE_DIR || "/app/state/profile";
const LOGIN_URL = process.argv[2] || process.env.AXE_A11Y_LOGIN_URL || "https://example.com/login";

async function clearStaleProfileSingletons(profileDir) {
  await Promise.allSettled([
    fs.rm(path.join(profileDir, "SingletonLock"), { force: true }),
    fs.rm(path.join(profileDir, "SingletonCookie"), { force: true }),
    fs.rm(path.join(profileDir, "SingletonSocket"), { force: true }),
  ]);
}

if (!PROFILE_ENABLED) {
  console.error("AXE_A11Y_PROFILE_ENABLED is false. Enable the persistent profile first.");
  process.exit(1);
}

await fs.mkdir(PROFILE_DIR, { recursive: true });
await clearStaleProfileSingletons(PROFILE_DIR);

const context = await chromium.launchPersistentContext(PROFILE_DIR, {
  headless: false,
  channel: "chrome",
  viewport: { width: 1440, height: 960 },
  locale: "en-US",
  timezoneId: "America/New_York",
  args: [
    "--disable-dev-shm-usage",
    "--no-sandbox",
  ],
});

const page = context.pages()[0] || (await context.newPage());

await page.goto(LOGIN_URL, {
  waitUntil: "load",
  timeout: 30000,
});

console.log(`Persistent profile browser opened at ${LOGIN_URL}.`);
console.log("Use VNC at vnc://localhost:5900 to complete login, then press Ctrl+C here.");

await new Promise((resolve) => {
  const stop = () => resolve();
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
});

await context.close().catch(() => {});
