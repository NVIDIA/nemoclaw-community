// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Progressive enhancement for tutorial paging, navigation, and code copying.

const HEADING_SELECTOR = "h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]";
const PART_HEADING_SELECTOR = "h2[id]";

function fragmentId(link) {
  try {
    return decodeURIComponent((link.getAttribute("href") ?? "").split("#").at(-1));
  } catch {
    return "";
  }
}

function currentFragment(windowObject) {
  try {
    return decodeURIComponent(windowObject.location.hash.slice(1));
  } catch {
    return "";
  }
}

function partLabel(title, fallback) {
  return title.replace(/^Part\s+\d+\s*(?:[\u2013\u2014:-]\s*)?/i, "").trim()
    || fallback;
}

function codeLanguage(block, surface) {
  const candidates = [block.querySelector("code"), block, surface];
  for (const candidate of candidates) {
    const className = [...(candidate?.classList ?? [])]
      .find((name) => name.startsWith("language-"));
    if (className) {
      return className.slice("language-".length).toLowerCase();
    }
  }
  return "";
}

function displayLanguage(language) {
  const labels = {
    bash: "Bash",
    json: "JSON",
    mermaid: "Mermaid",
    plaintext: "Text",
    sh: "Shell",
    shell: "Shell",
    text: "Text",
    yaml: "YAML",
    yml: "YAML",
  };
  return labels[language] ?? (language
    ? language.charAt(0).toUpperCase() + language.slice(1)
    : "Code");
}

export function addCopyButtons(article) {
  const documentObject = article.ownerDocument;
  const windowObject = documentObject.defaultView ?? globalThis;
  let copyIndex = 0;
  return [...article.querySelectorAll("pre")].flatMap((block) => {
    const code = block.querySelector("code");
    if (code?.classList.contains("language-mermaid")) {
      return [];
    }

    const parent = block.parentElement;
    const surface = parent?.classList.contains("codehilite")
      ? parent
      : block;
    if (surface.closest?.(".tutorial-code-block")) {
      return [];
    }

    const source = code?.textContent ?? block.textContent;
    const language = displayLanguage(codeLanguage(block, surface));
    const wrapper = documentObject.createElement("div");
    wrapper.className = "tutorial-code-block";
    surface.before(wrapper);

    const toolbar = documentObject.createElement("div");
    toolbar.className = "tutorial-code-toolbar";
    const label = documentObject.createElement("span");
    label.className = "tutorial-code-language";
    label.textContent = language;

    const button = documentObject.createElement("button");
    button.className = "tutorial-copy-button";
    button.type = "button";
    button.textContent = "Copy";
    copyIndex += 1;
    button.setAttribute("aria-label", `Copy ${language} block ${copyIndex}`);
    button.addEventListener("click", async () => {
      try {
        await windowObject.navigator.clipboard.writeText(source);
        button.dataset.state = "copied";
        button.textContent = "Copied";
      } catch {
        button.dataset.state = "error";
        button.textContent = "Unavailable";
      }
      windowObject.setTimeout(() => {
        delete button.dataset.state;
        button.textContent = "Copy";
      }, 2000);
    });
    toolbar.append(label, button);
    wrapper.append(toolbar, surface);
    return [button];
  });
}

export function initActiveToc(article) {
  const documentObject = article.ownerDocument;
  const windowObject = documentObject.defaultView ?? globalThis;
  const links = [...documentObject.querySelectorAll(".detail-toc a[href*='#']")];
  const targetIds = new Set(links.map(fragmentId));
  const headings = [...article.querySelectorAll(HEADING_SELECTOR)]
    .filter((heading) => targetIds.has(heading.id));
  if (headings.length === 0) {
    return null;
  }

  let activeId = "";
  const markActive = (identifier) => {
    if (!identifier || identifier === activeId) {
      return;
    }
    activeId = identifier;
    for (const link of links) {
      const current = fragmentId(link) === identifier;
      link.classList.toggle("is-active", current);
      link.toggleAttribute("aria-current", current);
      if (current) {
        link.setAttribute("aria-current", "location");
      }
    }
  };

  let scheduled = false;
  const update = () => {
    scheduled = false;
    const visibleHeadings = headings.filter(
      (heading) => !heading.closest(".tutorial-step[hidden]"),
    );
    if (visibleHeadings.length === 0) {
      return;
    }
    const offset = Math.min(160, Math.max(80, windowObject.innerHeight * 0.18));
    let current = visibleHeadings[0];
    for (const heading of visibleHeadings) {
      if (heading.getBoundingClientRect().top > offset) {
        break;
      }
      current = heading;
    }
    markActive(current.id);
  };
  const scheduleUpdate = () => {
    if (!scheduled) {
      scheduled = true;
      windowObject.requestAnimationFrame(update);
    }
  };

  for (const link of links) {
    link.addEventListener("click", () => {
      markActive(fragmentId(link));
      const mobileToc = link.closest(".detail-toc-mobile");
      if (mobileToc) {
        mobileToc.open = false;
      }
    });
  }
  windowObject.addEventListener("scroll", scheduleUpdate, { passive: true });
  windowObject.addEventListener("resize", scheduleUpdate);
  windowObject.addEventListener("hashchange", scheduleUpdate);
  update();
  return { markActive, update };
}

