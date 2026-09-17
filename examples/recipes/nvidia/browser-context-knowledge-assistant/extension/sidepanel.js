// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const CANONICAL_SERVICE_PATH = "/api/plugins/ask-nemoclaw";
const DEFAULT_NEMOCLAW_ORIGIN = String(globalThis.ASK_NEMOCLAW_CONFIG?.hermesOrigin || "").replace(/\/$/, "");
const DEFAULT_SERVICE_PATH = String(globalThis.ASK_NEMOCLAW_CONFIG?.servicePath || CANONICAL_SERVICE_PATH);
const DEFAULT_DASHBOARD_PATH = String(globalThis.ASK_NEMOCLAW_CONFIG?.dashboardPath || "/");
function normalizedDeploymentUrl(value) {
  try {
    const url = new URL(value);
    const loopbackHosts = new Set(["127.0.0.1", "localhost", "[::1]"]);
    const allowedScheme = url.protocol === "https:" || (
      url.protocol === "http:" && loopbackHosts.has(url.hostname)
    );
    if (!allowedScheme || url.username || url.password || url.search || url.hash) return null;
    url.pathname = url.pathname.replace(/\/+$/, "") || "/";
    return url.href.replace(/\/$/, "");
  } catch (_) {
    return null;
  }
}

function isBrevSecureLink(value) {
  try {
    const hostname = new URL(value).hostname.toLowerCase();
    return hostname.endsWith(".gobrev.dev") || hostname.endsWith(".brevlab.com");
  } catch (_) {
    return false;
  }
}
const DEFAULT_NEMOCLAW_SERVICE_URL = normalizedDeploymentUrl(`${DEFAULT_NEMOCLAW_ORIGIN}${DEFAULT_SERVICE_PATH}`);
const DEFAULT_NEMOCLAW_DASHBOARD_URL = normalizedDeploymentUrl(`${DEFAULT_NEMOCLAW_ORIGIN}${DEFAULT_DASHBOARD_PATH}`);
let nemoClawOrigin = DEFAULT_NEMOCLAW_ORIGIN;
let nemoClawServiceUrl = DEFAULT_NEMOCLAW_SERVICE_URL || "";
let nemoClawDashboardUrl = DEFAULT_NEMOCLAW_DASHBOARD_URL || "";
let nemoClawServiceUrls = [];
const conversationsEndpoint = () => `${nemoClawServiceUrl}/conversations`;
const MAX_PAGE_TEXT_CHARS = 200000;
const MAX_SELECTED_TEXT_CHARS = 50000;
const MAX_VIEWPORT_IMAGE_BYTES = 4000000;
const MAX_VIEWPORT_IMAGE_PIXELS = 4000000;
const MAX_VIEWPORT_IMAGE_EDGE = 2048;
const HERMES_REQUEST_TIMEOUT_MS = 60000;
const sessionAuth = globalThis.AskNemoClawAuth;

const elements = {
  pageLabel: document.getElementById("page-label"),
  connectionStatus: document.getElementById("connection-status"),
  checkConnectionButton: document.getElementById("check-connection-button"),
  openNemoClawButton: document.getElementById("open-nemoclaw-button"),
  settingsButton: document.getElementById("settings-button"),
  settingsCard: document.getElementById("settings-card"),
  settingsForm: document.getElementById("settings-form"),
  nemoClawUrl: document.getElementById("nemoclaw-url"),
  settingsError: document.getElementById("settings-error"),
  disconnectButton: document.getElementById("disconnect-button"),
  cancelSettingsButton: document.getElementById("cancel-settings-button"),
  conversationSelect: document.getElementById("conversation-select"),
  newConversationButton: document.getElementById("new-conversation-button"),
  refreshButton: document.getElementById("refresh-button"),
  messages: document.getElementById("messages"),
  emptyState: document.getElementById("empty-state"),
  status: document.getElementById("status-card"),
  statusTitle: document.getElementById("status-title"),
  statusDetail: document.getElementById("status-detail"),
  stopButton: document.getElementById("stop-button"),
  error: document.getElementById("error-card"),
  errorTitle: document.getElementById("error-title"),
  errorDetail: document.getElementById("error-detail"),
  contextMode: document.getElementById("context-mode"),
  composer: document.getElementById("composer"),
  prompt: document.getElementById("prompt"),
  sendButton: document.getElementById("send-button"),
  retryButton: document.getElementById("retry-button"),
  signInButton: document.getElementById("sign-in-button")
};

let activePage = null;
let activeConversationId = null;
let activeJob = null;
let pollTimer = null;
let retryAction = null;
let pendingSubmission = null;
let dashboardSessionToken = null;
let dashboardSessionTokenOrigin = null;
let refreshGeneration = 0;
let refreshController = null;
let statusTimer = null;
let currentStatus = null;
let requestStartedAt = null;

function originPermission(origin) {
  return `${origin}/*`;
}

function inferredServiceUrls(dashboardUrl, preferredServiceUrl = null) {
  const origin = new URL(dashboardUrl).origin;
  const paths = [
    preferredServiceUrl ? new URL(preferredServiceUrl).pathname : null,
    DEFAULT_SERVICE_PATH,
    CANONICAL_SERVICE_PATH,
    "/ask-nemoclaw"
  ].filter(Boolean);
  return [...new Set(paths.map(path => normalizedDeploymentUrl(`${origin}${path}`)).filter(Boolean))];
}

function applyNemoClawUrl(dashboardUrl, preferredServiceUrl = null) {
  nemoClawDashboardUrl = dashboardUrl;
  nemoClawOrigin = new URL(dashboardUrl).origin;
  nemoClawServiceUrls = inferredServiceUrls(dashboardUrl, preferredServiceUrl);
  nemoClawServiceUrl = nemoClawServiceUrls[0];
}

function nemoClawConversationDashboardUrl() {
  const url = new URL("/sessions", nemoClawDashboardUrl);
  url.searchParams.set("profile", "dashboard-home");
  return url.href;
}

