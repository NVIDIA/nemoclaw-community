#!/usr/bin/env node
// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { AsyncLocalStorage } from "node:async_hooks";

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express from "express";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { chromium } from "patchright";
import AxeBuilder from "@axe-core/playwright";

const DEFAULT_TIMEOUT_MS = 30000;
const DEFAULT_SETTLE_MS = 1500;
const DEFAULT_RECORD_DURATION_MS = 3000;
const DEFAULT_VIEWPORT = { width: 1920, height: 1080 };
const DEFAULT_VIDEO_SIZE = { width: 1280, height: 720 };
const PROFILE_ENABLED = process.env.AXE_A11Y_PROFILE_ENABLED === "true";
const PROFILE_DIR = process.env.AXE_A11Y_PROFILE_DIR || "/app/state/profile";
const ARTIFACTS_DIR = process.env.AXE_A11Y_ARTIFACTS_DIR || "/app/state/artifacts";

const PDF_FORMATS = {
  letter: { width: "8.5in", height: "11in" },
  legal: { width: "8.5in", height: "14in" },
  tabloid: { width: "11in", height: "17in" },
  ledger: { width: "17in", height: "11in" },
  a0: { width: "33.1in", height: "46.8in" },
  a1: { width: "23.4in", height: "33.1in" },
  a2: { width: "16.54in", height: "23.4in" },
  a3: { width: "11.7in", height: "16.54in" },
  a4: { width: "8.27in", height: "11.7in" },
  a5: { width: "5.83in", height: "8.27in" },
  a6: { width: "4.13in", height: "5.83in" },
};

let profileLock = Promise.resolve();
const requestContext = new AsyncLocalStorage();

async function clearStaleProfileSingletons(profileDir) {
  await Promise.allSettled([
    fs.rm(path.join(profileDir, "SingletonLock"), { force: true }),
    fs.rm(path.join(profileDir, "SingletonCookie"), { force: true }),
    fs.rm(path.join(profileDir, "SingletonSocket"), { force: true }),
  ]);
}

function currentArtifactBaseUrl() {
  const context = requestContext.getStore();
  if (context?.artifactBaseUrl) {
    return context.artifactBaseUrl;
  }
  if (process.env.AXE_A11Y_ARTIFACT_BASE_URL) {
    return process.env.AXE_A11Y_ARTIFACT_BASE_URL.replace(/\/+$/, "");
  }
  const port = Number.parseInt(process.env.PORT || "9010", 10);
  return `http://host.docker.internal:${port}`;
}

function asBoolean(value, fallback = false) {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    if (value === "true") {
      return true;
    }
    if (value === "false") {
      return false;
    }
  }
  return fallback;
}