function groupTutorialSteps(article) {
  const documentObject = article.ownerDocument;
  const nodes = [...article.childNodes];
  const boundaries = nodes
    .map((node, index) => node.nodeType === 1 && node.matches(PART_HEADING_SELECTOR)
      ? { heading: node, index }
      : null)
    .filter(Boolean);
  if (boundaries.length === 0) {
    return [];
  }

  return boundaries.map(({ heading, index }, stepIndex) => {
    const section = documentObject.createElement("section");
    section.className = "tutorial-step";
    section.dataset.step = String(stepIndex + 1);
    section.setAttribute("aria-labelledby", heading.id);
    heading.tabIndex = -1;

    const start = stepIndex === 0 ? 0 : index;
    const end = boundaries[stepIndex + 1]?.index ?? nodes.length;
    article.insertBefore(section, nodes[start]);
    for (const node of nodes.slice(start, end)) {
      section.append(node);
    }
    return { heading, section };
  });
}

function progressNavigation(steps) {
  const documentObject = steps[0].section.ownerDocument;
  const navigation = documentObject.createElement("nav");
  navigation.className = "tutorial-progress";
  navigation.setAttribute("aria-label", "Tutorial progress");

  const summary = documentObject.createElement("div");
  summary.className = "tutorial-progress-summary";
  const counter = documentObject.createElement("p");
  counter.className = "tutorial-progress-counter";
  counter.id = "tutorial-progress-counter";
  counter.setAttribute("aria-live", "polite");
  const title = documentObject.createElement("p");
  title.className = "tutorial-progress-title";
  summary.append(counter, title);

  const meter = documentObject.createElement("progress");
  meter.className = "tutorial-progress-meter";
  meter.max = steps.length;
  meter.setAttribute("aria-label", "Tutorial completion");

  const list = documentObject.createElement("ol");
  list.className = "tutorial-progress-steps";
  const links = steps.map(({ heading }, index) => {
    const item = documentObject.createElement("li");
    const link = documentObject.createElement("a");
    const label = partLabel(heading.textContent.trim(), `Part ${index + 1}`);
    link.href = `#${heading.id}`;
    link.setAttribute(
      "aria-label",
      `Part ${index + 1} of ${steps.length}: ${label}`,
    );
    const number = documentObject.createElement("span");
    number.className = "tutorial-progress-number";
    number.setAttribute("aria-hidden", "true");
    number.textContent = String(index + 1);
    const linkLabel = documentObject.createElement("span");
    linkLabel.className = "tutorial-progress-link-label";
    linkLabel.textContent = label;
    link.append(number, linkLabel);
    item.append(link);
    list.append(item);
    return { item, link, label };
  });
  navigation.append(summary, meter, list);
  return { counter, links, list, meter, navigation, title };
}

function paginationNavigation(documentObject) {
  const navigation = documentObject.createElement("nav");
  navigation.className = "tutorial-pagination";
  navigation.setAttribute("aria-label", "Tutorial pages");

  const createLink = (className, label) => {
    const link = documentObject.createElement("a");
    link.className = `tutorial-page-link ${className}`;
    link.textContent = label;
    return { label, link };
  };

  const previous = createLink("tutorial-page-previous", "Previous");
  const next = createLink("tutorial-page-next", "Next");
  navigation.append(previous.link, next.link);
  return { navigation, next, previous };
}