async function loadNemoClawOrigin() {
  const stored = await chrome.storage.local.get([
    "askNemoClawUrl",
    "askNemoClawConfiguredByUser",
    "askNemoClawServiceUrl",
    "askNemoClawDashboardUrl",
    "askNemoClawOrigin"
  ]);
  const legacyOrigin = normalizedDeploymentUrl(stored.askNemoClawOrigin || "");
  const candidateDashboard = normalizedDeploymentUrl(
    stored.askNemoClawUrl || stored.askNemoClawDashboardUrl || legacyOrigin || ""
  );
  const legacyService = normalizedDeploymentUrl(stored.askNemoClawServiceUrl || "");
  const candidateOrigin = candidateDashboard ? new URL(candidateDashboard).origin : "";
  if (
    stored.askNemoClawConfiguredByUser === true
    && candidateDashboard
    && (!legacyService || new URL(legacyService).origin === candidateOrigin)
    && await chrome.permissions.contains({ origins: [originPermission(candidateOrigin)] })
  ) {
    applyNemoClawUrl(candidateDashboard, legacyService);
    elements.nemoClawUrl.value = nemoClawDashboardUrl;
    return true;
  }
  if (candidateDashboard && stored.askNemoClawConfiguredByUser !== true) {
    await chrome.storage.local.remove([
      "askNemoClawUrl",
      "askNemoClawOrigin",
      "askNemoClawServiceUrl",
      "askNemoClawDashboardUrl",
      "askNemoClawConversationId"
    ]);
  }
  if (
    DEFAULT_NEMOCLAW_DASHBOARD_URL
    && DEFAULT_NEMOCLAW_SERVICE_URL
    && await chrome.permissions.contains({ origins: [originPermission(DEFAULT_NEMOCLAW_ORIGIN)] })
  ) {
    applyNemoClawUrl(DEFAULT_NEMOCLAW_DASHBOARD_URL, DEFAULT_NEMOCLAW_SERVICE_URL);
    elements.nemoClawUrl.value = nemoClawDashboardUrl;
    return true;
  }
  nemoClawOrigin = "";
  nemoClawServiceUrl = "";
  nemoClawDashboardUrl = "";
  nemoClawServiceUrls = [];
  elements.nemoClawUrl.value = "";
  return false;
}

function showSettings() {
  elements.nemoClawUrl.value = nemoClawDashboardUrl;
  elements.settingsError.hidden = true;
  elements.settingsCard.hidden = false;
  elements.nemoClawUrl.focus();
}

async function saveSettings(event) {
  event.preventDefault();
  const candidateDashboard = normalizedDeploymentUrl(String(elements.nemoClawUrl.value || "").trim());
  if (!candidateDashboard) {
    elements.settingsError.textContent = "Enter a valid HTTPS NemoClaw URL, or an HTTP localhost URL, without credentials, a query, or a fragment.";
    elements.settingsError.hidden = false;
    return;
  }
  const candidateOrigin = new URL(candidateDashboard).origin;
  if (isBrevSecureLink(candidateDashboard)) {
    elements.settingsError.textContent = "Brev Secure Links use redirect-based browser authentication and cannot carry extension API requests. Start a Brev port forward and enter its localhost URL instead.";
    elements.settingsError.hidden = false;
    return;
  }
  const previousOrigin = nemoClawOrigin;
  const granted = await chrome.permissions.request({ origins: [originPermission(candidateOrigin)] });
  if (!granted) {
    elements.settingsError.textContent = "Chrome did not grant access to this NemoClaw origin.";
    elements.settingsError.hidden = false;
    return;
  }
  applyNemoClawUrl(candidateDashboard);
  await sessionAuth.clearSession();
  dashboardSessionToken = null;
  dashboardSessionTokenOrigin = null;
  await chrome.storage.local.set({
    askNemoClawUrl: candidateDashboard,
    askNemoClawConfiguredByUser: true
  });
  await chrome.storage.local.remove([
    "askNemoClawOrigin",
    "askNemoClawServiceUrl",
    "askNemoClawDashboardUrl"
  ]);
  await chrome.storage.local.remove("askNemoClawConversationId");
  if (previousOrigin && previousOrigin !== candidateOrigin) {
    await chrome.permissions.remove({ origins: [originPermission(previousOrigin)] });
  }
  activeConversationId = null;
  elements.settingsCard.hidden = true;
  await initialize();
}

async function disconnectNemoClaw() {
  const previousOrigin = nemoClawOrigin;
  clearTimeout(pollTimer);
  activeJob = null;
  activeConversationId = null;
  pendingSubmission = null;
  dashboardSessionToken = null;
  dashboardSessionTokenOrigin = null;
  await sessionAuth.clearSession();
  await chrome.storage.local.remove([
    "askNemoClawUrl",
    "askNemoClawConfiguredByUser",
    "askNemoClawOrigin",
    "askNemoClawServiceUrl",
    "askNemoClawDashboardUrl",
    "askNemoClawConversationId"
  ]);
  if (previousOrigin) {
    await chrome.permissions.remove({ origins: [originPermission(previousOrigin)] });
  }
  nemoClawOrigin = "";
  nemoClawServiceUrl = "";
  nemoClawDashboardUrl = "";
  nemoClawServiceUrls = [];
  elements.nemoClawUrl.value = "";
  hideStatus();
  clearError();
  setConnectionState("unavailable", "NemoClaw is not configured");
  showSettings();
}

function setConnectionState(state, label) {
  elements.connectionStatus.dataset.state = state;
  elements.connectionStatus.textContent = label;
}

function scrollConversationToBottom() {
  const scroll = () => globalThis.scrollTo?.({
    top: document.documentElement.scrollHeight,
    behavior: "auto"
  });
  if (typeof globalThis.requestAnimationFrame === "function") {
    globalThis.requestAnimationFrame(scroll);
  } else {
    scroll();
  }
}

function conversationIsNearBottom() {
  const root = document.documentElement;
  return globalThis.scrollY + globalThis.innerHeight >= root.scrollHeight - 160;
}

const SENSITIVE_QUERY_PARAMETER = /(?:^|[_-])(?:access[_-]?token|auth|authorization|code|credential|jwt|key|password|refresh[_-]?token|secret|session|sig|signature|state|token)(?:$|[_-])/i;