function clampInteger(value, fallback, min = 0, max = Number.MAX_SAFE_INTEGER) {
  const parsed = Number.parseInt(value ?? "", 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

function sanitizeFragment(value, fallback = "artifact") {
  const normalized = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || fallback;
}

function durationMs(start, end) {
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < 0 || end < start) {
    return -1;
  }
  return Math.round((end - start) * 1000) / 1000;
}

function totalMsFromHarTimings(timings) {
  return Object.values(timings).reduce((sum, value) => {
    if (!Number.isFinite(value) || value < 0) {
      return sum;
    }
    return sum + value;
  }, 0);
}

function getRequestTiming(request) {
  if (typeof request?.timing !== "function") {
    return null;
  }

  try {
    return request.timing();
  } catch {
    return null;
  }
}

function buildTimingSummary(request) {
  const timing = getRequestTiming(request);
  if (!timing) {
    return null;
  }

  return {
    startTime: timing.startTime ?? null,
    dns: durationMs(timing.domainLookupStart, timing.domainLookupEnd),
    connect: durationMs(timing.connectStart, timing.connectEnd),
    tls: durationMs(timing.secureConnectionStart, timing.connectEnd),
    send: durationMs(timing.requestStart, timing.requestStart),
    wait: durationMs(timing.requestStart, timing.responseStart),
    receive: durationMs(timing.responseStart, timing.responseEnd),
    total: durationMs(0, timing.responseEnd),
  };
}

function buildHarTimings(request) {
  const timing = getRequestTiming(request);
  if (!timing) {
    return {
      blocked: -1,
      dns: -1,
      connect: -1,
      ssl: -1,
      send: 0,
      wait: -1,
      receive: -1,
    };
  }

  return {
    blocked: -1,
    dns: durationMs(timing.domainLookupStart, timing.domainLookupEnd),
    connect: durationMs(timing.connectStart, timing.connectEnd),
    ssl: durationMs(timing.secureConnectionStart, timing.connectEnd),
    send: 0,
    wait: durationMs(timing.requestStart, timing.responseStart),
    receive: durationMs(timing.responseStart, timing.responseEnd),
  };
}

function buildHarTimingsFromSummary(timing) {
  if (!timing) {
    return {
      blocked: -1,
      dns: -1,
      connect: -1,
      ssl: -1,
      send: 0,
      wait: -1,
      receive: -1,
    };
  }

  return {
    blocked: -1,
    dns: timing.dns ?? -1,
    connect: timing.connect ?? -1,
    ssl: timing.tls ?? -1,
    send: timing.send ?? 0,
    wait: timing.wait ?? -1,
    receive: timing.receive ?? -1,
  };
}

function artifactStem(pageUrl, suffix) {
  try {
    const parsed = new URL(pageUrl);
    return `${sanitizeFragment(parsed.hostname, "page")}-${sanitizeFragment(suffix, "capture")}`;
  } catch {
    return sanitizeFragment(suffix, "capture");
  }
}

function toolText(payload) {
  return {
    type: "text",
    text: JSON.stringify(payload, null, 2),
  };
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
  return dirPath;
}

async function saveArtifactBuffer(buffer, folder, extension, pageUrl, suffix) {
  const targetDir = await ensureDir(path.join(ARTIFACTS_DIR, folder));
  const fileName = `${artifactStem(pageUrl, suffix)}-${Date.now()}-${randomUUID().slice(0, 8)}.${extension}`;
  const artifactPath = path.join(targetDir, fileName);
  await fs.writeFile(artifactPath, buffer);
  const relativePath = path.join(folder, fileName);
  return {
    path: artifactPath,
    relativePath,
    fileName,
    url: `${currentArtifactBaseUrl()}/artifacts/${relativePath.replace(/\\/g, "/")}`,
  };
}

async function promoteVideoArtifact(tempVideoPath, pageUrl, suffix) {
  const targetDir = await ensureDir(path.join(ARTIFACTS_DIR, "recordings"));
  const fileName = `${artifactStem(pageUrl, suffix)}-${Date.now()}-${randomUUID().slice(0, 8)}.webm`;
  const artifactPath = path.join(targetDir, fileName);
  try {
    await fs.rename(tempVideoPath, artifactPath);
  } catch {
    await fs.copyFile(tempVideoPath, artifactPath);
    await fs.unlink(tempVideoPath).catch(() => {});
  }
  const relativePath = path.join("recordings", fileName);
  return {
    path: artifactPath,
    relativePath,
    fileName,
    url: `${currentArtifactBaseUrl()}/artifacts/${relativePath.replace(/\\/g, "/")}`,
  };
}

async function saveTextArtifact(text, folder, extension, pageUrl, suffix) {
  const targetDir = await ensureDir(path.join(ARTIFACTS_DIR, folder));
  const fileName = `${artifactStem(pageUrl, suffix)}-${Date.now()}-${randomUUID().slice(0, 8)}.${extension}`;
  const artifactPath = path.join(targetDir, fileName);
  await fs.writeFile(artifactPath, text, "utf-8");
  const relativePath = path.join(folder, fileName);
  return {
    path: artifactPath,
    relativePath,
    fileName,
    url: `${currentArtifactBaseUrl()}/artifacts/${relativePath.replace(/\\/g, "/")}`,
  };
}

async function withProfileSerialization(operation) {
  if (!PROFILE_ENABLED) {
    return operation();
  }

  let release;
  const previous = profileLock;
  profileLock = new Promise((resolve) => {
    release = resolve;
  });

  await previous;
  try {
    return await operation();
  } finally {
    release();
  }
}

function buildLaunchArgs(ignoreHttpsErrors) {
  // Patchright handles the CDP/Runtime detection patches internally.
  // We intentionally do NOT pass --disable-blink-features=AutomationControlled — that flag
  // is itself a detection signal once patchright's CDP fixes are in play.
  const launchArgs = [
    "--disable-dev-shm-usage",
    "--no-sandbox",
  ];

  if (ignoreHttpsErrors) {
    launchArgs.push("--ignore-certificate-errors");
  }

  return launchArgs;
}

function buildContextOptions(ignoreHttpsErrors, recordVideo = false) {
  const options = {
    ignoreHTTPSErrors: ignoreHttpsErrors,
    viewport: DEFAULT_VIEWPORT,
    locale: "en-US",
    timezoneId: "America/New_York",
    permissions: [],
  };

  if (recordVideo) {
    options.recordVideo = {
      dir: path.join(ARTIFACTS_DIR, "recordings", ".tmp"),
      size: DEFAULT_VIDEO_SIZE,
    };
  }

  return options;
}

async function openSession(args, options = {}) {
  const ignoreHttpsErrors = asBoolean(args.ignore_https_errors, false);
  const headless = options.forceHeaded ? false : process.env.PLAYWRIGHT_HEADLESS !== "false";
  const launchArgs = buildLaunchArgs(ignoreHttpsErrors);
  const contextOptions = buildContextOptions(ignoreHttpsErrors, options.recordVideo === true);

  await ensureDir(ARTIFACTS_DIR);
  if (options.recordVideo) {
    await ensureDir(path.join(ARTIFACTS_DIR, "recordings", ".tmp"));
  }

  let browser = null;
  let context;

  if (PROFILE_ENABLED) {
    await ensureDir(PROFILE_DIR);
    await clearStaleProfileSingletons(PROFILE_DIR);
    context = await chromium.launchPersistentContext(PROFILE_DIR, {
      headless,
      channel: "chrome",
      args: launchArgs,
      ...contextOptions,
    });
  } else {
    browser = await chromium.launch({
      headless,
      channel: "chrome",
      args: launchArgs,
    });
    context = await browser.newContext(contextOptions);
  }

  const page = await context.newPage();
  return { browser, context, page };
}

async function closeSession(session) {
  if (session.context) {
    await session.context.close().catch(() => {});
  }
  if (session.browser) {
    await session.browser.close().catch(() => {});
  }
}

async function waitForVisualAssets(page, timeoutMs) {
  const effectiveTimeoutMs = Math.min(timeoutMs, 8000);
  await page
    .evaluate(async ({ maxImages, timeout }) => {
      const candidates = Array.from(document.images)
        .filter((img) => {
          const src = img.currentSrc || img.src || "";
          if (!src) {
            return false;
          }
          const rect = img.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        })
        .slice(0, maxImages);

      const waitForImage = (img) =>
        Promise.race([
          img.decode ? img.decode().catch(() => {}) : Promise.resolve(),
          new Promise((resolve) => {
            if (img.complete) {
              resolve();
              return;
            }
            const done = () => {
              img.removeEventListener("load", done);
              img.removeEventListener("error", done);
              resolve();
            };
            img.addEventListener("load", done, { once: true });
            img.addEventListener("error", done, { once: true });
          }),
          new Promise((resolve) => window.setTimeout(resolve, timeout)),
        ]);

      await Promise.allSettled(candidates.map(waitForImage));
    }, { maxImages: 24, timeout: effectiveTimeoutMs })
    .catch(() => {});
}

async function navigateAndSettle(page, args) {
  const timeoutMs = clampInteger(args.timeout_ms, DEFAULT_TIMEOUT_MS, 1000, 120000);
  const settleMs = clampInteger(args.settle_ms, DEFAULT_SETTLE_MS, 0, 15000);

  await page.goto(args.url, {
    waitUntil: "load",
    timeout: timeoutMs,
  });

  if (args.wait_for_selector) {
    await page.waitForSelector(args.wait_for_selector, {
      state: "visible",
      timeout: timeoutMs,
    });
  }

  if (args.wait_for_text) {
    await page.getByText(args.wait_for_text, { exact: false }).first().waitFor({
      state: "visible",
      timeout: timeoutMs,
    });
  }

  await page.waitForLoadState("domcontentloaded", {
    timeout: Math.min(timeoutMs, 5000),
  }).catch(() => {});
  await waitForVisualAssets(page, timeoutMs);

  if (settleMs > 0) {
    await page.waitForTimeout(settleMs);
  }
}

async function buildAuditPageResult(page, args) {
  let builder = new AxeBuilder({ page });

  if (Array.isArray(args.tags) && args.tags.length > 0) {
    builder = builder.withTags(args.tags);
  }

  const axeResults = await builder.analyze();
  const violations = axeResults.violations;

  const report = {
    url: page.url(),
    timestamp: new Date().toISOString(),
    title: await page.title(),
    violations: violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      description: violation.description,
      help: violation.help,
      helpUrl: violation.helpUrl,
      tags: violation.tags,
      nodes: violation.nodes.map((node) => ({
        html: node.html,
        target: node.target,
        failureSummary: node.failureSummary,
      })),
    })),
    violationCount: violations.length,
    summary: {
      critical: violations.filter((violation) => violation.impact === "critical").length,
      serious: violations.filter((violation) => violation.impact === "serious").length,
      moderate: violations.filter((violation) => violation.impact === "moderate").length,
      minor: violations.filter((violation) => violation.impact === "minor").length,
    },
  };

  if (asBoolean(args.include_passes, false)) {
    report.passes = axeResults.passes || [];
  }

  return {
    content: [toolText(report)],
  };
}

