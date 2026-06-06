// SPDX-License-Identifier: Apache-2.0
import { chromium } from 'playwright';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const url = process.env.FINANCE_UI_URL || 'http://127.0.0.1:8765/';
const exampleRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const screenshot = resolve(exampleRoot, 'docs', 'ui-smoke.png');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto(url, { waitUntil: 'networkidle' });
await page.getByLabel('API base URL').fill(`${url.replace(/\/$/, '')}/v1`);
await page.getByLabel('API token').fill('test-token');
await page.getByRole('button', { name: 'Earnings prep' }).click();
await page.getByRole('button', { name: 'Send' }).click();
await page.getByText('Mock analyst brief').waitFor({ timeout: 10000 });
await page.screenshot({ path: screenshot, fullPage: true });
await browser.close();
console.log(JSON.stringify({ ok: true, url, screenshot }));
