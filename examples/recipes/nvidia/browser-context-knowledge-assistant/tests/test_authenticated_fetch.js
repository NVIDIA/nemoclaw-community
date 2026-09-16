// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../extension/sidepanel.js"), "utf8");
const start = source.indexOf("function authenticationError");
const end = source.indexOf("async function resolveNemoClawServiceUrl", start);
assert.ok(start >= 0 && end > start);

const requests = [];
const connectionStates = [];
const origin = "https://agent.example.test";
const oldToken = "old-dashboard-token-value";
const newToken = "new-dashboard-token-value";
const context = {
  AbortController,
  Error,
  Headers,
  JSON,
  setTimeout,
  clearTimeout,
  nemoClawOrigin: origin,
  nemoClawDashboardUrl: `${origin}/`,
  dashboardSessionToken: oldToken,
  dashboardSessionTokenOrigin: origin,
  HERMES_REQUEST_TIMEOUT_MS: 1000,
  sessionAuth: { sessionForRequest: async () => null },
  setConnectionState: (state, label) => connectionStates.push({ state, label }),
  fetch: async (url, options = {}) => {
    requests.push({ url, token: options.headers?.get?.("X-Hermes-Session-Token") || null });
    if (url === `${origin}/`) {
      return {
        ok: true,
        status: 200,
        text: async () => `<script>window.__HERMES_SESSION_TOKEN__=${JSON.stringify(newToken)};</script>`
      };
    }
    const token = options.headers.get("X-Hermes-Session-Token");
    return { status: token === newToken ? 200 : 401, type: "basic", url };
  }
};
context.globalThis = context;
vm.runInNewContext(
  `${source.slice(start, end)}\nglobalThis.authenticatedFetchForTest = authenticatedFetch;`,
  context
);

(async () => {
  const response = await context.authenticatedFetchForTest(`${origin}/api/plugins/ask-nemoclaw/conversations`);
  assert.equal(response.status, 200);
  assert.deepEqual(requests.map(request => request.token), [oldToken, null, newToken]);
  assert.equal(connectionStates.at(-1).state, "connected");
  console.log("dashboard session-token recovery: OK");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
