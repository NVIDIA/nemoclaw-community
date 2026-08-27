// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  CATALOG_INDUSTRIES,
  DEFAULT_CATALOG_STATE,
  canonicalizeCatalogState,
  initCatalog,
  matchesCatalogRecord,
  normalizeSearchText,
  parseCatalogURLState,
  serializeCatalogURLState,
  tokenizeQuery,
} from "../../site/catalog.mjs";
import { decodeSandboxSource } from "../../site/diagrams.mjs";

const catalogSchema = JSON.parse(
  readFileSync(new URL("../../examples/catalog.schema.json", import.meta.url), "utf8"),
);

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

test("hackathon recipes are selected through collections", () => {
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

test("client industry identifiers match the catalog schema", () => {
  const labels = catalogSchema.$defs.example.properties.industry.enum;
  const identifiers = labels.map((label) => normalizeSearchText(label)
    .replace(/[^a-z0-9]+/gu, "-")
    .replace(/^-|-$/gu, ""));

  assert.deepEqual(CATALOG_INDUSTRIES, ["all", ...identifiers]);
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
      search: "payment operations",
    },
  });
  const partnerCard = fakeControl({
    dataset: {
      category: "partner-recipes",
      industry: "financial-services",
      collections: "",
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
