// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../extension/auth-session.js"), "utf8");

function makeContext({ cookies = [], stored = {}, fetchImpl = null } = {}) {
  const sessionWrites = [];
  const sessionRemovals = [];
  const cookieWrites = [];
  const context = {
    Date,
    JSON,
    URL,
    chrome: {
      cookies: {
        getAll: async details => {
          assert.equal(details.url, "https://agent.example.test/");
          return cookies;
        },
        set: async details => {
          cookieWrites.push(details);
          return details;
        }
      },
      storage: {
        session: {
          get: async key => ({ [key]: stored[key] }),
          set: async value => {
            sessionWrites.push(value);
            Object.assign(stored, value);
          },
          remove: async key => {
            sessionRemovals.push(key);
            delete stored[key];
          }
        }
      }
    },
    fetch: fetchImpl || (async () => { throw new Error("unexpected fetch"); })
  };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return { auth: context.AskNemoClawAuth, sessionWrites, sessionRemovals, cookieWrites };
}

(async () => {
  const future = Date.now() / 1000 + 600;
  const cookieContext = makeContext({
    cookies: [
      { name: "__Host-hermes_session_at", value: "access-token-value", expirationDate: future },
      { name: "__Host-hermes_session_rt", value: "refresh-token-value", expirationDate: future + 600 },
      { name: "__Host-hermes_session_provider", value: "basic", expirationDate: future + 600 }
    ]
  });
  const fromCookie = await cookieContext.auth.sessionForRequest("https://agent.example.test");
  assert.equal(fromCookie.accessToken, "access-token-value");
  assert.equal(fromCookie.refreshToken, "refresh-token-value");
  assert.equal(fromCookie.provider, "basic");
  assert.equal(cookieContext.sessionWrites.length, 1);
  const adopted = cookieContext.sessionWrites[0].askNemoClawBearerSession;
  assert.equal(adopted.accessCookie.value, undefined);
  assert.equal(adopted.refreshCookie.value, undefined);

  let refreshRequest = null;
  const expiredStored = {
    askNemoClawBearerSession: {
      origin: "https://agent.example.test",
      accessToken: "expired-access-token",
      refreshToken: "stored-refresh-token",
      provider: "basic",
      expiresAt: 1,
      accessCookie: {
        name: "__Host-hermes_session_at",
        value: "must-not-be-copied"
      },
      refreshCookie: {
        name: "__Host-hermes_session_rt",
        value: "must-not-be-copied"
      }
    }
  };
  const refreshContext = makeContext({
    stored: expiredStored,
    fetchImpl: async (url, options) => {
      refreshRequest = { url, options };
      return {
        ok: true,
        status: 200,
        json: async () => ({
          access_token: "rotated-access-token",
          refresh_token: "rotated-refresh-token",
          expires_at: future,
          provider: "basic"
        })
      };
    }
  });
  const refreshController = new AbortController();
  const refreshed = await refreshContext.auth.sessionForRequest(
    "https://agent.example.test",
    { forceRefresh: true, signal: refreshController.signal }
  );
  assert.equal(refreshRequest.url, "https://agent.example.test/auth/native/refresh");
  assert.equal(refreshRequest.options.credentials, "omit");
  assert.equal(refreshRequest.options.signal, refreshController.signal);
  assert.deepEqual(
    JSON.parse(refreshRequest.options.body),
    { refresh_token: "stored-refresh-token", provider: "basic" }
  );
  assert.equal(refreshed.accessToken, "rotated-access-token");
  assert.equal(expiredStored.askNemoClawBearerSession.refreshToken, "rotated-refresh-token");
  assert.equal(expiredStored.askNemoClawBearerSession.accessCookie.value, undefined);
  assert.equal(expiredStored.askNemoClawBearerSession.refreshCookie.value, undefined);
  assert.equal(refreshContext.cookieWrites.length, 2);
  assert.equal(refreshContext.cookieWrites[0].name, "__Host-hermes_session_at");
  assert.equal(refreshContext.cookieWrites[0].value, "rotated-access-token");
  assert.equal(refreshContext.cookieWrites[1].name, "__Host-hermes_session_rt");
  assert.equal(refreshContext.cookieWrites[1].value, "rotated-refresh-token");

  await refreshContext.auth.clearSession();
  assert.equal(refreshContext.sessionRemovals.length, 1);

  console.log("extension authentication session: OK");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
