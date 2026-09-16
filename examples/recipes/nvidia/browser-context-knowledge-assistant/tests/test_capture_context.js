// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../extension/sidepanel.js"), "utf8");
const captureSource = source.slice(source.indexOf("async function captureViewportImage("), source.indexOf("function authenticationError("));

function event() {
  const listeners = new Set();
  return {
    addListener: (listener) => listeners.add(listener),
    removeListener: (listener) => listeners.delete(listener),
    emit: (...args) => { for (const listener of listeners) listener(...args); },
    get size() { return listeners.size; }
  };
}

async function captureWith(change = () => {}, at = "injection") {
  const tabs = { onActivated: event(), onUpdated: event(), onRemoved: event() };
  const state = { tabId: 1, documentId: "document-a", url: "https://example.com/a", screenshots: 0 };
  const errors = [];
  let injections = 0;
  tabs.query = async () => [{ id: state.tabId }];
  tabs.captureVisibleTab = async () => {
    state.screenshots++;
    if (at === "screenshot") change(state, tabs);
    return "data:image/jpeg;base64,synthetic";
  };
  const context = vm.createContext({
    chrome: {
      tabs,
      scripting: { executeScript: async () => {
        if (injections++ > 0) return [{ documentId: state.documentId, result: state.url }];
        const result = [{ documentId: "document-a", result: {
          document_url: "https://example.com/a", page_title: "Page A", page_text: "Text from A", selected_text: "Selection A"
        } }];
        if (at === "injection") change(state, tabs);
        return result;
      } }
    },
    readActiveTab: async () => ({ tabId: 1, windowId: 10, page_url: "https://example.com/a", page_title: "Page A" }),
    captureFromPage: () => {},
    sanitizePageUrl: (url) => url,
    normalizeViewportImage: async () => ({ content_base64: "synthetic" }),
    MAX_PAGE_TEXT_CHARS: 1000, MAX_SELECTED_TEXT_CHARS: 100,
    showError: (...args) => errors.push(args), submitMessage: () => {}
  });
  vm.runInContext(captureSource, context);
  const result = await context.captureContext();
  for (const name of ["onActivated", "onUpdated", "onRemoved"]) assert.equal(tabs[name].size, 0);
  return { result, state, errors };
}

test("captures an unchanged tab and document", async () => {
  const { result, errors } = await captureWith();
  assert.equal(result.page_url, "https://example.com/a");
  assert.equal(result.page_text, "Text from A");
  assert.equal(result.viewport_image.content_base64, "synthetic");
  assert.equal(errors.length, 0);
});

test("rejects a tab switch before the screenshot", async () => {
  const { result, state } = await captureWith((state) => { state.tabId = 2; });
  assert.equal(result, null);
  assert.equal(state.screenshots, 0);
});

test("rejects switching away and back while taking the screenshot", async () => {
  const { result, errors } = await captureWith((state, tabs) => {
    tabs.onActivated.emit({ tabId: 2, windowId: 10 });
    tabs.onActivated.emit({ tabId: 1, windowId: 10 });
  }, "screenshot");
  assert.equal(result, null);
  assert.match(errors[0][1], /changed during capture/);
});

test("rejects a reload even when the URL is unchanged", async () => {
  const { result } = await captureWith((state) => { state.documentId = "document-b"; }, "screenshot");
  assert.equal(result, null);
});

test("rejects a same-document URL change", async () => {
  const { result } = await captureWith((state) => { state.url = "https://example.com/b"; }, "screenshot");
  assert.equal(result, null);
});

test("rejects navigation away and back to the original URL", async () => {
  const { result } = await captureWith((state, tabs) => {
    tabs.onUpdated.emit(1, { url: "https://example.com/b" });
    tabs.onUpdated.emit(1, { url: "https://example.com/a" });
  }, "screenshot");
  assert.equal(result, null);
});

test("rejects closing the captured tab", async () => {
  const { result } = await captureWith((state, tabs) => tabs.onRemoved.emit(1), "screenshot");
  assert.equal(result, null);
});

test("ignores changes in another window or tab", async () => {
  const { result } = await captureWith((state, tabs) => {
    tabs.onActivated.emit({ tabId: 2, windowId: 20 });
    tabs.onUpdated.emit(2, { status: "loading" });
    tabs.onRemoved.emit(2);
  }, "screenshot");
  assert.notEqual(result, null);
});
