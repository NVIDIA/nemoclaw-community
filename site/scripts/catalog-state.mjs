// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Pure catalog search, filter, and URL-state helpers with no DOM dependency.

export const DEFAULT_CATALOG_STATE = Object.freeze({
  q: "",
  view: "category",
  category: "all",
  industry: "all",
  maintenance: "maintained",
});

export const CATALOG_VIEWS = Object.freeze(["category", "industry"]);

export const CATALOG_CATEGORIES = Object.freeze([
  "all",
  "nvidia-recipes",
  "partner-recipes",
  "community-recipes",
  "nvidia-field-demos",
  "developer-tools",
  "build-a-claw",
  "hackathon-recipes",
]);

export const CATALOG_COLLECTION_CATEGORIES = Object.freeze({
  "build-a-claw": "build-a-claw",
  "hackathon-recipes": "hackathon",
});

export const CATALOG_INDUSTRIES = Object.freeze([
  "all",
  "academia-education",
  "aec",
  "aerospace",
  "agriculture",
  "automotive-transportation",
  "cloud-services",
  "consumer-internet",
  "energy",
  "financial-services",
  "gaming",
  "hardware-semiconductor",
  "health-and-life-sciences",
  "hpc-scientific-computing",
  "manufacturing",
  "media-entertainment",
  "public-sector",
  "restaurant-quick-service",
  "retail-consumer-packaged-goods",
  "smart-cities-spaces",
  "telecommunications",
  "other",
]);

export const CATALOG_MAINTENANCE = Object.freeze([
  "maintained",
  "all",
  "current",
  "review-soon",
  "review-due",
  "review-overdue",
  "review-critical",
  "deprecated",
]);

const viewValues = new Set(CATALOG_VIEWS);
const categoryValues = new Set(CATALOG_CATEGORIES);
const industryValues = new Set(CATALOG_INDUSTRIES);
const maintenanceValues = new Set(CATALOG_MAINTENANCE);

export function normalizeWhitespace(value) {
  return String(value ?? "").trim().replace(/\s+/gu, " ");
}

export function normalizeSearchText(value) {
  const folded = String(value ?? "")
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .toLocaleLowerCase("en-US")
    .replace(/[^\p{L}\p{N}]+/gu, " ");
  return normalizeWhitespace(folded);
}

export function tokenizeQuery(value) {
  const normalized = normalizeSearchText(value);
  return normalized ? normalized.split(" ") : [];
}

function allowedOrDefault(value, allowed, fallback) {
  const normalized = normalizeWhitespace(value).toLocaleLowerCase("en-US");
  return allowed.has(normalized) ? normalized : fallback;
}

export function canonicalizeCatalogState(state = {}) {
  const view = allowedOrDefault(
    state.view,
    viewValues,
    DEFAULT_CATALOG_STATE.view,
  );
  return {
    q: normalizeWhitespace(state.q),
    view,
    category: view === "category"
      ? allowedOrDefault(
        state.category,
        categoryValues,
        DEFAULT_CATALOG_STATE.category,
      )
      : DEFAULT_CATALOG_STATE.category,
    industry: view === "industry"
      ? allowedOrDefault(
        state.industry,
        industryValues,
        DEFAULT_CATALOG_STATE.industry,
      )
      : DEFAULT_CATALOG_STATE.industry,
    maintenance: allowedOrDefault(
      state.maintenance,
      maintenanceValues,
      DEFAULT_CATALOG_STATE.maintenance,
    ),
  };
}

function asSearchParams(source) {
  if (source instanceof URLSearchParams) {
    return source;
  }

  if (source instanceof URL) {
    return source.searchParams;
  }

  const text = String(source ?? "");
  const query = text.includes("?") ? text.slice(text.indexOf("?") + 1) : text;
  return new URLSearchParams(query.split("#", 1)[0]);
}

export function parseCatalogURLState(source = "") {
  const params = asSearchParams(source);
  return canonicalizeCatalogState({
    q: params.get("q") ?? "",
    view: params.get("view") ?? DEFAULT_CATALOG_STATE.view,
    category: params.get("category") ?? DEFAULT_CATALOG_STATE.category,
    industry: params.get("industry") ?? DEFAULT_CATALOG_STATE.industry,
    maintenance: params.get("maintenance") ?? DEFAULT_CATALOG_STATE.maintenance,
  });
}

export function serializeCatalogURLState(state = {}) {
  const canonical = canonicalizeCatalogState(state);
  const params = new URLSearchParams();

  if (canonical.q) {
    params.set("q", canonical.q);
  }
  if (canonical.view !== DEFAULT_CATALOG_STATE.view) {
    params.set("view", canonical.view);
  }
  if (canonical.category !== DEFAULT_CATALOG_STATE.category) {
    params.set("category", canonical.category);
  }
  if (canonical.industry !== DEFAULT_CATALOG_STATE.industry) {
    params.set("industry", canonical.industry);
  }
  if (canonical.maintenance !== DEFAULT_CATALOG_STATE.maintenance) {
    params.set("maintenance", canonical.maintenance);
  }

  return params.toString();
}

function splitCollections(value) {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeWhitespace(item).toLocaleLowerCase("en-US"))
      .filter(Boolean);
  }

  return normalizeWhitespace(value).toLocaleLowerCase("en-US")
    .split(/[\s,]+/u)
    .filter(Boolean);
}

function recordValue(record, key) {
  return record?.[key] ?? record?.dataset?.[key] ?? "";
}

export function matchesCatalogRecord(record, state = {}) {
  const canonical = canonicalizeCatalogState(state);
  const searchText = normalizeSearchText(
    recordValue(record, "search") || record?.textContent || "",
  );

  if (!tokenizeQuery(canonical.q).every((token) => searchText.includes(token))) {
    return false;
  }

  if (canonical.view === "category" && canonical.category !== "all") {
    const collection = CATALOG_COLLECTION_CATEGORIES[canonical.category];
    if (collection) {
      const collections = splitCollections(recordValue(record, "collections"));
      if (!collections.includes(collection)) {
        return false;
      }
    } else if (recordValue(record, "category") !== canonical.category) {
      return false;
    }
  }

  if (
    canonical.view === "industry"
    && canonical.industry !== "all"
    && recordValue(record, "industry") !== canonical.industry
  ) {
    return false;
  }

  const maintenance = recordValue(record, "maintenance");
  if (
    canonical.maintenance !== "all"
    && !(canonical.maintenance === "maintained" && maintenance !== "deprecated")
    && maintenance !== canonical.maintenance
  ) {
    return false;
  }

  return true;
}

export function stateEquals(left, right) {
  return serializeCatalogURLState(left) === serializeCatalogURLState(right);
}
