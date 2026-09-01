// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

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
  "hackathon-recipes",
  "build-a-claw-recipes",
]);

export const CATALOG_COLLECTION_CATEGORIES = Object.freeze({
  "hackathon-recipes": "hackathon",
  "build-a-claw-recipes": "build-a-claw",
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

function setViewControlState(control, active) {
  if ("checked" in control) {
    control.checked = active;
  }
}

function stateEquals(left, right) {
  return serializeCatalogURLState(left) === serializeCatalogURLState(right);
}

function hashTarget(documentObject, locationObject) {
  if (!locationObject.hash) {
    return null;
  }

  try {
    return documentObject.getElementById(decodeURIComponent(locationObject.hash.slice(1)));
  } catch {
    return null;
  }
}

export function initCategoryInfo(documentObject = globalThis.document) {
  if (!documentObject?.querySelectorAll) {
    return;
  }

  const containers = [...documentObject.querySelectorAll("[data-category-info]")];
  if (containers.length === 0) {
    return;
  }
  const close = (container) => {
    container.dataset.open = "false";
    container.querySelector("button")?.setAttribute("aria-expanded", "false");
  };

  for (const container of containers) {
    const button = container.querySelector("button[aria-controls]");
    if (!button) {
      continue;
    }
    button.addEventListener("click", () => {
      const opening = button.getAttribute("aria-expanded") !== "true";
      for (const other of containers) {
        close(other);
      }
      if (opening) {
        container.dataset.dismissed = "false";
        container.dataset.open = "true";
        button.setAttribute("aria-expanded", "true");
      } else {
        container.dataset.dismissed = "true";
      }
    });
    button.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        close(container);
        container.dataset.dismissed = "true";
      }
    });
    container.addEventListener?.("pointerleave", () => {
      container.dataset.dismissed = "false";
    });
  }

  documentObject.addEventListener?.("click", (event) => {
    if (!event.target?.closest?.("[data-category-info]")) {
      for (const container of containers) {
        close(container);
      }
    }
  });
}

