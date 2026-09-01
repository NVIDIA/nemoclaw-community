// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { execFileSync } from "node:child_process";
import test from "node:test";

import {
  CATALOG_CATEGORIES,
  CATALOG_COLLECTION_CATEGORIES,
  CATALOG_INDUSTRIES,
  CATALOG_MAINTENANCE,
  DEFAULT_CATALOG_STATE,
  canonicalizeCatalogState,
  initCatalog,
  initCategoryInfo,
  matchesCatalogRecord,
  normalizeSearchText,
  parseCatalogURLState,
  serializeCatalogURLState,
  tokenizeQuery,
} from "../../site/catalog.mjs";
import { decodeSandboxSource } from "../../site/diagrams.mjs";

const taxonomy = JSON.parse(execFileSync(
  "python3",
  ["scripts/build_catalog.py", "--print-taxonomy"],
  {
    cwd: new URL("../../", import.meta.url),
    encoding: "utf8",
  },
));

test("Mermaid sandbox documents decode Unicode as UTF-8", () => {
  const source = "♿ axe-core · 🌐 browser → 🤖 agent — 1920×1080";
  const payload = Buffer.from(source, "utf8").toString("base64");

  assert.equal(
    decodeSandboxSource(`data:text/html;charset=UTF-8;base64,${payload}`),
    source,
  );
});

test("search normalization collapses whitespace and ignores case and accents", () => {
  assert.equal(normalizeSearchText("  GPU\n  Café  "), "gpu cafe");
  assert.deepEqual(tokenizeQuery("  GPU\n cloud "), ["gpu", "cloud"]);
});

test("search uses whitespace-token AND matching", () => {
  const record = { search: "GPU autoscaling for Kubernetes clusters" };

  assert.equal(matchesCatalogRecord(record, { q: "gpu kubernetes" }), true);
  assert.equal(matchesCatalogRecord(record, { q: "gpu finance" }), false);
  assert.equal(matchesCatalogRecord(record, { q: "KUBERNETES   auto" }), true);
  assert.equal(matchesCatalogRecord(record, { q: "GPU, Kubernetes" }), true);
});

test("category view matches the exact recipe category", () => {
  const record = { category: "partner-recipes", search: "assistant" };

  assert.equal(
    matchesCatalogRecord(record, { view: "category", category: "partner-recipes" }),
    true,
  );
  assert.equal(
    matchesCatalogRecord(record, { view: "category", category: "nvidia-recipes" }),
    false,
  );
});

test("recipe collections select their matching membership", () => {
  const hackathonRecord = {
    category: "community-recipes",
    collections: ["hackathon", "featured"],
  };
  const regularRecord = {
    category: "community-recipes",
    collections: "featured",
  };

  assert.equal(
    matchesCatalogRecord(hackathonRecord, {
      view: "category",
      category: "hackathon-recipes",
    }),
    true,
  );
  assert.equal(
    matchesCatalogRecord(regularRecord, {
      view: "category",
      category: "hackathon-recipes",
    }),
    false,
  );
  assert.equal(
    matchesCatalogRecord(
      { category: "nvidia-recipes", collections: ["build-a-claw"] },
      { view: "category", category: "build-a-claw-recipes" },
    ),
    true,
  );
  assert.equal(
    matchesCatalogRecord(hackathonRecord, {
      view: "category",
      category: "build-a-claw-recipes",
    }),
    false,
  );
});

test("industry view matches an exact industry slug", () => {
  const record = { industry: "financial-services", search: "risk review" };

  assert.equal(
    matchesCatalogRecord(record, {
      view: "industry",
      industry: "financial-services",
    }),
    true,
  );
  assert.equal(
    matchesCatalogRecord(record, { view: "industry", industry: "financial" }),
    true,
    "an invalid URL-style value canonicalizes to the all-industries default",
  );
  assert.equal(
    matchesCatalogRecord(record, { view: "industry", industry: "cloud-services" }),
    false,
  );
});

test("maintenance defaults to nondeprecated examples and supports exact states", () => {
  const current = { maintenance: "current" };
  const reviewCritical = { maintenance: "review-critical" };
  const deprecated = { maintenance: "deprecated" };

  assert.equal(matchesCatalogRecord(current), true);
  assert.equal(matchesCatalogRecord(reviewCritical), true);
  assert.equal(matchesCatalogRecord(deprecated), false);
  assert.equal(matchesCatalogRecord(deprecated, { maintenance: "all" }), true);
  assert.equal(
    matchesCatalogRecord(reviewCritical, { maintenance: "review-critical" }),
    true,
  );
  assert.equal(
    matchesCatalogRecord(current, { maintenance: "review-due" }),
    false,
  );
});

test("invalid URL values canonicalize to defaults", () => {
  assert.deepEqual(
    parseCatalogURLState("?q=%20GPU%20%20cloud%20&view=map&category=unknown&industry=finance"),
    { ...DEFAULT_CATALOG_STATE, q: "GPU cloud" },
  );
  assert.deepEqual(
    canonicalizeCatalogState({ view: "INDUSTRY", industry: "ENERGY" }),
    {
      ...DEFAULT_CATALOG_STATE,
      view: "industry",
      industry: "energy",
    },
  );
  assert.equal(
    parseCatalogURLState("?view=industry&industry=health-and-life-sciences").industry,
    "health-and-life-sciences",
  );
});

test("URL serialization omits defaults and uses a stable parameter order", () => {
  assert.equal(serializeCatalogURLState(DEFAULT_CATALOG_STATE), "");
  assert.equal(
    serializeCatalogURLState({
      q: "  GPU   cloud ",
      view: "industry",
      category: "partner-recipes",
      industry: "cloud-services",
    }),
    "q=GPU+cloud&view=industry&industry=cloud-services",
  );
});

test("inactive facets are removed from URL state", () => {
  assert.deepEqual(
    parseCatalogURLState("?view=category&industry=energy"),
    DEFAULT_CATALOG_STATE,
  );
  assert.deepEqual(
    parseCatalogURLState("?view=industry&category=partner-recipes&industry=energy"),
    {
      ...DEFAULT_CATALOG_STATE,
      view: "industry",
      industry: "energy",
    },
  );
});

test("client facet identifiers match the README catalog builder", () => {
  assert.deepEqual(CATALOG_CATEGORIES, taxonomy.categories);
  assert.deepEqual(
    CATALOG_COLLECTION_CATEGORIES,
    taxonomy.collection_categories,
  );
  assert.deepEqual(CATALOG_INDUSTRIES, taxonomy.industries);
  assert.deepEqual(CATALOG_MAINTENANCE, taxonomy.maintenance);
});

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
