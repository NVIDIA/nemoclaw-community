// SPDX-License-Identifier: Apache-2.0
import { chromium } from "playwright";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const url = process.env.FINANCE_UI_URL || "http://127.0.0.1:8765/";
const apiUrl = process.env.FINANCE_API_URL || `${url.replace(/\/$/, "")}/v1`;
const expectedText = process.env.FINANCE_EXPECT_TEXT || "";
const responseTimeoutMs = Number(
  process.env.FINANCE_RESPONSE_TIMEOUT_MS || "120000",
);
const mode = process.env.FINANCE_SMOKE_MODE || "prompt";
const requireTraceEvents = process.env.FINANCE_REQUIRE_TRACE_EVENTS === "1";
const exampleRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const screenshot = resolve(exampleRoot, "docs", "ui-smoke.png");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.stack || error.message));
await page.goto(url, { waitUntil: "networkidle" });
if (await page.getByLabel("API URL").count()) {
  throw new Error("API URL field should not be present");
}
if (await page.getByLabel("API token").count()) {
  throw new Error("API token field should not be present");
}
if (await page.getByText("Demo Prompts").count()) {
  throw new Error("Demo prompt panel should not be present");
}
if (await page.getByText("Ten-Question Eval").count()) {
  throw new Error("Ten-question eval panel should not be present");
}
for (const removedPanel of [
  "Session Context",
  "Skill Usage",
  "Tool Calls / Trace Clues",
  "Run Telemetry",
]) {
  if (await page.getByText(removedPanel).count()) {
    throw new Error(`${removedPanel} panel should not be present`);
  }
}
const promptBox = page.getByLabel("Message the financial assistant");
if (mode === "email") {
  await promptBox.fill(
    "Email from pm@northstar-cap.com: Need a concise NVDA pre-market brief using public quote context and SEC company facts. Include caveats and next checks before acting.",
  );
  await page.keyboard.press("Enter");
} else if (mode === "basic") {
  await promptBox.fill("What are you?");
  await page.keyboard.press("Enter");
} else {
  await promptBox.fill(
    "Create a concise analyst brief for NVDA using a public market snapshot and SEC company facts. Separate facts, hypotheses, checks, and caveats.",
  );
  await page.keyboard.press("Enter");
}
if (expectedText) {
  await page.getByText(expectedText).waitFor({ timeout: responseTimeoutMs });
} else {
  const assistantMessage = page.locator(".message.assistant").last();
  await assistantMessage.waitFor({ timeout: responseTimeoutMs });
  await page
    .locator("#status")
    .getByText("Ready")
    .waitFor({ timeout: responseTimeoutMs });
  await page
    .locator(".message.assistant .markdown-body table")
    .first()
    .waitFor({ timeout: responseTimeoutMs })
    .catch(() => {});
  const text = (await assistantMessage.textContent()) || "";
  if (
    text.length < 20 ||
    text.includes("Request failed") ||
    text.includes("No assistant message returned")
  ) {
    throw new Error(`Unexpected assistant response: ${text}`);
  }
  await page
    .getByText(/financial-|OpenShell|Skill Usage|Relay/i)
    .first()
    .waitFor({ timeout: responseTimeoutMs });
}
await page
  .locator("#status")
  .getByText("Ready")
  .waitFor({ timeout: responseTimeoutMs });
if (pageErrors.length) {
  throw new Error(
    `Browser page errors were raised:\n${pageErrors.join("\n\n")}`,
  );
}
if (requireTraceEvents) {
  await fetch(`${url.replace(/\/$/, "")}/api/phoenix/recent`).then(
    async (response) => {
      const payload = await response.json();
      if (!payload.ok || !payload.spans?.some((span) => span.kind === "tool")) {
        throw new Error(
          "Phoenix tool spans were not available from /api/phoenix/recent",
        );
      }
    },
  );
}
await page.screenshot({ path: screenshot, fullPage: true });
await browser.close();
console.log(JSON.stringify({ ok: true, url, apiUrl, screenshot }));
