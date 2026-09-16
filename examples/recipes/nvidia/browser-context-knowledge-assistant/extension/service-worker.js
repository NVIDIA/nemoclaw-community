// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

async function configureAction() {
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false });
}

configureAction().catch(() => {});

function sanitizedTarget(tab) {
  try {
    const url = new URL(tab.url || "");
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    const sensitiveQueryParameter = /(?:^|[_-])(?:access[_-]?token|auth|authorization|code|credential|jwt|key|password|refresh[_-]?token|secret|session|sig|signature|state|token)(?:$|[_-])/i;
    for (const key of [...url.searchParams.keys()]) {
      if (sensitiveQueryParameter.test(key)) url.searchParams.delete(key);
    }
    url.hash = "";
    return {
      tabId: tab.id,
      windowId: tab.windowId,
      page_url: url.href,
      page_title: String(tab.title || "Untitled page").slice(0, 512)
    };
  } catch (_) {
    return null;
  }
}

chrome.runtime.onInstalled.addListener(() => {
  configureAction().catch(() => {});
});

chrome.runtime.onStartup.addListener(() => {
  configureAction().catch(() => {});
});

chrome.action.onClicked.addListener(async tab => {
  if (!tab.id || !Number.isInteger(tab.windowId)) return;
  // Call open synchronously from the toolbar event. Awaiting another API first
  // can consume Chrome's user gesture and cause sidePanel.open() to fail.
  const panelPromise = chrome.sidePanel.open({ windowId: tab.windowId });
  const target = sanitizedTarget(tab);
  try {
    if (target) {
      await chrome.storage.session.set({ askNemoClawTarget: target });
    } else {
      await chrome.storage.session.remove("askNemoClawTarget");
    }
  } catch (_) {
    // Opening the panel must not depend on caching.
  }
  try {
    await panelPromise;
  } catch (error) {
    console.error("Ask NemoClaw could not open the side panel", error);
    return;
  }
  try {
    await chrome.runtime.sendMessage({ type: "active-tab-granted", tabId: tab.id });
  } catch (_) {
    // The panel may not have loaded its message listener yet.
  }
});