function removeSensitiveQueryParameters(url) {
  for (const key of [...url.searchParams.keys()]) {
    if (SENSITIVE_QUERY_PARAMETER.test(key)) url.searchParams.delete(key);
  }
}

function sanitizePageUrl(rawUrl) {
  const url = new URL(rawUrl || "");
  if (!['http:', 'https:'].includes(url.protocol)) return null;
  if (url.username || url.password) return null;
  removeSensitiveQueryParameters(url);
  url.hash = "";
  return url.href;
}

async function readActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const stored = await chrome.storage.session.get("askNemoClawTarget");
  const authorizedTarget = stored.askNemoClawTarget;
  const matchingStoredTarget = authorizedTarget?.tabId === tab?.id ? authorizedTarget : null;
  const pageUrl = sanitizePageUrl(tab?.url || matchingStoredTarget?.page_url || "");
  if (!tab?.id || !pageUrl) {
    throw new Error("unsupported_page");
  }
  activePage = {
    tabId: tab.id,
    windowId: tab.windowId,
    page_url: pageUrl,
    page_title: tab.title || matchingStoredTarget?.page_title || "Untitled page"
  };
  elements.pageLabel.textContent = `${activePage.page_title} · ${activePage.page_url}`;
  return activePage;
}

async function refreshActivePage(showFailure = true) {
  try {
    await readActiveTab();
    elements.contextMode.textContent = "Available page text + visible viewport";
    return true;
  } catch (_) {
    if (showFailure) {
      showError(
        "Page access unavailable",
        "Open a normal HTTP or HTTPS page and click the Ask NemoClaw toolbar icon, then try again.",
        false,
        () => refreshActivePage(true)
      );
    }
    return false;
  }
}

function showError(title, detail, authenticationRequired = false, action = null) {
  elements.errorTitle.textContent = title;
  elements.errorDetail.textContent = detail;
  elements.signInButton.hidden = !authenticationRequired;
  elements.retryButton.hidden = !action;
  retryAction = action;
  elements.error.hidden = false;
}

function clearError() {
  elements.error.hidden = true;
  retryAction = null;
}

function appendText(parent, tag, text, className = "") {
  const node = document.createElement(tag);
  node.textContent = String(text ?? "");
  if (className) node.className = className;
  parent.appendChild(node);
  return node;
}

function humanize(key) {
  return key.replaceAll("_", " ").replace(/\b\w/g, character => character.toUpperCase());
}

function decodeRenderableItem(item) {
  if (typeof item !== "string") return item;
  const candidate = item.trim();
  if (!candidate.startsWith("{") && !candidate.startsWith("[")) return item;
  try {
    return JSON.parse(candidate);
  } catch (_) {
    return item;
  }
}

function parseMarkdownBlocks(value) {
  const lines = String(value ?? "")
    .replace(/\r\n?/g, "\n")
    .replace(/\s+--\s+(?=#{1,6}\s)/g, "\n\n")
    .split("\n");
  const blocks = [];
  let paragraph = [];

  const flushParagraph = () => {
    const text = paragraph.join(" ").trim();
    if (text) blocks.push({ type: "paragraph", text });
    paragraph = [];
  };
  const isTableDivider = line =>
    /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const splitTableRow = line =>
    line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+?)\s*#*$/);
    if (heading) {
      flushParagraph();
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2] });
      continue;
    }
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushParagraph();
      blocks.push({ type: "rule" });
      continue;
    }
    if (trimmed.includes("|") && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      flushParagraph();
      const headers = splitTableRow(trimmed);
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].trim().includes("|")) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      index -= 1;
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    const unordered = trimmed.match(/^[-*+]\s+(?:\[([ xX])\]\s+)?(.+)$/);
    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const orderedList = Boolean(ordered);
      const items = [];
      while (index < lines.length) {
        const candidate = lines[index].trim();
        const match = orderedList
          ? candidate.match(/^\d+[.)]\s+(.+)$/)
          : candidate.match(/^[-*+]\s+(?:\[([ xX])\]\s+)?(.+)$/);
        if (!match) break;
        items.push(
          orderedList
            ? { text: match[1] }
            : { text: match[2], checked: match[1] ? match[1].toLowerCase() === "x" : null }
        );
        index += 1;
      }
      index -= 1;
      blocks.push({ type: "list", ordered: orderedList, items });
      continue;
    }

    if (trimmed.startsWith(">")) {
      flushParagraph();
      blocks.push({ type: "quote", text: trimmed.replace(/^>\s?/, "") });
      continue;
    }
    paragraph.push(trimmed);
  }
  flushParagraph();
  return blocks;
}

function appendInlineMarkdown(parent, value) {
  const text = String(value ?? "");
  const pattern = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\*[^*\n]+\*|_[^_\n]+_)/g;
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > offset) parent.appendChild(document.createTextNode(text.slice(offset, match.index)));
    const token = match[0];
    const node = document.createElement(token.startsWith("`") ? "code" : token.startsWith("**") || token.startsWith("__") ? "strong" : "em");
    node.textContent = token.startsWith("**") || token.startsWith("__") ? token.slice(2, -2) : token.slice(1, -1);
    parent.appendChild(node);
    offset = match.index + token.length;
  }
  if (offset < text.length) parent.appendChild(document.createTextNode(text.slice(offset)));
}

