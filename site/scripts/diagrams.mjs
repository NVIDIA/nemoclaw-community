// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Safe client-side rendering for build-validated Mermaid diagrams.

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const FORBIDDEN_ELEMENTS = new Set([
  "audio",
  "base",
  "embed",
  "foreignobject",
  "iframe",
  "link",
  "meta",
  "object",
  "script",
  "video",
]);
const CSS_URL_PATTERN = /url\(\s*([^)]+?)\s*\)/giu;
const MAX_FRAME_WIDTH = 2400;
const SAFE_IFRAME_CSP = [
  "default-src 'none'",
  "style-src 'unsafe-inline'",
  "img-src 'none'",
  "font-src 'none'",
  "connect-src 'none'",
  "media-src 'none'",
  "object-src 'none'",
  "frame-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join("; ");

function nearestHeadingLabel(element, index) {
  let candidate = element.previousElementSibling;
  while (candidate) {
    if (/^H[2-6]$/u.test(candidate.tagName)) {
      return `${candidate.textContent.trim()} diagram`;
    }
    candidate = candidate.previousElementSibling;
  }
  return `Example architecture diagram ${index + 1}`;
}

function safeHeight(value) {
  const pixels = Number.parseFloat(value);
  if (!Number.isFinite(pixels)) {
    return 320;
  }
  return Math.min(Math.max(pixels, 80), 4000);
}

function frameDimensions(svg, fallbackHeight) {
  const values = (svg.getAttribute("viewBox") ?? "")
    .trim()
    .split(/[\s,]+/u)
    .map(Number);
  if (
    values.length === 4
    && values.every(Number.isFinite)
    && values[2] > 0
    && values[3] > 0
  ) {
    const width = Math.min(values[2], MAX_FRAME_WIDTH);
    const scale = Math.min(1, width / values[2]);
    return {
      width: Math.ceil(width),
      height: safeHeight(Math.ceil(values[3] * scale) + 2),
    };
  }
  return { width: 1024, height: safeHeight(fallbackHeight) };
}

function containsExternalCss(value) {
  if (/(?:@import|javascript:|vbscript:)/iu.test(value)) {
    return true;
  }
  for (const match of value.matchAll(CSS_URL_PATTERN)) {
    const target = match[1].trim().replace(/^(?:"([\s\S]*)"|'([\s\S]*)')$/u, "$1$2");
    if (!target.startsWith("#")) {
      return true;
    }
  }
  return false;
}

function validateSandboxDocument(documentObject) {
  const svg = documentObject.body.querySelector(":scope > svg");
  if (!svg || documentObject.body.children.length !== 1) {
    throw new Error("Mermaid output did not contain exactly one SVG.");
  }

  for (const element of documentObject.querySelectorAll("*")) {
    if (FORBIDDEN_ELEMENTS.has(element.localName.toLocaleLowerCase("en-US"))) {
      throw new Error(`Mermaid output contained forbidden ${element.localName}.`);
    }
    for (const attribute of element.attributes) {
      const name = attribute.name.toLocaleLowerCase("en-US");
      const value = attribute.value.trim();
      if (name.startsWith("on")) {
        throw new Error("Mermaid output contained an event handler.");
      }
      if (name === "href" || name === "xlink:href" || name === "src") {
        if (value && !value.startsWith("#")) {
          throw new Error("Mermaid output contained an external resource.");
        }
      }
      if (name === "style" && containsExternalCss(value)) {
        throw new Error("Mermaid output contained external CSS.");
      }
    }
  }

  for (const style of documentObject.querySelectorAll("style")) {
    if (containsExternalCss(style.textContent)) {
      throw new Error("Mermaid output contained an external stylesheet reference.");
    }
  }
  return svg;
}

export function decodeSandboxSource(source) {
  const prefix = "data:text/html;charset=UTF-8;base64,";
  if (!source.startsWith(prefix)) {
    throw new Error("Mermaid sandbox output used an unexpected source format.");
  }
  const bytes = Uint8Array.from(
    atob(source.slice(prefix.length)),
    (character) => character.charCodeAt(0),
  );
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function accessibleSandboxFrame(markup, label, identifier) {
  const template = document.createElement("template");
  template.innerHTML = markup.trim();
  const generatedFrame = template.content.firstElementChild;
  if (
    template.content.children.length !== 1
    || generatedFrame?.tagName !== "IFRAME"
  ) {
    throw new Error("Mermaid sandbox output did not contain one iframe.");
  }

  const sandboxMarkup = decodeSandboxSource(generatedFrame.getAttribute("src") ?? "");
  const sandboxDocument = new DOMParser().parseFromString(sandboxMarkup, "text/html");
  if (sandboxDocument.querySelector("parsererror")) {
    throw new Error("Mermaid sandbox output could not be parsed.");
  }
  const svg = validateSandboxDocument(sandboxDocument);
  svg.setAttribute("role", "img");
  if (!svg.hasAttribute("aria-labelledby")) {
    const title = sandboxDocument.createElementNS(SVG_NAMESPACE, "title");
    title.id = `${identifier}-title`;
    title.textContent = label;
    svg.prepend(title);
    svg.setAttribute("aria-labelledby", title.id);
  }

  const frame = document.createElement("iframe");
  frame.className = "mermaid-frame";
  frame.title = label;
  frame.tabIndex = -1;
  frame.loading = "lazy";
  frame.setAttribute("sandbox", "");
  const dimensions = frameDimensions(svg, generatedFrame.style.height);
  frame.width = String(dimensions.width);
  frame.height = String(dimensions.height);
  frame.srcdoc = [
    "<!doctype html><html><head><meta charset=\"utf-8\">",
    `<meta http-equiv="Content-Security-Policy" content="${SAFE_IFRAME_CSP}">`,
    "<style>html,body{margin:0;background:#f5f5f5}svg{display:block;max-width:100%;height:auto;margin:auto}</style>",
    "</head><body>",
    sandboxDocument.body.innerHTML,
    "</body></html>",
  ].join("");
  return frame;
}

function diagramFigure(frame, sourceBlock, label) {
  const figure = document.createElement("figure");
  figure.className = "mermaid-diagram";
  figure.dataset.rendered = "true";

  const caption = document.createElement("figcaption");
  caption.className = "mermaid-caption";
  caption.textContent = label;

  const canvas = document.createElement("div");
  canvas.className = "mermaid-canvas";
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "region");
  canvas.setAttribute("aria-label", `${label}; scroll to view the full diagram`);
  canvas.append(frame);

  const source = document.createElement("details");
  source.className = "mermaid-source";
  const summary = document.createElement("summary");
  summary.textContent = "View diagram source";
  source.append(summary, sourceBlock);
  figure.append(caption, canvas, source);
  return figure;
}

function showFallback(sourceBlock) {
  sourceBlock.classList.add("mermaid-source-fallback");
  const message = document.createElement("p");
  message.className = "mermaid-error";
  message.textContent = "This diagram could not be rendered. Its source is shown below.";
  sourceBlock.before(message);
}

async function renderDiagrams() {
  const sources = [...document.querySelectorAll("pre > code.language-mermaid")];
  if (sources.length === 0) {
    return;
  }
  if (!globalThis.mermaid) {
    for (const source of sources) {
      showFallback(source.parentElement);
    }
    return;
  }

  globalThis.mermaid.initialize({
    startOnLoad: false,
    securityLevel: "sandbox",
    suppressErrorRendering: true,
    maxTextSize: 10000,
    maxEdges: 100,
    htmlLabels: false,
    theme: "base",
    fontFamily: "ui-sans-serif, system-ui, sans-serif",
    secure: [
      "secure",
      "securityLevel",
      "startOnLoad",
      "maxTextSize",
      "maxEdges",
      "suppressErrorRendering",
      "htmlLabels",
      "fontFamily",
      "altFontFamily",
      "theme",
      "themeCSS",
      "themeVariables",
      "dompurifyConfig",
      "flowchart",
    ],
    flowchart: {
      htmlLabels: false,
      useMaxWidth: true,
    },
    themeVariables: {
      background: "#f5f5f5",
      primaryColor: "#e8f3d2",
      primaryTextColor: "#111111",
      primaryBorderColor: "#4d692e",
      lineColor: "#4a4a4a",
      secondaryColor: "#e5e5e5",
      tertiaryColor: "#ffffff",
      noteBkgColor: "#fff8d8",
      noteTextColor: "#111111",
    },
  });

  for (const [index, source] of sources.entries()) {
    const sourceBlock = source.parentElement;
    const label = nearestHeadingLabel(sourceBlock, index);
    const identifier = `catalog-mermaid-${index + 1}`;
    try {
      const { svg } = await globalThis.mermaid.render(
        identifier,
        source.textContent,
      );
      const frame = accessibleSandboxFrame(svg, label, identifier);
      const sourceCopy = sourceBlock.cloneNode(true);
      sourceBlock.replaceWith(diagramFigure(frame, sourceCopy, label));
    } catch {
      showFallback(sourceBlock);
    }
  }
}

if (typeof document !== "undefined") {
  if (document.readyState === "complete") {
    void renderDiagrams();
  } else {
    globalThis.addEventListener(
      "load",
      () => void renderDiagrams(),
      { once: true },
    );
  }
}