async function buildSpecificRulesResult(page, args) {
  const axeResults = await new AxeBuilder({ page }).withRules(args.rules).analyze();

  return {
    content: [
      toolText({
        url: page.url(),
        title: await page.title(),
        rules: args.rules,
        violations: axeResults.violations,
        passes: axeResults.passes,
      }),
    ],
  };
}

async function buildAuditElementResult(page, args) {
  const locator = page.locator(args.selector).first();
  const count = await locator.count();
  if (count === 0) {
    throw new Error(`Element not found: ${args.selector}`);
  }

  const axeResults = await new AxeBuilder({ page }).include(args.selector).analyze();

  return {
    content: [
      toolText({
        url: page.url(),
        title: await page.title(),
        selector: args.selector,
        violations: axeResults.violations,
      }),
    ],
  };
}

async function buildSummaryResult(page) {
  const axeResults = await new AxeBuilder({ page }).analyze();
  const violations = axeResults.violations;
  const wcagLevels = {
    A: [],
    AA: [],
    AAA: [],
  };

  violations.forEach((violation) => {
    violation.tags.forEach((tag) => {
      if (tag === "wcag2a" || tag === "wcag21a") {
        wcagLevels.A.push(violation);
      }
      if (tag === "wcag2aa" || tag === "wcag21aa") {
        wcagLevels.AA.push(violation);
      }
      if (tag === "wcag2aaa" || tag === "wcag21aaa") {
        wcagLevels.AAA.push(violation);
      }
    });
  });

  return {
    content: [
      toolText({
        url: page.url(),
        title: await page.title(),
        summary: {
          total_violations: violations.length,
          wcag_level_a: {
            count: wcagLevels.A.length,
            compliance: wcagLevels.A.length === 0 ? "PASS" : "FAIL",
          },
          wcag_level_aa: {
            count: wcagLevels.AA.length,
            compliance: wcagLevels.AA.length === 0 ? "PASS" : "FAIL",
          },
          wcag_level_aaa: {
            count: wcagLevels.AAA.length,
            compliance: wcagLevels.AAA.length === 0 ? "PASS" : "FAIL",
          },
        },
        by_severity: {
          critical: violations.filter((violation) => violation.impact === "critical").length,
          serious: violations.filter((violation) => violation.impact === "serious").length,
          moderate: violations.filter((violation) => violation.impact === "moderate").length,
          minor: violations.filter((violation) => violation.impact === "minor").length,
        },
      }),
    ],
  };
}