function renderMarkdown(parent, value) {
  const blocks = parseMarkdownBlocks(value);
  if (blocks.length === 0) return;
  for (const block of blocks) {
    if (block.type === "rule") {
      parent.appendChild(document.createElement("hr"));
      continue;
    }
    if (block.type === "table") {
      const wrapper = document.createElement("div");
      wrapper.className = "markdown-table-wrap";
      const table = document.createElement("table");
      const headRow = document.createElement("tr");
      for (const header of block.headers) {
        const cell = document.createElement("th");
        appendInlineMarkdown(cell, header);
        headRow.appendChild(cell);
      }
      const thead = document.createElement("thead");
      thead.appendChild(headRow);
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const row of block.rows) {
        const rowNode = document.createElement("tr");
        for (let index = 0; index < block.headers.length; index += 1) {
          const cell = document.createElement("td");
          appendInlineMarkdown(cell, row[index] || "");
          rowNode.appendChild(cell);
        }
        tbody.appendChild(rowNode);
      }
      table.appendChild(tbody);
      wrapper.appendChild(table);
      parent.appendChild(wrapper);
      continue;
    }
    if (block.type === "list") {
      const list = document.createElement(block.ordered ? "ol" : "ul");
      for (const item of block.items) {
        const itemNode = document.createElement("li");
        if (item.checked !== null && item.checked !== undefined) {
          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.checked = item.checked;
          checkbox.disabled = true;
          itemNode.appendChild(checkbox);
        }
        appendInlineMarkdown(itemNode, item.text);
        list.appendChild(itemNode);
      }
      parent.appendChild(list);
      continue;
    }
    const tag = block.type === "heading" ? `h${Math.min(6, Math.max(4, block.level + 2))}` : block.type === "quote" ? "blockquote" : "p";
    const node = document.createElement(tag);
    appendInlineMarkdown(node, block.text);
    parent.appendChild(node);
  }
}

function renderValue(parent, value) {
  if (Array.isArray(value)) {
    if (value.length === 0) {
      appendText(parent, "p", "No issues identified.");
      return;
    }
    for (const originalItem of value) {
      const item = decodeRenderableItem(originalItem);
      const itemNode = document.createElement("div");
      itemNode.className = "response-item";
      if (item && typeof item === "object" && !Array.isArray(item)) {
        if (item.priority) appendText(itemNode, "div", item.priority, "priority");
        for (const [key, field] of Object.entries(item)) {
          if (key === "priority" || field === "") continue;
          appendText(itemNode, "p", `${humanize(key)}: ${typeof field === "string" ? field : JSON.stringify(field)}`);
        }
      } else {
        if (typeof item === "string") renderMarkdown(itemNode, item);
        else appendText(itemNode, "p", JSON.stringify(item));
      }
      parent.appendChild(itemNode);
    }
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, field] of Object.entries(value)) {
      const fieldNode = document.createElement("div");
      fieldNode.className = "response-field";
      appendText(fieldNode, "strong", `${humanize(key)}:`);
      if (typeof field === "string") renderMarkdown(fieldNode, field);
      else appendText(fieldNode, "p", JSON.stringify(field));
      parent.appendChild(fieldNode);
    }
    return;
  }
  if (typeof value === "string") renderMarkdown(parent, value);
  else appendText(parent, "p", value);
}

function renderResultInto(parent, result) {
  if (result?.format === "structured" && result.data && typeof result.data === "object") {
    for (const [key, value] of Object.entries(result.data)) {
      const section = document.createElement("section");
      section.className = "response-section";
      appendText(section, "h3", humanize(key));
      renderValue(section, value);
      parent.appendChild(section);
    }
  } else {
    renderMarkdown(parent, result?.text || "NemoClaw returned an empty response.");
  }
}

function captureFromPage(maximum, maximumSelection) {
  const visible = document.body?.innerText || "";
  const selected = globalThis.getSelection?.().toString() || "";
  return {
    document_url: location.href,
    page_title: document.title || "Untitled page",
    page_text: visible.slice(0, maximum),
    page_text_truncated: visible.length > maximum,
    selected_text: selected.slice(0, maximumSelection)
  };
}

function scaledViewportDimensions(width, height) {
  if (!(width > 0 && height > 0)) throw new Error("invalid_viewport_image");
  const edgeScale = Math.min(1, MAX_VIEWPORT_IMAGE_EDGE / Math.max(width, height));
  const pixelScale = Math.min(1, Math.sqrt(MAX_VIEWPORT_IMAGE_PIXELS / (width * height)));
  const scale = Math.min(edgeScale, pixelScale);
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale))
  };
}

async function normalizeViewportImage(dataUrl) {
  if (typeof dataUrl !== "string" || !dataUrl.startsWith("data:image/jpeg;base64,")) {
    throw new Error("invalid_viewport_image");
  }
  const image = new Image();
  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = () => reject(new Error("invalid_viewport_image"));
    image.src = dataUrl;
  });
  const dimensions = scaledViewportDimensions(image.naturalWidth, image.naturalHeight);
  const canvas = document.createElement("canvas");
  canvas.width = dimensions.width;
  canvas.height = dimensions.height;
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) throw new Error("invalid_viewport_image");
  context.drawImage(image, 0, 0, dimensions.width, dimensions.height);
  const normalized = canvas.toDataURL("image/jpeg", 0.9);
  const contentBase64 = normalized.slice(normalized.indexOf(",") + 1);
  const decodedBytes = Math.floor((contentBase64.length * 3) / 4);
  if (!contentBase64 || decodedBytes > MAX_VIEWPORT_IMAGE_BYTES) {
    throw new Error("viewport_image_too_large");
  }
  return {
    mime_type: "image/jpeg",
    content_base64: contentBase64,
    width: dimensions.width,
    height: dimensions.height
  };
}

async function captureViewportImage(windowId) {
  const dataUrl = await chrome.tabs.captureVisibleTab(windowId, {
    format: "jpeg",
    quality: 90
  });
  return normalizeViewportImage(dataUrl);
}

