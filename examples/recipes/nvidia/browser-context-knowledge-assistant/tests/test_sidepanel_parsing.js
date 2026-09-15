// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../extension/sidepanel.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../extension/sidepanel.html"), "utf8");
assert.match(source, /CANONICAL_SERVICE_PATH = "\/api\/plugins\/ask-nemoclaw"/);
assert.match(source, /nemoClawServiceUrl/);
assert.match(source, /nemoClawDashboardUrl/);
assert.match(source, /askNemoClawUrl/);
assert.match(source, /askNemoClawConfiguredByUser/);
assert.match(source, /inferredServiceUrls/);
assert.match(source, /"\/ask-nemoclaw"/);
assert.match(source, /askNemoClawServiceUrl/);
assert.match(source, /askNemoClawDashboardUrl/);
assert.doesNotMatch(source, /requestsBrandingReview|REVIEW_ENDPOINT|REVIEW_FIELDS|GOOGLE_DOC_PATTERN|window\.confirm/);
assert.match(source, /askNemoClawConversationId/);
assert.match(source, /Idempotency-Key/);
assert.match(source, /captureContext\(\)/);
assert.match(source, /chrome\.tabs\.captureVisibleTab/);
assert.match(source, /viewport_image: viewportImage/);
assert.match(source, /Available page text \+ visible viewport/);
assert.match(source, /page_text: pageText \|\| null/);
assert.doesNotMatch(source, /empty_page/);
assert.match(source, /function scrollConversationToBottom/);
assert.match(source, /document\.documentElement\.scrollHeight/);
assert.match(source, /behavior: "auto"/);
assert.doesNotMatch(source, /behavior: "smooth"/);
assert.ok(html.indexOf('id="messages"') < html.indexOf('id="status-card"'));
assert.match(source, /refreshPageAndCreateConversation/);
assert.match(source, /await refreshActivePage\(false\)[\s\S]*await createConversation\(\)/);
assert.match(source, /redirect: "manual"/);
assert.match(source, /window\\\.\__HERMES_SESSION_TOKEN__/);
assert.match(source, /X-Hermes-Session-Token/);
assert.match(source, /fetch\(nemoClawDashboardUrl/);
assert.match(source, /sessionAuth\.sessionForRequest/);
assert.match(source, /\.gobrev\.dev/);
assert.match(source, /Brev Secure Links use redirect-based browser authentication/);
assert.match(source, /Authorization/);
assert.match(source, /forceRefresh: true/);
assert.match(source, /disconnectNemoClaw/);
assert.doesNotMatch(source, /if \(!isLoopbackOrigin\(nemoClawOrigin\)\) return null/);
assert.doesNotMatch(source, /storage\.(?:local|sync)\.set\([^)]*(?:SessionToken|sessionToken|token)/s);
assert.match(source, /response\.type === "opaqueredirect"/);
assert.match(source, /response\.headers\.get\("content-type"\)\?\.includes\("text\/html"\)/);
assert.match(source, /HERMES_REQUEST_TIMEOUT_MS = 60000/);
assert.match(source, /NemoClaw did not respond within 60 seconds/);
assert.match(source, /generation !== refreshGeneration \|\| activeJob \|\| pendingSubmission/);
assert.match(source, /refreshController\?\.abort\(\)/);
assert.match(source, /loadConversation\(submission\.conversationId, false\)/);
assert.match(source, /schedulePoll\(body\.job_id, submission\.conversationId\)/);
assert.doesNotMatch(source, /conversationUrl\(activeConversationId, `\/messages\/\$\{encodeURIComponent\(jobId\)\}`\)/);
assert.match(source, /conversationIsNearBottom\(\)/);
const showStatusStart = source.indexOf("function showStatus");
const showStatusEnd = source.indexOf("function hideStatus", showStatusStart);
assert.doesNotMatch(source.slice(showStatusStart, showStatusEnd), /scrollConversationToBottom/);
assert.match(source, /Loading conversations/);
assert.match(source, /Capturing current page/);
assert.match(source, /Sending page context/);
assert.match(source, /Waiting for agent capacity/);
assert.match(source, /Working on your request/);
assert.match(source, /Still working/);
assert.match(source, /Vision and complex reasoning requests can take several minutes/);
assert.match(source, /setInterval\(renderStatus, 1000\)/);
assert.match(source, /formatElapsed\(elapsed\)/);
assert.doesNotMatch(source, /NemoClaw is responding/);
assert.match(source, /checkNemoClawConnection/);
assert.match(source, /Connected to NemoClaw/);
assert.match(source, /Sign-in required/);
assert.match(source, /chrome\.permissions\.request/);
assert.match(source, /chrome\.permissions\.remove/);
assert.match(source, /stored\.askNemoClawConfiguredByUser === true/);
assert.match(source, /NemoClaw is not configured/);
assert.match(source, /const configured = await loadNemoClawOrigin\(\)/);
assert.doesNotMatch(source, /Ask NemoClaw requires HTTPS or an HTTP loopback NemoClaw origin/);
assert.match(source, /askNemoClawOrigin/);
assert.match(source, /chrome\.tabs\.create\(\{ url: nemoClawDashboardUrl \}\)/);
assert.match(html, /id="settings-button"/);
assert.match(html, /aria-label="NemoClaw settings"/);
assert.match(html, /id="nemoclaw-url"/);
assert.match(html, /id="disconnect-button"/);
assert.doesNotMatch(html, /id="nemoclaw-service-url"/);
assert.doesNotMatch(html, /id="nemoclaw-dashboard-url"/);
assert.ok(html.indexOf('id="settings-card"') < html.indexOf('id="check-connection-button"'));
assert.match(html, /memory-backed session storage/);
assert.doesNotMatch(source, /storage\.(?:local|sync)\.set\([^)]*(?:page_text|result|messages)/s);
const tokenParserStart = source.indexOf("function parseDashboardSessionToken");
const tokenParserEnd = source.indexOf("async function loadDashboardSessionToken", tokenParserStart);
assert.ok(tokenParserStart >= 0 && tokenParserEnd > tokenParserStart);
const tokenContext = {};
vm.runInNewContext(
  `${source.slice(tokenParserStart, tokenParserEnd)}\nglobalThis.parseToken = parseDashboardSessionToken;`,
  tokenContext
);
assert.equal(
  tokenContext.parseToken('<script>window.__HERMES_SESSION_TOKEN__="0123456789abcdef";</script>'),
  "0123456789abcdef"
);
assert.equal(tokenContext.parseToken('<script>window.__HERMES_SESSION_TOKEN__="short";</script>'), null);
assert.equal(tokenContext.parseToken("<html>no token</html>"), null);
const start = source.indexOf("function parseMarkdownBlocks");
const end = source.indexOf("function appendInlineMarkdown", start);
assert.ok(start >= 0 && end > start);

const context = {};
vm.runInNewContext(
  `${source.slice(start, end)}\nglobalThis.parseMarkdown = parseMarkdownBlocks;`,
  context
);

const markdown = `## Technical Review

**Required:** Correct the product name.

- First issue
- [x] Verified item
- [ ] Open item

| Issue | Fix |
| --- | --- |
| Name | Standardize it |
`;
const blocks = context.parseMarkdown(markdown);
assert.deepEqual(Array.from(blocks, block => block.type), ["heading", "paragraph", "list", "table"]);
assert.equal(blocks[2].items[1].checked, true);
assert.equal(blocks[2].items[2].checked, false);
assert.equal(blocks[3].rows[0][1], "Standardize it");

const captureStart = source.indexOf("function captureFromPage");
const captureEnd = source.indexOf("async function captureContext", captureStart);
const captureContext = {
  location: { href: "https://example.com/article" },
  document: { title: "Example", body: { innerText: "Visible browser text" } },
  getSelection: () => ({ toString: () => "Selected text" }),
  MAX_VIEWPORT_IMAGE_EDGE: 2048,
  MAX_VIEWPORT_IMAGE_PIXELS: 4000000
};
vm.runInNewContext(
  `${source.slice(captureStart, captureEnd)}\nglobalThis.capture = captureFromPage; globalThis.scale = scaledViewportDimensions;`,
  captureContext
);
const captured = captureContext.capture(10, 8);
assert.equal(captured.document_url, "https://example.com/article");
assert.equal(captured.page_text, "Visible br");
assert.equal(captured.page_text_truncated, true);
assert.equal(captured.selected_text, "Selected");
const scaled = captureContext.scale(3840, 2160);
assert.ok(scaled.width <= 2048);
assert.ok(scaled.width * scaled.height <= 4000000);

const sanitizerStart = source.indexOf("const SENSITIVE_QUERY_PARAMETER");
const sanitizerEnd = source.indexOf("async function readActiveTab", sanitizerStart);
assert.ok(sanitizerStart >= 0 && sanitizerEnd > sanitizerStart);
const sanitizerContext = { URL };
vm.runInNewContext(
  `${source.slice(sanitizerStart, sanitizerEnd)}\nglobalThis.sanitize = sanitizePageUrl;`,
  sanitizerContext
);
assert.equal(
  sanitizerContext.sanitize("https://www.youtube.com/watch?v=example123&access_token=secret#chapter"),
  "https://www.youtube.com/watch?v=example123"
);

console.log("side-panel response normalization: OK");