async function buildCapturePageResult(page, args) {
  const screenshotBytes = await page.screenshot({
    fullPage: asBoolean(args.full_page, false),
    type: "png",
    animations: "disabled",
  });
  const artifact = await saveArtifactBuffer(
    screenshotBytes,
    "screenshots",
    "png",
    page.url(),
    asBoolean(args.full_page, false) ? "full-page" : "page"
  );

  return {
    content: [
      toolText({
        url: page.url(),
        title: await page.title(),
        full_page: asBoolean(args.full_page, false),
        artifact_path: artifact.path,
        artifact_relative_path: artifact.relativePath,
        artifact_url: artifact.url,
      }),
      {
        type: "image",
        mimeType: "image/png",
        data: screenshotBytes.toString("base64"),
      },
    ],
  };
}

async function buildCaptureElementResult(page, args) {
  const locator = page.locator(args.selector).first();
  const count = await locator.count();
  if (count === 0) {
    throw new Error(`Element not found: ${args.selector}`);
  }

  await locator.scrollIntoViewIfNeeded();
  const screenshotBytes = await locator.screenshot({
    type: "png",
    animations: "disabled",
  });
  const artifact = await saveArtifactBuffer(
    screenshotBytes,
    "screenshots",
    "png",
    page.url(),
    `element-${args.selector}`
  );

  return {
    content: [
      toolText({
        url: page.url(),
        title: await page.title(),
        selector: args.selector,
        artifact_path: artifact.path,
        artifact_relative_path: artifact.relativePath,
        artifact_url: artifact.url,
      }),
      {
        type: "image",
        mimeType: "image/png",
        data: screenshotBytes.toString("base64"),
      },
    ],
  };
}

async function buildRecordPageSessionResult(args) {
  const session = await openSession(args, { recordVideo: true });
  const captureFinalScreenshot = asBoolean(args.capture_final_screenshot, true);
  const holdOpenMs = clampInteger(args.duration_ms, DEFAULT_RECORD_DURATION_MS, 0, 120000);
  const video = session.page.video();
  let screenshotBytes = null;
  let finalUrl = args.url;
  let title = "";

  try {
    await navigateAndSettle(session.page, args);
    if (holdOpenMs > 0) {
      await session.page.waitForTimeout(holdOpenMs);
    }

    finalUrl = session.page.url();
    title = await session.page.title();

    if (captureFinalScreenshot) {
      screenshotBytes = await session.page.screenshot({
        fullPage: asBoolean(args.full_page, false),
        type: "png",
        animations: "disabled",
      });
    }
  } finally {
    await closeSession(session);
  }

  let screenshotArtifact = null;
  if (screenshotBytes) {
    screenshotArtifact = await saveArtifactBuffer(
      screenshotBytes,
      "screenshots",
      "png",
      finalUrl,
      "recording-final-frame"
    );
  }

  const tempVideoPath = video ? await video.path() : null;
  const videoArtifact = tempVideoPath
    ? await promoteVideoArtifact(tempVideoPath, finalUrl, "session-recording")
    : null;

  const result = {
    url: finalUrl,
    title,
    duration_ms: holdOpenMs,
    profile_mode: PROFILE_ENABLED ? "persistent" : "ephemeral",
    video_artifact_path: videoArtifact?.path || null,
    video_artifact_relative_path: videoArtifact?.relativePath || null,
    video_artifact_url: videoArtifact?.url || null,
    screenshot_artifact_path: screenshotArtifact?.path || null,
    screenshot_artifact_relative_path: screenshotArtifact?.relativePath || null,
    screenshot_artifact_url: screenshotArtifact?.url || null,
  };

  const content = [toolText(result)];
  if (screenshotBytes) {
    content.push({
      type: "image",
      mimeType: "image/png",
      data: screenshotBytes.toString("base64"),
    });
  }

  return { content };
}