async function captureContext() {
  let page = null;
  let changed = false;
  const onActivated = (info) => {
    if (!page || info.windowId === page.windowId) changed = true;
  };
  const onUpdated = (tabId, info) => {
    if ((!page || tabId === page.tabId) && (info.url || info.status === "loading")) changed = true;
  };
  const onRemoved = (tabId) => {
    if (!page || tabId === page.tabId) changed = true;
  };
  chrome.tabs.onActivated.addListener(onActivated);
  chrome.tabs.onUpdated.addListener(onUpdated);
  chrome.tabs.onRemoved.addListener(onRemoved);
  try {
    page = await readActiveTab();
    const requireSameTab = async () => {
      const [tab] = await chrome.tabs.query({ active: true, windowId: page.windowId });
      if (changed || tab?.id !== page.tabId) throw new Error("page_changed");
    };
    const injection = await chrome.scripting.executeScript({
      target: { tabId: page.tabId },
      func: captureFromPage,
      args: [MAX_PAGE_TEXT_CHARS, MAX_SELECTED_TEXT_CHARS]
    });
    const capture = injection?.[0]?.result;
    const documentId = injection?.[0]?.documentId;
    if (!documentId || !capture?.document_url || sanitizePageUrl(capture.document_url) !== page.page_url) {
      throw new Error("page_changed");
    }
    await requireSameTab();
    const viewportImage = await captureViewportImage(page.windowId);
    await requireSameTab();
    const verification = await chrome.scripting.executeScript({
      target: { tabId: page.tabId },
      func: () => location.href
    });
    if (changed || verification?.[0]?.documentId !== documentId || verification?.[0]?.result !== capture.document_url) {
      throw new Error("page_changed");
    }
    const pageText = String(capture?.page_text || "").trim();
    const selectedText = String(capture?.selected_text || "").trim();
    return {
      page_url: page.page_url,
      page_title: String(capture?.page_title || page.page_title).slice(0, 512),
      capture_mode: "browser",
      page_text: pageText || null,
      page_text_truncated: Boolean(capture?.page_text_truncated),
      selected_text: selectedText,
      viewport_image: viewportImage
    };
  } catch (error) {
    const messages = {
      page_changed: "The active page changed during capture. Keep the target tab open and active, then try again.",
      unsupported_page: "Open a normal HTTP or HTTPS page and click the extension icon again.",
      invalid_viewport_image: "Chrome could not prepare an image of the visible page area.",
      viewport_image_too_large: "The visible page image exceeded the protected request limit. Reduce browser zoom and try again."
    };
    showError(
      "Page context unavailable",
      messages[error.message] || "Click the extension icon on the target page to grant temporary page access.",
      false,
      () => submitMessage(true)
    );
    return null;
  } finally {
    chrome.tabs.onActivated.removeListener(onActivated);
    chrome.tabs.onUpdated.removeListener(onUpdated);
    chrome.tabs.onRemoved.removeListener(onRemoved);
  }
}

function authenticationError() {
  const error = new Error("authentication");
  error.authenticationRequired = true;
  return error;
}

function parseDashboardSessionToken(html) {
  const match = String(html || "").slice(0, 2_000_000).match(
    /window\.__HERMES_SESSION_TOKEN__\s*=\s*("(?:\\.|[^"\\])*")/
  );
  if (!match) return null;
  try {
    const token = JSON.parse(match[1]);
    return typeof token === "string" && token.length >= 16 && token.length <= 512
      ? token
      : null;
  } catch (_) {
    return null;
  }
}

async function loadDashboardSessionToken(signal) {
  if (dashboardSessionTokenOrigin === nemoClawOrigin && dashboardSessionToken) {
    return dashboardSessionToken;
  }
  const response = await fetch(nemoClawDashboardUrl, {
    credentials: "include",
    cache: "no-store",
    redirect: "manual",
    signal
  });
  if (!response.ok) return null;
  const token = parseDashboardSessionToken(await response.text());
  if (!token) return null;
  dashboardSessionToken = token;
  dashboardSessionTokenOrigin = nemoClawOrigin;
  return token;
}

