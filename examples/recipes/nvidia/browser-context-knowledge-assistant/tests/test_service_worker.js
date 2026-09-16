// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../extension/service-worker.js"), "utf8");
let clickHandler = null;
let storedTarget = null;
const context = {
  URL,
  console,
  chrome: {
    sidePanel: {
      setPanelBehavior: async () => {},
      open: async () => {}
    },
    action: {
      onClicked: { addListener: handler => { clickHandler = handler; } }
    },
    runtime: {
      onInstalled: { addListener: () => {} },
      onStartup: { addListener: () => {} },
      sendMessage: async () => {}
    },
    storage: {
      session: {
        set: async value => { storedTarget = value.askNemoClawTarget; },
        remove: async () => { storedTarget = null; }
      }
    }
  }
};
context.globalThis = context;
vm.runInNewContext(source, context);

(async () => {
  assert.equal(typeof clickHandler, "function");
  await clickHandler({
    id: 17,
    windowId: 3,
    title: "Example video",
    url: "https://www.youtube.com/watch?v=video123&access_token=secret#chapter"
  });
  assert.equal(storedTarget.page_url, "https://www.youtube.com/watch?v=video123");
  assert.equal(storedTarget.page_title, "Example video");
  console.log("service-worker target sanitization: OK");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