async function buildGeneratePdfResult(page, args) {
  const format = (args.format || "a4").toLowerCase();
  const landscape = asBoolean(args.landscape, false);
  const printBackground = asBoolean(args.print_background, true);
  const displayHeaderFooter = asBoolean(args.display_header_footer, false);

  const pdfOptions = {
    landscape,
    printBackground,
    displayHeaderFooter,
    preferCSSPageSize: false,
  };

  if (PDF_FORMATS[format]) {
    pdfOptions.width = PDF_FORMATS[format].width;
    pdfOptions.height = PDF_FORMATS[format].height;
  } else if (format === "custom") {
    if (args.width && args.height) {
      pdfOptions.width = args.width;
      pdfOptions.height = args.height;
    } else {
      throw new Error("Custom format requires width and height parameters");
    }
  } else {
    pdfOptions.format = "A4";
  }

  if (displayHeaderFooter) {
    pdfOptions.headerTemplate = args.header_template || "<div></div>";
    pdfOptions.footerTemplate = args.footer_template || "<div></div>";
  }

  if (args.margin) {
    pdfOptions.margin = args.margin;
  }

  if (args.page_ranges) {
    pdfOptions.pageRanges = args.page_ranges;
  }

  const pdfBytes = await page.pdf(pdfOptions);

  const pdfArtifact = await saveArtifactBuffer(
    pdfBytes,
    "pdfs",
    "pdf",
    page.url(),
    args.suffix || "export"
  );

  const result = {
    url: page.url(),
    title: await page.title(),
    format,
    landscape,
    pdf_artifact_path: pdfArtifact.path,
    pdf_artifact_relative_path: pdfArtifact.relativePath,
    pdf_artifact_url: pdfArtifact.url,
    sizeBytes: pdfBytes.length,
  };

  return { content: [toolText(result)] };
}

async function buildCaptureNetworkResult(page, args) {
  const exportFormat = (args.export_format || "summary").toLowerCase();
  const capturedRequests = [];
  const capturedResponses = [];
  const failedRequests = [];

  page.on("request", (request) => {
    capturedRequests.push({
      url: request.url(),
      method: request.method(),
      resourceType: request.resourceType(),
      headers: request.headers(),
    });
  });

  page.on("requestfailed", (request) => {
    failedRequests.push({
      url: request.url(),
      method: request.method(),
      resourceType: request.resourceType(),
      failureText: request.failure()?.errorText || "unknown",
    });
  });

  page.on("response", (response) => {
    const request = response.request();
    let size = 0;

    try {
      const contentLength = response.headers()["content-length"];
      if (contentLength) {
        size = Number.parseInt(contentLength, 10) || 0;
      }
    } catch {
      // Ignore
    }

    capturedResponses.push({
      url: request.url(),
      method: request.method(),
      status: response.status(),
      statusText: response.statusText(),
      contentType: response.headers()["content-type"] || "unknown",
      size,
      timing: buildTimingSummary(request),
    });
  });

  await navigateAndSettle(page, args);
  await page.waitForLoadState("networkidle", {
    timeout: Math.min(clampInteger(args.timeout_ms, DEFAULT_TIMEOUT_MS, 1000, 120000), 5000),
  }).catch(() => {});

  const summary = {
    totalRequests: capturedRequests.length,
    totalResponses: capturedResponses.length,
    failedRequests: failedRequests.length,
    totalSizeBytes: capturedResponses.reduce((sum, r) => sum + (r.size || 0), 0),
    byStatus: {},
    byContentType: {},
  };

  for (const response of capturedResponses) {
    summary.byStatus[response.status] = (summary.byStatus[response.status] || 0) + 1;
    const contentType = (response.contentType || "unknown").split(";")[0].trim();
    summary.byContentType[contentType] = (summary.byContentType[contentType] || 0) + 1;
  }

  let harArtifact = null;

  if (exportFormat === "har") {
    const harLog = {
      log: {
        version: "1.2",
        creator: {
          name: "axe-a11y-mcp-server",
          version: "1.1.0",
        },
        pages: [
          {
            startedDateTime: new Date().toISOString(),
            id: "page_1",
            title: await page.title(),
            pageTimings: {},
          },
        ],
        entries: capturedResponses.slice(0, 500).map((response) => {
          const timings = buildHarTimingsFromSummary(response.timing);

          return ({
          startedDateTime: new Date().toISOString(),
          time: totalMsFromHarTimings(timings),
          pageref: "page_1",
          request: {
            method: response.method,
            url: response.url,
            httpVersion: "HTTP/1.1",
            headers: [],
            queryString: [],
            cookies: [],
            headersSize: -1,
            bodySize: -1,
          },
          response: {
            status: response.status,
            statusText: response.statusText,
            httpVersion: "HTTP/1.1",
            headers: [],
            cookies: [],
            content: {
              size: response.size || 0,
              mimeType: response.contentType,
            },
            redirectURL: "",
            headersSize: -1,
            bodySize: response.size || -1,
          },
          cache: {},
          timings,
        });
        }),
      },
    };

    const harContent = JSON.stringify(harLog, null, 2);
    harArtifact = await saveTextArtifact(
      harContent,
      "har",
      "har",
      page.url(),
      args.suffix || "capture"
    );
  }

  const result = {
    url: page.url(),
    title: await page.title(),
    exportFormat,
    summary,
    requests: capturedRequests.slice(0, 50),
    responses: capturedResponses.slice(0, 50),
    failed_requests: failedRequests.slice(0, 50),
  };

  if (harArtifact) {
    result.har_artifact_path = harArtifact.path;
    result.har_artifact_relative_path = harArtifact.relativePath;
    result.har_artifact_url = harArtifact.url;
  }

  return { content: [toolText(result)] };
}