async function authenticatedFetch(url, options = {}) {
  const controller = new AbortController();
  const externalSignal = options.signal;
  const requestOptions = { ...options };
  delete requestOptions.signal;
  const abortFromCaller = () => controller.abort();
  if (externalSignal?.aborted) controller.abort();
  else externalSignal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = setTimeout(() => controller.abort(), HERMES_REQUEST_TIMEOUT_MS);
  try {
    const headers = new Headers(options.headers || {});
    let bearerSession = await sessionAuth.sessionForRequest(nemoClawOrigin, { signal: controller.signal });
    let usedDashboardToken = false;
    if (bearerSession?.accessToken) {
      headers.set("Authorization", `Bearer ${bearerSession.accessToken}`);
    } else {
      const dashboardToken = await loadDashboardSessionToken(controller.signal);
      if (dashboardToken) {
        headers.set("X-Hermes-Session-Token", dashboardToken);
        usedDashboardToken = true;
      }
    }
    let response = await fetch(url, {
      ...requestOptions,
      headers,
      credentials: "include",
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal
    });
    if (response.status === 401 && bearerSession?.refreshToken) {
      bearerSession = await sessionAuth.sessionForRequest(nemoClawOrigin, {
        forceRefresh: true,
        signal: controller.signal
      });
      if (bearerSession?.accessToken) {
        headers.set("Authorization", `Bearer ${bearerSession.accessToken}`);
        response = await fetch(url, {
          ...requestOptions,
          headers,
          credentials: "omit",
          cache: "no-store",
          redirect: "manual",
          signal: controller.signal
        });
      }
    }
    if (response.status === 401 && usedDashboardToken) {
      dashboardSessionToken = null;
      dashboardSessionTokenOrigin = null;
      headers.delete("X-Hermes-Session-Token");
      const renewedDashboardToken = await loadDashboardSessionToken(controller.signal);
      if (renewedDashboardToken) {
        headers.set("X-Hermes-Session-Token", renewedDashboardToken);
        response = await fetch(url, {
          ...requestOptions,
          headers,
          credentials: "include",
          cache: "no-store",
          redirect: "manual",
          signal: controller.signal
        });
      }
    }
    if (
      response.status === 401
      || response.status === 302
      || response.status === 303
      || response.status === 307
      || response.status === 308
      || response.type === "opaqueredirect"
    ) {
      setConnectionState("authentication", "Sign-in required");
      throw authenticationError();
    }
    if (response.status >= 500) {
      setConnectionState("unavailable", `NemoClaw returned HTTP ${response.status}`);
    } else {
      setConnectionState("connected", "Connected to NemoClaw");
    }
    return response;
  } catch (error) {
    if (error?.name === "AbortError") {
      if (externalSignal?.aborted) {
        const cancelled = new Error("Request cancelled.");
        cancelled.cancelled = true;
        throw cancelled;
      }
      setConnectionState("unavailable", "NemoClaw did not respond");
      throw new Error("NemoClaw did not respond within 60 seconds.");
    }
    if (!error?.authenticationRequired) {
      setConnectionState("unavailable", "NemoClaw is unavailable");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", abortFromCaller);
  }
}

async function resolveNemoClawServiceUrl() {
  let lastResponse = null;
  for (const candidate of nemoClawServiceUrls) {
    nemoClawServiceUrl = candidate;
    const response = await authenticatedFetch(conversationsEndpoint());
    if (response.status !== 404) return response;
    lastResponse = response;
  }
  return lastResponse || authenticatedFetch(conversationsEndpoint());
}

async function checkNemoClawConnection(showFailure = true) {
  if (!nemoClawDashboardUrl) {
    setConnectionState("unavailable", "NemoClaw is not configured");
    showSettings();
    return false;
  }
  elements.checkConnectionButton.disabled = true;
  setConnectionState("checking", "Checking NemoClaw…");
  try {
    const response = await resolveNemoClawServiceUrl();
    await readJsonResponse(response, "NemoClaw did not return a valid connection response.");
    setConnectionState("connected", "Connected to NemoClaw");
    return true;
  } catch (error) {
    if (error.authenticationRequired) {
      setConnectionState("authentication", "Sign-in required");
      if (showFailure) {
        showError("Sign in to NemoClaw", "Open NemoClaw, sign in normally, then open Settings and select Check current connection.", true, () => checkNemoClawConnection(true));
      }
    } else {
      setConnectionState("unavailable", "NemoClaw is unavailable");
      if (showFailure) {
        showError("NemoClaw is unavailable", error.message || "The configured NemoClaw service did not respond.", false, () => checkNemoClawConnection(true));
      }
    }
    return false;
  } finally {
    elements.checkConnectionButton.disabled = false;
  }
}

function formatElapsed(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

function renderStatus() {
  const states = {
    loading: ["Loading conversations", "NemoClaw is restoring your recent conversations."],
    starting: ["Starting a conversation", "NemoClaw is preparing the agent conversation."],
    capturing: ["Capturing current page", "Reading available page text and preparing the visible viewport."],
    sending: ["Sending page context", "Transferring your prompt and current browser context to NemoClaw."],
    queued: ["Waiting for agent capacity", "Your request is queued and will start when capacity is available."],
    prompting: ["Working on your request", "NemoClaw is analyzing the current page context."],
    cancelling: ["Stopping", "NemoClaw is interrupting the current response."]
  };
  let [title, detail] = states[currentStatus] || states.queued;
  const tracksElapsed = currentStatus !== "loading" && requestStartedAt !== null;
  const elapsed = tracksElapsed ? Date.now() - requestStartedAt : 0;
  if (elapsed >= 60000 && currentStatus === "queued") {
    title = "Still waiting for capacity";
    detail = "NemoClaw will start when agent capacity is available.";
  } else if (elapsed >= 60000 && currentStatus === "prompting") {
    title = "Still working";
    detail = "Vision and complex reasoning requests can take several minutes.";
  }
  elements.statusTitle.textContent = tracksElapsed ? `${title} · ${formatElapsed(elapsed)}` : title;
  elements.statusDetail.textContent = detail;
  elements.stopButton.hidden = currentStatus === "cancelling" || currentStatus === "loading";
  elements.status.hidden = false;
}

function showStatus(status, options = {}) {
  currentStatus = status;
  if (options.resetElapsed) requestStartedAt = Date.now();
  if (status !== "loading" && requestStartedAt === null) requestStartedAt = Date.now();
  clearInterval(statusTimer);
  renderStatus();
  if (status !== "loading") statusTimer = setInterval(renderStatus, 1000);
}

function hideStatus() {
  clearInterval(statusTimer);
  statusTimer = null;
  currentStatus = null;
  requestStartedAt = null;
  elements.status.hidden = true;
}

function conversationUrl(conversationId, suffix = "") {
  return `${conversationsEndpoint()}/${encodeURIComponent(conversationId)}${suffix}`;
}

function errorDetailFromResponse(response, body, fallback) {
  if (typeof body?.detail === "string") return body.detail;
  return fallback || `NemoClaw returned HTTP ${response.status}.`;
}

async function readJsonResponse(response, fallback) {
  let body = null;
  try { body = await response.json(); } catch (_) {}
  if (response.redirected || response.url?.includes("/login") || response.headers.get("content-type")?.includes("text/html")) {
    throw authenticationError();
  }
  if (!response.ok) throw new Error(errorDetailFromResponse(response, body, fallback));
  if (body === null) throw new Error(fallback || "NemoClaw returned an invalid response.");
  return body;
}

function renderConversationMessages(messages) {
  const followLatest = conversationIsNearBottom();
  elements.messages.replaceChildren();
  if (!messages.length) {
    elements.messages.appendChild(elements.emptyState);
    elements.emptyState.hidden = false;
    return;
  }
  for (const message of messages) {
    const bubble = document.createElement("article");
    bubble.className = `message ${message.role === "user" ? "user" : "assistant"}`;
    appendText(bubble, "div", message.role === "user" ? "You" : "NemoClaw", "message-role");
    if (message.role === "assistant" && message.result) {
      renderResultInto(bubble, message.result);
    } else {
      renderMarkdown(bubble, message.content || "");
    }
    elements.messages.appendChild(bubble);
  }
  if (followLatest) scrollConversationToBottom();
}

async function loadConversation(conversationId, resumePolling = true) {
  const response = await authenticatedFetch(conversationUrl(conversationId));
  const body = await readJsonResponse(response, "NemoClaw could not load this conversation.");
  activeConversationId = body.conversation.conversation_id;
  await chrome.storage.local.set({ askNemoClawConversationId: activeConversationId });
  elements.conversationSelect.value = activeConversationId;
  renderConversationMessages(body.messages || []);
  if (resumePolling && body.active_job) {
    activeJob = { ...body.active_job, conversation_id: activeConversationId };
    showStatus(activeJob.status);
    schedulePoll(activeJob.job_id, activeConversationId);
  } else if (!activeJob) {
    hideStatus();
  }
  return body;
}

async function loadConversationList(preferredId = null, initialResponse = null, loadSelected = true) {
  const response = initialResponse || await authenticatedFetch(conversationsEndpoint());
  const body = await readJsonResponse(response, "NemoClaw could not list recent conversations.");
  const conversations = body.conversations || [];
  elements.conversationSelect.replaceChildren();
  for (const conversation of conversations) {
    const option = document.createElement("option");
    option.value = conversation.conversation_id;
    option.textContent = conversation.title || "New conversation";
    elements.conversationSelect.appendChild(option);
  }
  const selected = conversations.find(item => item.conversation_id === preferredId)?.conversation_id
    || conversations[0]?.conversation_id
    || null;
  if (selected && loadSelected) await loadConversation(selected);
  return selected;
}

function showCreatedConversation(conversation) {
  activeConversationId = conversation.conversation_id;
  const option = document.createElement("option");
  option.value = activeConversationId;
  option.textContent = conversation.title || "New conversation";
  elements.conversationSelect.prepend(option);
  elements.conversationSelect.value = activeConversationId;
  renderConversationMessages([]);
  return chrome.storage.local.set({ askNemoClawConversationId: activeConversationId });
}

async function createConversation({ signal = null, expectedGeneration = null, preserveStatus = false } = {}) {
  clearTimeout(pollTimer);
  activeJob = null;
  if (!preserveStatus) hideStatus();
  clearError();
  const title = activePage?.page_title || "New conversation";
  const response = await authenticatedFetch(conversationsEndpoint(), {
    method: "POST",
    headers: { "Content-Type": "text/plain;charset=UTF-8" },
    body: JSON.stringify({ title }),
    signal
  });
  const body = await readJsonResponse(response, "NemoClaw could not create a conversation.");
  if (expectedGeneration !== null && expectedGeneration !== refreshGeneration) return null;
  await showCreatedConversation(body.conversation);
  elements.prompt.focus();
  return body.conversation;
}

async function refreshPageAndCreateConversation() {
  const generation = ++refreshGeneration;
  refreshController?.abort();
  const controller = new AbortController();
  refreshController = controller;
  elements.refreshButton.disabled = true;
  clearTimeout(pollTimer);
  activeJob = null;
  pendingSubmission = null;
  hideStatus();
  clearError();
  try {
    const pageAvailable = await refreshActivePage(false);
    if (!pageAvailable) {
      showError(
        "Page access unavailable",
        "Open a normal HTTP or HTTPS page and click the Ask NemoClaw toolbar icon, then select Refresh again.",
        false,
        () => refreshPageAndCreateConversation()
      );
      return;
    }
    elements.prompt.value = "";
    await createConversation({ signal: controller.signal, expectedGeneration: generation });
  } catch (error) {
    if (error.cancelled || generation !== refreshGeneration || activeJob || pendingSubmission) return;
    showError(
      "Page refresh failed",
      error.message || "Ask NemoClaw could not reload the active page.",
      false,
      () => refreshPageAndCreateConversation()
    );
  } finally {
    if (refreshController === controller) refreshController = null;
    if (generation === refreshGeneration) elements.refreshButton.disabled = false;
  }
}

async function createNewConversation() {
  const generation = ++refreshGeneration;
  refreshController?.abort();
  const controller = new AbortController();
  refreshController = controller;
  elements.newConversationButton.disabled = true;
  clearTimeout(pollTimer);
  activeJob = null;
  pendingSubmission = null;
  hideStatus();
  clearError();
  try {
    await createConversation({ signal: controller.signal, expectedGeneration: generation });
  } catch (error) {
    if (error.cancelled || generation !== refreshGeneration) return;
    showError(
      "Conversation could not start",
      error.message || "NemoClaw could not create a conversation.",
      false,
      () => createNewConversation()
    );
  } finally {
    if (refreshController === controller) refreshController = null;
    if (generation === refreshGeneration) elements.newConversationButton.disabled = false;
  }
}

function schedulePoll(jobId, conversationId) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(() => pollResponse(jobId, conversationId), 1200);
}

async function pollResponse(jobId, conversationId) {
  if (!conversationId || activeConversationId !== conversationId) return;
  try {
    const response = await authenticatedFetch(conversationUrl(conversationId, `/messages/${encodeURIComponent(jobId)}`));
    const body = await readJsonResponse(response, "The extension could not read the response status from NemoClaw.");
    if (body.conversation_id !== conversationId || activeConversationId !== conversationId) return;
    if (body.status === "complete") {
      activeJob = null;
      pendingSubmission = null;
      hideStatus();
      clearError();
      await loadConversation(conversationId, false);
      return;
    }
    if (body.status === "failed" || body.status === "cancelled") {
      activeJob = null;
      pendingSubmission = null;
      hideStatus();
      await loadConversation(conversationId, false);
      showError(
        body.status === "cancelled" ? "Request stopped" : "NemoClaw request failed",
        body.error?.message || "NemoClaw could not process this request.",
        false,
        null
      );
      return;
    }
    activeJob = { ...body, conversation_id: conversationId };
    showStatus(body.status);
    schedulePoll(jobId, conversationId);
  } catch (error) {
    if (error.authenticationRequired) {
      showError("Sign in to NemoClaw", "Your NemoClaw session is missing or expired. Sign in normally, then try again.", true, () => initialize());
    } else {
      showError("NemoClaw is unavailable", error.message, false, () => pollResponse(jobId, conversationId));
    }
  }
}

function newIdempotencyKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
}