export function initTutorialPaging(article) {
  const documentObject = article.ownerDocument;
  const windowObject = documentObject.defaultView ?? globalThis;
  const steps = groupTutorialSteps(article);
  if (steps.length === 0) {
    return null;
  }

  const progress = progressNavigation(steps);
  const pagination = paginationNavigation(documentObject);
  article.prepend(progress.navigation);
  article.append(pagination.navigation);

  const stepByTarget = new Map();
  for (const [index, { section }] of steps.entries()) {
    for (const target of section.querySelectorAll("[id]")) {
      stepByTarget.set(target.id, index);
    }
  }

  let activeIndex = -1;
  const updateDestination = (control, destination) => {
    control.link.hidden = !destination;
    if (!destination) {
      control.link.removeAttribute("href");
      control.link.removeAttribute("aria-label");
      return;
    }
    control.link.href = `#${destination.heading.id}`;
    const destinationLabel = partLabel(
      destination.heading.textContent.trim(),
      destination.heading.textContent.trim(),
    );
    control.link.setAttribute(
      "aria-label",
      `${control.label}: ${destinationLabel}`,
    );
  };

  const showStep = (index) => {
    if (index < 0 || index >= steps.length) {
      return false;
    }
    activeIndex = index;
    for (const [stepIndex, { section }] of steps.entries()) {
      section.hidden = stepIndex !== index;
    }
    for (const [stepIndex, { item, link }] of progress.links.entries()) {
      const current = stepIndex === index;
      item.classList.toggle("is-complete", stepIndex < index);
      item.classList.toggle("is-current", current);
      link.toggleAttribute("aria-current", current);
      if (current) {
        link.setAttribute("aria-current", "step");
      }
    }
    const currentStep = steps[index];
    const currentTitle = currentStep.heading.textContent.trim();
    progress.counter.textContent = `Part ${index + 1} of ${steps.length}`;
    progress.title.textContent = partLabel(currentTitle, currentTitle);
    progress.meter.value = index + 1;
    progress.meter.textContent = `${index + 1} of ${steps.length}`;
    const activeLink = progress.links[index].link;
    if (progress.list.scrollWidth > progress.list.clientWidth) {
      progress.list.scrollLeft = Math.max(
        0,
        activeLink.offsetLeft - (progress.list.clientWidth - activeLink.offsetWidth) / 2,
      );
    }
    updateDestination(pagination.previous, steps[index - 1]);
    updateDestination(pagination.next, steps[index + 1]);
    return true;
  };

  const revealFragment = (
    identifier,
    { fallbackIndex, focus = false, scroll = false } = {},
  ) => {
    const targetIndex = stepByTarget.get(identifier);
    const index = targetIndex ?? fallbackIndex;
    if (index === undefined) {
      return;
    }
    showStep(index);
    if (!focus && !scroll) {
      return;
    }
    const target = targetIndex === undefined
      ? steps[0].heading
      : documentObject.getElementById(identifier);
    const scrollTarget = targetIndex === undefined
      || target === steps[targetIndex].heading
      ? progress.navigation
      : target;
    windowObject.requestAnimationFrame(() => {
      if (scroll) {
        scrollTarget?.scrollIntoView({ block: "start" });
      }
      if (focus && target) {
        target.tabIndex = -1;
        target.focus({ preventScroll: true });
      }
    });
  };

  const showFragment = (options = {}) => revealFragment(
    currentFragment(windowObject),
    { ...options, fallbackIndex: 0 },
  );

  for (const link of article.querySelectorAll('a[href^="#"]')) {
    link.addEventListener(
      "click",
      () => revealFragment(fragmentId(link), { focus: true, scroll: true }),
    );
  }
  windowObject.addEventListener(
    "hashchange",
    () => showFragment({ focus: true, scroll: true }),
  );
  windowObject.addEventListener("pageshow", () => {
    if (currentFragment(windowObject)) {
      showFragment({ scroll: true });
    }
  });

  showFragment({ scroll: Boolean(currentFragment(windowObject)) });
  article.closest(".tutorial-page")?.classList.add("tutorial-is-paged");
  return { activeIndex: () => activeIndex, showStep, steps };
}

export function initTutorial(documentObject = globalThis.document) {
  const article = documentObject?.querySelector?.(".tutorial-content");
  if (!article || article.dataset.tutorialEnhanced === "true") {
    return null;
  }
  article.dataset.tutorialEnhanced = "true";
  const copyButtons = addCopyButtons(article);
  const paging = initTutorialPaging(article);
  return {
    copyButtons,
    paging,
    activeToc: paging ? null : initActiveToc(article),
  };
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => initTutorial(), { once: true });
  } else {
    initTutorial();
  }
}
