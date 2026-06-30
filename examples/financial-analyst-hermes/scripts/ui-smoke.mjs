// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const url = process.env.FINANCE_UI_URL || "http://127.0.0.1:18080/";
const responseTimeoutMs = Number(
  process.env.FINANCE_RESPONSE_TIMEOUT_MS || "300000",
);
const requireToolSpan = process.env.FINANCE_REQUIRE_TRACE_EVENTS === "1";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const artifactDir =
  process.env.FINANCE_SMOKE_ARTIFACT_DIR || resolve(root, ".runtime");
await mkdir(artifactDir, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.stack || error.message));

await page.goto(url, { waitUntil: "networkidle" });
const prompt = page.getByLabel("Message the financial assistant");
if ((await prompt.inputValue()) !== "")
  throw new Error("Composer must start empty");
for (const removed of ["Session Context", "Skill Usage", "Run Telemetry"]) {
  if (await page.getByText(removed).count())
    throw new Error(`${removed} must not be present`);
}

const traceStartedAt = new Date().toISOString();
await prompt.fill(
  "Use the terminal tool to inspect the installed SKILL.md files. Then tell me which skills are installed and what financial work each supports.",
);
await prompt.press("Enter");
const assistant = page.locator(".message.assistant").last();
await assistant.waitFor({ timeout: responseTimeoutMs });
await page
  .locator(".run-state", { hasText: "Ready" })
  .waitFor({ timeout: responseTimeoutMs });
const answer = (await assistant.textContent()) || "";
if (
  answer.length < 40 ||
  /Request failed|No assistant message returned/i.test(answer)
) {
  throw new Error(`Unexpected assistant response: ${answer}`);
}
if (pageErrors.length)
  throw new Error(`Browser errors:\n${pageErrors.join("\n")}`);

await page.screenshot({
  path: resolve(artifactDir, "ui-desktop.png"),
  fullPage: true,
});

if (requireToolSpan) {
  const since = encodeURIComponent(traceStartedAt);
  const payload = await fetch(
    `${url.replace(/\/$/, "")}/api/phoenix/recent?since=${since}`,
  ).then((response) => response.json());
  const traces = new Map();
  for (const span of payload.spans || []) {
    const trace = traces.get(span.trace_id) || {
      kinds: new Set(),
      parentIds: new Set(),
    };
    trace.kinds.add(span.kind);
    if (span.parent_id) trace.parentIds.add(span.parent_id);
    traces.set(span.trace_id, trace);
  }
  const coherent = [...traces.values()].some(
    (trace) =>
      trace.kinds.has("tool") &&
      trace.kinds.has("llm") &&
      trace.parentIds.size > 0,
  );
  if (!payload.ok || !coherent) {
    throw new Error(
      "Phoenix did not return correlated Hermes LLM and tool spans",
    );
  }
}

const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
await mobile.goto(url, { waitUntil: "networkidle" });
await mobile.getByLabel("Message the financial assistant").waitFor();
const box = await mobile
  .getByLabel("Message the financial assistant")
  .boundingBox();
if (!box || box.y + box.height > 844)
  throw new Error("Mobile composer is outside the viewport");
await mobile.screenshot({
  path: resolve(artifactDir, "ui-mobile.png"),
  fullPage: true,
});

await browser.close();
console.log(
  JSON.stringify({ ok: true, url, answer_length: answer.length, artifactDir }),
);