async function withNavigatedPage(args, operation) {
  const session = await openSession(args);
  try {
    await navigateAndSettle(session.page, args);
    return await operation(session.page);
  } finally {
    await closeSession(session);
  }
}

function listTools() {
  return [
    {
      name: "audit_page",
      description:
        "Run a comprehensive accessibility audit on a web page using axe-core. Returns WCAG violations, best practices, and detailed remediation guidance.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL of the page to audit" },
          tags: {
            type: "array",
            items: { type: "string" },
            description: "Optional WCAG tags to filter by (e.g., ['wcag2aa'])",
          },
          include_passes: {
            type: "boolean",
            description: "Include successful checks in the report",
            default: false,
          },
          ignore_https_errors: {
            type: "boolean",
            description: "Ignore HTTPS certificate errors",
            default: false,
          },
          wait_for_selector: {
            type: "string",
            description: "Optional CSS selector to wait for before running the audit",
          },
          wait_for_text: {
            type: "string",
            description: "Optional visible text to wait for before running the audit",
          },
          settle_ms: {
            type: "integer",
            description: "Additional settle time after navigation",
            default: DEFAULT_SETTLE_MS,
          },
          timeout_ms: {
            type: "integer",
            description: "Navigation and wait timeout in milliseconds",
            default: DEFAULT_TIMEOUT_MS,
          },
        },
        required: ["url"],
      },
    },
    {
      name: "check_specific_rules",
      description:
        "Check specific axe-core rules on a page. Useful for targeted accessibility checks such as color contrast or image alt text.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL of the page to check" },
          rules: {
            type: "array",
            items: { type: "string" },
            description: "Array of axe rule IDs (e.g., ['color-contrast', 'image-alt'])",
          },
          ignore_https_errors: {
            type: "boolean",
            description: "Ignore HTTPS certificate errors",
            default: false,
          },
          wait_for_selector: {
            type: "string",
            description: "Optional CSS selector to wait for before running the audit",
          },
          wait_for_text: {
            type: "string",
            description: "Optional visible text to wait for before running the audit",
          },
          settle_ms: {
            type: "integer",
            description: "Additional settle time after navigation",
            default: DEFAULT_SETTLE_MS,
          },
          timeout_ms: {
            type: "integer",
            description: "Navigation and wait timeout in milliseconds",
            default: DEFAULT_TIMEOUT_MS,
          },
        },
        required: ["url", "rules"],
      },
    },
    {
      name: "audit_element",
      description: "Audit a specific element on the page by CSS selector.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL of the page" },
          selector: { type: "string", description: "CSS selector of the element to audit" },
          ignore_https_errors: {
            type: "boolean",
            description: "Ignore HTTPS certificate errors",
            default: false,
          },
          wait_for_selector: {
            type: "string",
            description: "Optional CSS selector to wait for before running the audit",
          },
          wait_for_text: {
            type: "string",
            description: "Optional visible text to wait for before running the audit",
          },
          settle_ms: {
            type: "integer",
            description: "Additional settle time after navigation",
            default: DEFAULT_SETTLE_MS,
          },
          timeout_ms: {
            type: "integer",
            description: "Navigation and wait timeout in milliseconds",
            default: DEFAULT_TIMEOUT_MS,
          },
        },
        required: ["url", "selector"],
      },
    },
    {
      name: "get_wcag_summary",
      description: "Get a high-level WCAG compliance summary grouped by severity.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL of the page to analyze" },
          ignore_https_errors: {
            type: "boolean",
            description: "Ignore HTTPS certificate errors",
            default: false,
          },
          wait_for_selector: {
            type: "string",
            description: "Optional CSS selector to wait for before running the audit",
          },
          wait_for_text: {
            type: "string",
            description: "Optional visible text to wait for before running the audit",
          },
          settle_ms: {
            type: "integer",
            description: "Additional settle time after navigation",
            default: DEFAULT_SETTLE_MS,
          },
          timeout_ms: {
            type: "integer",
            description: "Navigation and wait timeout in milliseconds",
            default: DEFAULT_TIMEOUT_MS,
          },
        },
        required: ["url"],
      },
    },
    {
      name: "axe_capture_page",
      description:
        "Capture a screenshot of the rendered page after navigation settles. Useful for proof artifacts and visual accessibility review.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL of the page to capture" },
          full_page: {
            type: "boolean",
            description: "Capture the full scrollable page instead of just the viewport",
            default: false,
          },
          ignore_https_errors: {
            type: "boolean",
            description: "Ignore HTTPS certificate errors",
            default: false,
          },
          wait_for_selector: {
            type: "string",
            description: "Optional CSS selector to wait for before capturing",
          },
          wait_for_text: {
            type: "string",
            description: "Optional visible text to wait for before capturing",
          },
          settle_ms: {
            type: "integer",
            description: "Additional settle time after navigation",
            default: DEFAULT_SETTLE_MS,
          },
          timeout_ms: {
            type: "integer",
            description: "Navigation and wait timeout in milliseconds",
            default: DEFAULT_TIMEOUT_MS,
          },
        },
        required: ["url"],
      },
    },
    {
      name: "axe_capture_element",
      description:
        "Capture a screenshot of a specific element by CSS selector after the page finishes rendering.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL of the page to capture" },
          selector: { type: "string", description: "CSS selector of the element to capture" },
          ignore_https_errors: {
            type: "boolean",
            description: "Ignore HTTPS certificate errors",
            default: false,
          },
          wait_for_selector: {
            type: "string",
            description: "Optional CSS selector to wait for before capturing",
          },
          wait_for_text: {
            type: "string",
            description: "Optional visible text to wait for before capturing",
          },
          settle_ms: {
            type: "integer",
            description: "Additional settle time after navigation",
            default: DEFAULT_SETTLE_MS,
          },
          timeout_ms: {
            type: "integer",
            description: "Navigation and wait timeout in milliseconds",
            default: DEFAULT_TIMEOUT_MS,
          },
        },
        required: ["url", "selector"],
      },
    },
    {
      name: "record_page_session",
      description:
        "Record a short Playwright video of the page after it loads. The recording is saved as an artifact and can optionally include a final screenshot preview.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL of the page to record" },
          duration_ms: {
            type: "integer",
            description: "How long to keep recording after the page settles",
            default: DEFAULT_RECORD_DURATION_MS,
          },
          capture_final_screenshot: {
            type: "boolean",
            description: "Capture a final screenshot preview alongside the video",
            default: true,
          },
          full_page: {
            type: "boolean",
            description: "Use a full-page screenshot for the final preview",
            default: false,
          },
          ignore_https_errors: {
            type: "boolean",
            description: "Ignore HTTPS certificate errors",
            default: false,
          },
          wait_for_selector: {
            type: "string",
            description: "Optional CSS selector to wait for before recording",
          },
          wait_for_text: {
            type: "string",
            description: "Optional visible text to wait for before recording",
          },
          settle_ms: {
            type: "integer",
            description: "Additional settle time after navigation",
            default: DEFAULT_SETTLE_MS,
          },
          timeout_ms: {
            type: "integer",
            description: "Navigation and wait timeout in milliseconds",
            default: DEFAULT_TIMEOUT_MS,
          },
        },
        required: ["url"],
      },
    },
    {
      name: "generate_pdf",
      description:
        "Generate a PDF export of the rendered page. Supports standard formats (A4, Letter, etc.) and custom dimensions.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL of the page to export as PDF" },
          format: {
            type: "string",
            enum: ["a4", "a3", "a5", "letter", "legal", "tabloid", "custom"],
            description: "Page format (default: a4)",
            default: "a4",
          },
          width: {
            type: "string",
            description: "Page width for custom format (e.g., '8.5in', '210mm')",
          },
          height: {
            type: "string",
            description: "Page height for custom format (e.g., '11in', '297mm')",
          },
          landscape: {
            type: "boolean",
            description: "Use landscape orientation",
            default: false,
          },
          print_background: {
            type: "boolean",
            description: "Include background graphics",
            default: true,
          },
          display_header_footer: {
            type: "boolean",
            description: "Display header and footer",
            default: false,
          },
          header_template: {
            type: "string",
            description: "HTML template for header (requires display_header_footer)",
          },
          footer_template: {
            type: "string",
            description: "HTML template for footer (requires display_header_footer)",
          },
          margin: {
            type: "object",
            description: "Page margins (e.g., {top: '1in', bottom: '1in'})",
          },
          page_ranges: {
            type: "string",
            description: "Page ranges to print (e.g., '1-5, 8, 11-13')",
          },
          suffix: {
            type: "string",
            description: "Suffix for the saved PDF filename",
            default: "export",
          },
          ignore_https_errors: {
            type: "boolean",
            description: "Ignore HTTPS certificate errors",
            default: false,
          },
          wait_for_selector: {
            type: "string",
            description: "Optional CSS selector to wait for before generating PDF",
          },
          wait_for_text: {
            type: "string",
            description: "Optional visible text to wait for before generating PDF",
          },
          settle_ms: {
            type: "integer",
            description: "Additional settle time after navigation",
            default: DEFAULT_SETTLE_MS,
          },
          timeout_ms: {
            type: "integer",
            description: "Navigation and wait timeout in milliseconds",
            default: DEFAULT_TIMEOUT_MS,
          },
        },
        required: ["url"],
      },
    },
    {
      name: "capture_network",
      description:
        "Capture network activity during page load. Returns a summary of requests/responses and optionally exports a HAR file.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL of the page to monitor" },
          export_format: {
            type: "string",
            enum: ["summary", "har"],
            description: "Export format: 'summary' for JSON summary only, 'har' to save HAR file",
            default: "summary",
          },
          suffix: {
            type: "string",
            description: "Suffix for the saved HAR filename",
            default: "capture",
          },
          ignore_https_errors: {
            type: "boolean",
            description: "Ignore HTTPS certificate errors",
            default: false,
          },
          wait_for_selector: {
            type: "string",
            description: "Optional CSS selector to wait for before completing capture",
          },
          wait_for_text: {
            type: "string",
            description: "Optional visible text to wait for before completing capture",
          },
          settle_ms: {
            type: "integer",
            description: "Additional settle time after navigation",
            default: DEFAULT_SETTLE_MS,
          },
          timeout_ms: {
            type: "integer",
            description: "Navigation and wait timeout in milliseconds",
            default: DEFAULT_TIMEOUT_MS,
          },
        },
        required: ["url"],
      },
    },
  ];
}