async function submitMessage(retryPending = false) {
  if (!nemoClawDashboardUrl) {
    showError("Configure NemoClaw", "Open Settings and enter the HTTPS URL for your NemoClaw deployment.", false, null);
    showSettings();
    return;
  }
  const prompt = elements.prompt.value.trim();
  if (!retryPending && !prompt) {
    showError("Message required", "Enter the instruction you want NemoClaw to follow.", false, null);
    return;
  }
  if (elements.sendButton.disabled) return;
  ++refreshGeneration;
  refreshController?.abort();
  refreshController = null;
  elements.refreshButton.disabled = false;
  elements.newConversationButton.disabled = true;
  elements.sendButton.disabled = true;
  try {
    showStatus(activeConversationId ? "capturing" : "starting", { resetElapsed: true });
    if (!activeConversationId) {
      await createConversation({ preserveStatus: true });
      showStatus("capturing");
    }
    let submission = retryPending ? pendingSubmission : null;
    if (!submission) {
      const context = await captureContext();
      if (!context) {
        hideStatus();
        return;
      }
      submission = {
        conversationId: activeConversationId,
        idempotencyKey: newIdempotencyKey(),
        body: { ...context, prompt }
      };
      pendingSubmission = submission;
    }
    clearError();
    showStatus("sending");
    const response = await authenticatedFetch(conversationUrl(submission.conversationId, "/messages"), {
      method: "POST",
      headers: {
        "Content-Type": "text/plain;charset=UTF-8",
        "Idempotency-Key": submission.idempotencyKey
      },
      body: JSON.stringify(submission.body)
    });
    const body = await readJsonResponse(response, "NemoClaw did not accept this message.");
    activeJob = { ...body, conversation_id: submission.conversationId };
    elements.prompt.value = "";
    if (activeConversationId === submission.conversationId) {
      await loadConversation(submission.conversationId, false);
      showStatus(body.status);
      schedulePoll(body.job_id, submission.conversationId);
    }
  } catch (error) {
    activeJob = null;
    hideStatus();
    if (error.authenticationRequired) {
      showError("Sign in to NemoClaw", "Your NemoClaw session is missing or expired. Sign in normally, then try again.", true, () => submitMessage(true));
    } else {
      showError("Request could not start", error.message || "NemoClaw did not accept the message.", false, () => submitMessage(true));
    }
  } finally {
    elements.sendButton.disabled = false;
    elements.newConversationButton.disabled = false;
  }
}

