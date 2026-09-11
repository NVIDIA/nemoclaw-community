// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_CATALOG_STATE } from "../../site/scripts/catalog-state.mjs";
import { initCatalog, initCategoryInfo } from "../../site/scripts/catalog.mjs";

test("category information buttons toggle one description at a time", () => {
  function informationControl() {
    const listeners = new Map();
    const containerListeners = new Map();
    const attributes = new Map([["aria-expanded", "false"]]);
    const button = {
      addEventListener: (type, listener) => listeners.set(type, listener),
      emit: (type, event) => listeners.get(type)?.(event),
      getAttribute: (name) => attributes.get(name) ?? null,
      setAttribute: (name, value) => attributes.set(name, value),
    };
    const container = {
      dataset: {},
      addEventListener: (type, listener) => containerListeners.set(type, listener),
      emit: (type) => containerListeners.get(type)?.(),
      querySelector: () => button,
    };
    return { attributes, button, container };
  }

  const first = informationControl();
  const second = informationControl();
  const documentListeners = new Map();
  initCategoryInfo({
    querySelectorAll: () => [first.container, second.container],
    addEventListener: (type, listener) => documentListeners.set(type, listener),
  });

  first.button.emit("click");
  assert.equal(first.container.dataset.open, "true");
  assert.equal(first.attributes.get("aria-expanded"), "true");

  first.button.emit("click");
  assert.equal(first.container.dataset.open, "false");
  assert.equal(first.container.dataset.dismissed, "true");
  assert.equal(first.attributes.get("aria-expanded"), "false");

  first.container.emit("pointerleave");
  assert.equal(first.container.dataset.dismissed, "false");
  first.button.emit("click");

  second.button.emit("click");
  assert.equal(first.container.dataset.open, "false");
  assert.equal(second.container.dataset.open, "true");

  second.button.emit("keydown", { key: "Escape" });
  assert.equal(second.container.dataset.open, "false");
  assert.equal(second.container.dataset.dismissed, "true");

  second.button.emit("click");

  documentListeners.get("click")({ target: { closest: () => null } });
  assert.equal(second.container.dataset.open, "false");
});

function fakeControl(properties = {}) {
  const listeners = new Map();
  return {
    hidden: false,
    disabled: false,
    dataset: {},
    value: "",
    checked: false,
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    emit(type) {
      listeners.get(type)?.();
    },
    focus() {},
    ...properties,
  };
}

function fakeCatalogDOM() {
  const nvidiaCard = fakeControl({
    dataset: {
      category: "nvidia-recipes",
      industry: "financial-services",
      collections: "",
      maintenance: "current",
      search: "payment operations",
    },
  });
  const partnerCard = fakeControl({
    dataset: {
      category: "partner-recipes",
      industry: "financial-services",
      collections: "",
      maintenance: "current",
      search: "x402 payment",
    },
  });

  function group(category, cards) {
    const attributes = new Map();
    return fakeControl({
      dataset: { catalogCategory: category },
      matches: (selector) => selector === "[data-catalog-category]",
      closest: () => null,
      querySelectorAll: (selector) => selector === "[data-catalog-entry]" ? cards : [],
      setAttribute: (name, value) => attributes.set(name, value),
      removeAttribute: (name) => attributes.delete(name),
    });
  }

  const nvidiaGroup = group("nvidia-recipes", [nvidiaCard]);
  const partnerGroup = group("partner-recipes", [partnerCard]);
  const category = fakeControl({ value: "all" });
  const industry = fakeControl({ value: "all" });
  const maintenance = fakeControl({ value: "maintained" });
  const categoryWrapper = fakeControl({
    dataset: { filterFor: "category" },
    querySelectorAll: () => [category],
  });
  const industryWrapper = fakeControl({
    dataset: { filterFor: "industry" },
    querySelectorAll: () => [industry],
  });
  const controls = fakeControl({
    hidden: true,
    querySelectorAll: () => [categoryWrapper, industryWrapper],
  });
  const categoryPanel = fakeControl({ hidden: false });
  const industryPanel = fakeControl({ hidden: true });
  const elements = {
    "catalog-controls": controls,
    "catalog-view-controls": fakeControl({ hidden: true }),
    "catalog-search": fakeControl(),
    "catalog-view-category": fakeControl(),
    "catalog-view-industry": fakeControl(),
    "catalog-category": category,
    "catalog-industry": industry,
    "catalog-maintenance": maintenance,
    "catalog-reset": fakeControl(),
    "catalog-status": fakeControl({ textContent: "" }),
    "catalog-empty": fakeControl({ hidden: true }),
    "catalog-results": fakeControl({
      dataset: {},
      querySelectorAll(selector) {
        if (selector === "[data-catalog-entry]") return [nvidiaCard, partnerCard];
        if (selector === "[data-catalog-category]") return [nvidiaGroup, partnerGroup];
        return [];
      },
    }),
    "browse-category-panel": categoryPanel,
    "browse-industry-panel": industryPanel,
    "nvidia-recipes": nvidiaGroup,
  };
  const location = {
    pathname: "/nemoclaw-community/",
    search: "?view=industry&industry=financial-services",
    hash: "#nvidia-recipes",
  };
  function applyHistoryURL(relativeURL) {
    const parsed = new URL(relativeURL, "https://example.test");
    location.pathname = parsed.pathname;
    location.search = parsed.search;
    location.hash = parsed.hash;
  }
  const windowListeners = new Map();
  const windowObject = {
    location,
    history: {
      pushState: (_state, _title, url) => applyHistoryURL(url),
      replaceState: (_state, _title, url) => applyHistoryURL(url),
    },
    addEventListener: (type, listener) => windowListeners.set(type, listener),
  };
  const documentObject = {
    getElementById: (id) => elements[id] ?? null,
  };
  return { documentObject, windowObject, elements, nvidiaCard, partnerCard };
}

test("an explicit view change clears a reconciled category fragment", () => {
  const fixture = fakeCatalogDOM();
  const catalog = initCatalog(fixture);

  assert.deepEqual(catalog.getState(), {
    ...DEFAULT_CATALOG_STATE,
    category: "nvidia-recipes",
  });
  assert.equal(fixture.nvidiaCard.hidden, false);
  assert.equal(fixture.partnerCard.hidden, true);

  fixture.elements["catalog-view-industry"].emit("click");

  assert.deepEqual(catalog.getState(), {
    ...DEFAULT_CATALOG_STATE,
    view: "industry",
  });
  assert.equal(fixture.windowObject.location.hash, "");
  assert.equal(fixture.elements["catalog-results"].dataset.view, "industry");
  assert.equal(fixture.elements["browse-category-panel"].hidden, true);
  assert.equal(fixture.elements["browse-industry-panel"].hidden, false);
  assert.equal(fixture.nvidiaCard.hidden, false);
  assert.equal(fixture.partnerCard.hidden, false);
});