async function executeTool(name, args) {
  switch (name) {
    case "audit_page":
      return withNavigatedPage(args, (page) => buildAuditPageResult(page, args));
    case "check_specific_rules":
      return withNavigatedPage(args, (page) => buildSpecificRulesResult(page, args));
    case "audit_element":
      return withNavigatedPage(args, (page) => buildAuditElementResult(page, args));
    case "get_wcag_summary":
      return withNavigatedPage(args, (page) => buildSummaryResult(page));
    case "axe_capture_page":
      return withNavigatedPage(args, (page) => buildCapturePageResult(page, args));
    case "axe_capture_element":
      return withNavigatedPage(args, (page) => buildCaptureElementResult(page, args));
    case "record_page_session":
      return buildRecordPageSessionResult(args);
    case "generate_pdf":
      return withNavigatedPage(args, (page) => buildGeneratePdfResult(page, args));
    case "capture_network": {
      const session = await openSession(args);
      try {
        return await buildCaptureNetworkResult(session.page, args);
      } finally {
        await closeSession(session);
      }
    }
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

function createServer() {
  const server = new Server(
    {
      name: "axe-a11y-mcp-server",
      version: "1.2.0",
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: listTools(),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args = {} } = request.params;

    try {
      return await withProfileSerialization(() => executeTool(name, args));
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: `Error: ${error.message}`,
          },
        ],
        isError: true,
      };
    }
  });

  return server;
}