export function initCatalog({
  documentObject = globalThis.document,
  windowObject = globalThis.window,
} = {}) {
  if (!documentObject || !windowObject) {
    return null;
  }

  initCategoryInfo(documentObject);

  const controls = documentObject.getElementById("catalog-controls");
  const viewControls = documentObject.getElementById("catalog-view-controls");
  const search = documentObject.getElementById("catalog-search");
  const categoryView = documentObject.getElementById("catalog-view-category");
  const industryView = documentObject.getElementById("catalog-view-industry");
  const category = documentObject.getElementById("catalog-category");
  const industry = documentObject.getElementById("catalog-industry");
  const maintenance = documentObject.getElementById("catalog-maintenance");
  const reset = documentObject.getElementById("catalog-reset");
  const status = documentObject.getElementById("catalog-status");
  const empty = documentObject.getElementById("catalog-empty");
  const results = documentObject.getElementById("catalog-results");
  const categoryPanel = documentObject.getElementById("browse-category-panel");
  const industryPanel = documentObject.getElementById("browse-industry-panel");

  if (
    !controls
    || !viewControls
    || !search
    || !categoryView
    || !industryView
    || !category
    || !industry
    || !maintenance
    || !reset
    || !status
    || !empty
    || !results
    || !categoryPanel
    || !industryPanel
  ) {
    return null;
  }

  const cards = [...results.querySelectorAll("[data-catalog-entry]")];
  const groups = [...results.querySelectorAll("[data-catalog-category]")];
  const filterWrappers = [...controls.querySelectorAll("[data-filter-for]")];
  let state = parseCatalogURLState(windowObject.location.search);

  function syncControls() {
    search.value = state.q;
    category.value = state.category;
    industry.value = state.industry;
    maintenance.value = state.maintenance;
    setViewControlState(categoryView, state.view === "category");
    setViewControlState(industryView, state.view === "industry");
    categoryPanel.hidden = state.view !== "category";
    industryPanel.hidden = state.view !== "industry";

    for (const wrapper of filterWrappers) {
      const active = wrapper.dataset.filterFor === state.view;
      wrapper.hidden = !active;
      for (const input of wrapper.querySelectorAll("input, select, button")) {
        input.disabled = !active;
      }
    }

    reset.disabled = stateEquals(state, DEFAULT_CATALOG_STATE);
  }

  function reconcileHashTarget() {
    const target = hashTarget(documentObject, windowObject.location);
    if (!target) {
      return;
    }

    const targetCard = target.matches?.("[data-catalog-entry]")
      ? target
      : target.closest?.("[data-catalog-entry]");
    const targetGroup = target.matches?.("[data-catalog-category]")
      ? target
      : target.closest?.("[data-catalog-category]");
    let next = { ...state };
    if (targetGroup) {
      const groupCategory = targetGroup.dataset.catalogCategory;
      if (
        next.q
        || next.view !== "category"
        || (next.category !== "all" && next.category !== groupCategory)
      ) {
        next = {
          ...next,
          q: "",
          view: "category",
          category: groupCategory,
        };
      }
    } else if (targetCard) {
      next.q = "";
      if (
        next.view === "category"
        && next.category !== "all"
        && next.category !== targetCard.dataset.category
      ) {
        next.category = "all";
      }
      if (
        next.view === "industry"
        && next.industry !== "all"
        && next.industry !== targetCard.dataset.industry
      ) {
        next.industry = "all";
      }
      const targetMaintenance = targetCard.dataset.maintenance;
      if (
        next.maintenance !== "all"
        && !(next.maintenance === "maintained" && targetMaintenance !== "deprecated")
        && next.maintenance !== targetMaintenance
      ) {
        next.maintenance = "all";
      }
    }

    next = canonicalizeCatalogState(next);
    if (!stateEquals(state, next)) {
      state = next;
      return true;
    }
    return false;
  }

  function render() {
    results.dataset.view = state.view;
    const visibleCards = new Set();

    for (const card of cards) {
      const visible = matchesCatalogRecord(card, state);
      card.hidden = !visible;
      if (visible) {
        visibleCards.add(card);
      }
    }

    for (const group of groups) {
      if (state.view === "industry") {
        group.setAttribute("role", "presentation");
        group.removeAttribute("aria-labelledby");
      } else {
        group.removeAttribute("role");
        group.setAttribute(
          "aria-labelledby",
          `${group.dataset.catalogCategory}-title`,
        );
      }
      const groupHasVisibleCard = [...group.querySelectorAll("[data-catalog-entry]")]
        .some((card) => visibleCards.has(card));
      group.hidden = !groupHasVisibleCard;
    }

    const count = visibleCards.size;
    status.textContent = `${count} ${count === 1 ? "example" : "examples"} shown`;
    empty.hidden = count !== 0;
  }

  function historyURL(preserveHash) {
    const params = serializeCatalogURLState(state);
    const hash = preserveHash ? windowObject.location.hash : "";
    return `${windowObject.location.pathname}${params ? `?${params}` : ""}${hash}`;
  }

  function updateHistory(mode, preserveHash = false) {
    const method = mode === "push" ? "pushState" : "replaceState";
    windowObject.history?.[method]?.({}, "", historyURL(preserveHash));
  }

  function commit(nextState, historyMode) {
    const next = canonicalizeCatalogState(nextState);
    const changed = !stateEquals(state, next);
    state = next;
    syncControls();
    render();
    if (changed || historyMode === "replace") {
      updateHistory(historyMode);
    }
  }

  search.addEventListener("input", () => {
    commit({ ...state, q: search.value }, "replace");
  });

  categoryView.addEventListener("click", () => {
    commit({ ...state, view: "category" }, "push");
  });

  industryView.addEventListener("click", () => {
    commit({ ...state, view: "industry" }, "push");
  });

  category.addEventListener("change", () => {
    commit({ ...state, category: category.value }, "push");
  });

  industry.addEventListener("change", () => {
    commit({ ...state, industry: industry.value }, "push");
  });

  maintenance.addEventListener("change", () => {
    commit({ ...state, maintenance: maintenance.value }, "push");
  });

  reset.addEventListener("click", () => {
    commit(DEFAULT_CATALOG_STATE, "push");
    search.focus();
  });

  windowObject.addEventListener("popstate", () => {
    state = parseCatalogURLState(windowObject.location.search);
    reconcileHashTarget();
    syncControls();
    render();
  });

  windowObject.addEventListener("hashchange", () => {
    reconcileHashTarget();
    syncControls();
    render();
    updateHistory("replace", true);
  });

  reconcileHashTarget();
  syncControls();
  render();
  updateHistory("replace", true);
  controls.hidden = false;
  controls.dataset.catalogReady = "true";
  viewControls.hidden = false;

  return {
    getState: () => ({ ...state }),
    render,
  };
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => initCatalog(), { once: true });
  } else {
    initCatalog();
  }
}
