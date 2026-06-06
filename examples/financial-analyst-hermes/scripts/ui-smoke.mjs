// SPDX-License-Identifier: Apache-2.0
import { chromium } from 'playwright';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const url = process.env.FINANCE_UI_URL || 'http://127.0.0.1:8765/';
const apiBaseUrl = process.env.FINANCE_API_BASE_URL || `${url.replace(/\/$/, '')}/v1`;
const apiToken = process.env.FINANCE_API_TOKEN || 'test-token';
const expectedText = process.env.FINANCE_EXPECT_TEXT === undefined ? 'Mock analyst brief' : process.env.FINANCE_EXPECT_TEXT;
const responseTimeoutMs = Number(process.env.FINANCE_RESPONSE_TIMEOUT_MS || '120000');
const exampleRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const screenshot = resolve(exampleRoot, 'docs', 'ui-smoke.png');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto(url, { waitUntil: 'networkidle' });
await page.getByLabel('API base URL').fill(apiBaseUrl);
await page.getByLabel('API token').fill(apiToken);
await page.getByRole('button', { name: 'Earnings prep' }).click();
await page.getByRole('button', { name: 'Send' }).click();
if (expectedText) {
  await page.getByText(expectedText).waitFor({ timeout: responseTimeoutMs });
} else {
  const secondAssistantMessage = page.locator('.message.assistant p').nth(1);
  await secondAssistantMessage.waitFor({ timeout: responseTimeoutMs });
  const text = (await secondAssistantMessage.textContent()) || '';
  if (text.length < 20 || text.includes('Request failed')) {
    throw new Error(`Unexpected assistant response: ${text}`);
  }
}
await page.screenshot({ path: screenshot, fullPage: true });
await browser.close();
console.log(JSON.stringify({ ok: true, url, apiBaseUrl, screenshot }));