const app = express();
app.use(express.json());

app.get("/healthz", (_req, res) => {
  res.json({
    status: "ok",
    service: "axe-a11y-mcp-server",
    profile_enabled: PROFILE_ENABLED,
    artifacts_dir: ARTIFACTS_DIR,
  });
});

app.use("/artifacts", express.static(ARTIFACTS_DIR, {
  setHeaders: (res, filePath) => {
    if (filePath.endsWith(".pdf")) {
      res.setHeader("Content-Type", "application/pdf");
    } else if (filePath.endsWith(".har")) {
      res.setHeader("Content-Type", "application/json");
    } else if (filePath.endsWith(".webm")) {
      res.setHeader("Content-Type", "video/webm");
    } else if (filePath.endsWith(".png")) {
      res.setHeader("Content-Type", "image/png");
    }
    res.setHeader("Access-Control-Allow-Origin", "*");
  },
}));

app.all("/mcp", async (req, res) => {
  const server = createServer();
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
  });
  const host = req.get("host");
  const forwardedProto = req.get("x-forwarded-proto");
  const protocol = forwardedProto || req.protocol || "http";
  const artifactBaseUrl = host ? `${protocol}://${host}` : currentArtifactBaseUrl();

  res.on("close", async () => {
    await transport.close().catch(() => {});
    await server.close().catch(() => {});
  });

  try {
    await requestContext.run({ artifactBaseUrl }, async () => {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    });
  } catch (error) {
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: {
          code: -32000,
          message: error.message,
        },
        id: req.body?.id ?? null,
      });
    }
  }
});

const port = Number.parseInt(process.env.PORT || "9010", 10);
app.listen(port, async () => {
  await ensureDir(ARTIFACTS_DIR);
  if (PROFILE_ENABLED) {
    await ensureDir(PROFILE_DIR);
  }
  console.log(`axe-a11y-mcp-server listening on :${port}`);
});