async function stopActiveJob() {
  const conversationId = activeJob?.conversation_id || activeConversationId;
  if (!conversationId || !activeJob?.job_id) return;
  elements.stopButton.disabled = true;
  try {
    const response = await authenticatedFetch(
      conversationUrl(conversationId, `/messages/${encodeURIComponent(activeJob.job_id)}/cancel`),
      { method: "POST", headers: { "Content-Type": "text/plain;charset=UTF-8" }, body: "{}" }
    );
    const body = await readJsonResponse(response, "NemoClaw could not stop this request.");
    activeJob = { ...body, conversation_id: conversationId };
    showStatus(body.status);
    schedulePoll(body.job_id, conversationId);
  } catch (error) {
    showError("Stop failed", error.message, false, () => stopActiveJob());
  } finally {
    elements.stopButton.disabled = false;
  }
}

async function initialize() {
  elements.sendButton.disabled = true;
  elements.newConversationButton.disabled = true;
  elements.refreshButton.disabled = true;
  clearError();
  showStatus("loading");
  const configured = await loadNemoClawOrigin();
  await refreshActivePage(false);
  if (!configured) {
    hideStatus();
    setConnectionState("unavailable", "NemoClaw is not configured");
    showSettings();
    return;
  }
  if (isBrevSecureLink(nemoClawDashboardUrl)) {
    hideStatus();
    setConnectionState("unavailable", "Brev Secure Link is incompatible");
    showError(
      "Use a localhost Brev port forward",
      "Brev Secure Links require redirect-based browser authentication that extension API requests cannot complete. Forward the Hermes dashboard port and configure its http://127.0.0.1 URL in Settings.",
      false,
      showSettings
    );
    return;
  }
  try {
    const stored = await chrome.storage.local.get("askNemoClawConversationId");
    const listResponse = await resolveNemoClawServiceUrl();
    const selected = await loadConversationList(stored.askNemoClawConversationId || null, listResponse);
    if (!selected) await createConversation();
  } catch (error) {
    if (error.authenticationRequired) {
      showError("Sign in to NemoClaw", "Sign in normally to load your Ask NemoClaw conversations.", true, () => initialize());
    } else {
      showError("NemoClaw is unavailable", error.message || "The extension could not load NemoClaw.", false, () => initialize());
    }
  } finally {
    if (!activeJob) hideStatus();
    elements.sendButton.disabled = false;
    elements.newConversationButton.disabled = false;
    elements.refreshButton.disabled = false;
  }
}

elements.composer.addEventListener("submit", event => {
  event.preventDefault();
  submitMessage(false);
});
elements.retryButton.addEventListener("click", () => retryAction?.());
elements.newConversationButton.addEventListener("click", createNewConversation);
elements.refreshButton.addEventListener("click", refreshPageAndCreateConversation);
elements.checkConnectionButton.addEventListener("click", () => checkNemoClawConnection(true));
elements.openNemoClawButton.addEventListener("click", () => {
  if (nemoClawDashboardUrl) chrome.tabs.create({ url: nemoClawConversationDashboardUrl() });
  else showSettings();
});
elements.settingsButton.addEventListener("click", showSettings);
elements.settingsForm.addEventListener("submit", event => saveSettings(event).catch(error => {
  elements.settingsError.textContent = error.message || "The NemoClaw settings could not be saved.";
  elements.settingsError.hidden = false;
}));
elements.cancelSettingsButton.addEventListener("click", () => { elements.settingsCard.hidden = true; });
elements.disconnectButton.addEventListener("click", () => disconnectNemoClaw().catch(error => {
  elements.settingsError.textContent = error.message || "The NemoClaw connection could not be removed.";
  elements.settingsError.hidden = false;
}));
elements.conversationSelect.addEventListener("change", async () => {
  clearTimeout(pollTimer);
  activeJob = null;
  pendingSubmission = null;
  hideStatus();
  clearError();
  try { await loadConversation(elements.conversationSelect.value); }
  catch (error) { showError("Conversation could not load", error.message, false, () => loadConversation(elements.conversationSelect.value)); }
});
elements.stopButton.addEventListener("click", stopActiveJob);
elements.signInButton.addEventListener("click", () => {
  if (nemoClawDashboardUrl) chrome.tabs.create({ url: new URL("/login", nemoClawDashboardUrl).href });
  else showSettings();
});
elements.prompt.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    submitMessage(false);
  }
});

chrome.runtime.onMessage.addListener(message => {
  if (message?.type === "active-tab-granted") {
    refreshActivePage(false);
  }
});

initialize();
