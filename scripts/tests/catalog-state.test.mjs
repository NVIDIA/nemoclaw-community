// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import test from "node:test";

import {
  CATALOG_CATEGORIES,
  CATALOG_COLLECTION_CATEGORIES,
  CATALOG_INDUSTRIES,
  CATALOG_MAINTENANCE,
  DEFAULT_CATALOG_STATE,
  canonicalizeCatalogState,
  matchesCatalogRecord,
  normalizeSearchText,
  parseCatalogURLState,
  serializeCatalogURLState,
  tokenizeQuery,
} from "../../site/scripts/catalog-state.mjs";

const taxonomy = JSON.parse(execFileSync(
  "python3",
  ["scripts/build_catalog.py", "--print-taxonomy"],
  {
    cwd: new URL("../../", import.meta.url),
    encoding: "utf8",
  },
));

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

test("collections select their matching membership", () => {
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
      { view: "category", category: "build-a-claw" },
    ),
    true,
  );
  assert.equal(
    matchesCatalogRecord(hackathonRecord, {
      view: "category",
      category: "build-a-claw",
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
