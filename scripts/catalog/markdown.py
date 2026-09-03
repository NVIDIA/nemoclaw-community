# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compile and sanitize README Markdown for catalog detail pages."""

from __future__ import annotations

import base64
import html
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .model import CatalogEntry, CatalogError
from .sources import is_regular_repo_file

try:
    import markdown
except ModuleNotFoundError:  # Report a targeted build error when dependencies are absent.
    markdown = None

try:
    import pygments
except ModuleNotFoundError:  # Tutorial code highlighting is an optional build path.
    pygments = None


MERMAID_VERSION = "11.17.2"
MERMAID_SHA256 = (
    "7a644017d37f93c8359790884e6b67fb1f747c78eb20475952404bd87190a3f8"
)
MERMAID_SRI = "sha256-" + base64.b64encode(
    bytes.fromhex(MERMAID_SHA256)
).decode("ascii")
MERMAID_CACHE_PATH = Path(".cache/catalog/mermaid.tiny.js")
MERMAID_FENCE_OPEN_PATTERN = re.compile(r"^```mermaid[ \t]*\r?$", re.MULTILINE)
MERMAID_FENCE_PATTERN = re.compile(
    r"^```mermaid[ \t]*\r?\n(?P<source>.*?)^```[ \t]*\r?$",
    re.MULTILINE | re.DOTALL,
)
MERMAID_DIAGRAM_TYPES = {
    "flowchart",
    "graph",
    "sequenceDiagram",
    "stateDiagram-v2",
}
MERMAID_FORBIDDEN_SOURCE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"%%\{"), "configuration directives"),
    (
        re.compile(r"(?:^|;)\s*click\b", re.IGNORECASE | re.MULTILINE),
        "click directives",
    ),
    (
        re.compile(
            r"@\{[^}\r\n]*\b(?:icon|img)\s*:",
            re.IGNORECASE,
        ),
        "image or icon shapes",
    ),
    (
        re.compile(
            r"<\s*/?\s*(?:"
            r"a|audio|base|embed|foreignObject|form|iframe|image|img|link|meta|"
            r"object|script|style|video)\b",
            re.IGNORECASE,
        ),
        "active HTML elements",
    ),
    (re.compile(r"@import\b", re.IGNORECASE), "CSS imports"),
    (re.compile(r"url\s*\(", re.IGNORECASE), "CSS URL references"),
)
MAX_MERMAID_DIAGRAMS_PER_README = 10
MAX_MERMAID_SOURCE_SIZE = 10_000
DETAIL_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self'; font-src 'self'; connect-src 'none'; "
    "object-src 'none'; frame-src 'self'; worker-src 'none'; base-uri 'none'; "
    "form-action 'none'"
)
TUTORIAL_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self'; font-src 'self'; connect-src 'none'; "
    "object-src 'none'; frame-src https://www.linkedin.com https://www.youtube.com; "
    "worker-src 'none'; base-uri 'none'; form-action 'none'"
)
TUTORIAL_IFRAME_PATHS = {
    "www.linkedin.com": "/embed/",
    "www.youtube.com": "/embed/",
}


def github_heading_slug(value: str, separator: str) -> str:
    """Approximate GitHub's stable heading IDs for README fragment links."""

    normalized = html.unescape(value).strip().casefold()
    normalized = re.sub(r"[^\w\-\ufe0f ]", "", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", separator, normalized)


def extract_mermaid_sources(content: str, readme_path: str) -> tuple[str, ...]:
    """Return Mermaid fences after enforcing the catalog's safe diagram subset."""

    opening_count = len(MERMAID_FENCE_OPEN_PATTERN.findall(content))
    matches = list(MERMAID_FENCE_PATTERN.finditer(content))
    if opening_count != len(matches):
        raise CatalogError(
            f"Mermaid fence is not closed correctly in {readme_path}."
        )
    if len(matches) > MAX_MERMAID_DIAGRAMS_PER_README:
        raise CatalogError(
            f"{readme_path} has more than {MAX_MERMAID_DIAGRAMS_PER_README} "
            "Mermaid diagrams."
        )

    sources: list[str] = []
    for index, match in enumerate(matches, start=1):
        source = match.group("source").strip()
        label = f"Mermaid diagram {index} in {readme_path}"
        if not source:
            raise CatalogError(f"{label} is empty.")
        if len(source) > MAX_MERMAID_SOURCE_SIZE:
            raise CatalogError(
                f"{label} exceeds the {MAX_MERMAID_SOURCE_SIZE}-character limit."
            )

        first_line = source.splitlines()[0].strip()
        diagram_type = first_line.split(maxsplit=1)[0]
        if diagram_type not in MERMAID_DIAGRAM_TYPES:
            raise CatalogError(
                f"{label} uses unsupported type {diagram_type!r}. Supported types: "
                + ", ".join(sorted(MERMAID_DIAGRAM_TYPES))
                + "."
            )
        if diagram_type in {"flowchart", "graph"} and re.fullmatch(
            r"(?:flowchart|graph)\s+(?:BT|LR|RL|TB|TD)", first_line
        ) is None:
            raise CatalogError(
                f"{label} must declare one supported flow direction on its first line."
            )
        if diagram_type in {"sequenceDiagram", "stateDiagram-v2"} and (
            first_line != diagram_type
        ):
            raise CatalogError(
                f"{label} has unexpected content after its diagram type."
            )
        for pattern, description in MERMAID_FORBIDDEN_SOURCE_PATTERNS:
            if pattern.search(source):
                raise CatalogError(f"{label} contains forbidden {description}.")
        sources.append(source)
    return tuple(sources)


def prepare_tutorial_markdown(source: str, source_path: str) -> tuple[str, str]:
    """Remove tutorial chrome and demote headings without changing fenced code."""

    title: str | None = None
    output: list[str] = []
    fence: tuple[str, int] | None = None
    for line in source.splitlines(keepends=True):
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        content = line[: -len(ending)] if ending else line
        if fence:
            if re.fullmatch(
                rf" {{0,3}}{re.escape(fence[0])}{{{fence[1]},}}[ \t]*", content
            ):
                fence = None
            output.append(line)
            continue
        opening = re.match(r"^ {0,3}(?P<fence>`{3,}|~{3,})", content)
        if opening:
            marker = opening.group("fence")
            fence = (marker[0], len(marker))
            output.append(line)
            continue
        if re.fullmatch(r"[ \t]*\[TOC\][ \t]*", content, re.IGNORECASE):
            continue
        heading = re.fullmatch(
            r"(?P<indent> {0,3})(?P<marks>#{1,6})[ \t]+(?P<text>.*)", content
        )
        if not heading:
            output.append(line)
            continue
        marks = heading.group("marks")
        if title is None and len(marks) == 1:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group("text")).strip()
            if not title:
                raise CatalogError(f"Tutorial title must not be empty in {source_path}.")
            continue
        marks = marks + "#" if len(marks) < 6 else marks
        output.append(
            f"{heading.group('indent')}{marks} {heading.group('text')}{ending}"
        )
    if title is None:
        raise CatalogError(
            f"Tutorial Markdown requires one level-one title in {source_path}."
        )
    return title, "".join(output)


def tutorial_fence_languages(source: str, source_path: str) -> tuple[str, ...]:
    """Return one safe display language for each tutorial fence in source order."""

    languages: list[str] = []
    fence: tuple[str, int, str] | None = None
    for line_number, line in enumerate(source.splitlines(), start=1):
        if fence:
            if re.fullmatch(
                rf" {{0,3}}{re.escape(fence[0])}{{{fence[1]},}}[ \t]*", line
            ):
                languages.append(fence[2])
                fence = None
            continue
        opening = re.fullmatch(
            r" {0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)", line
        )
        if not opening:
            continue
        marker = opening.group("fence")
        info = opening.group("info").strip()
        if not info:
            raise CatalogError(
                "Tutorial code fence requires an explicit language in "
                f"{source_path}:{line_number}. Use a language such as `bash`, "
                "`yaml`, or `text`."
            )
        if re.fullmatch(r"[A-Za-z0-9_+.-]+", info) is None:
            raise CatalogError(
                f"Tutorial code fence has invalid language {info!r} in "
                f"{source_path}:{line_number}."
            )
        language = info.casefold()
        fence = (marker[0], len(marker), language)
    if fence:
        raise CatalogError(f"Tutorial code fence is not closed in {source_path}.")
    return tuple(languages)


def annotate_tutorial_code_languages(
    rendered: str,
    languages: tuple[str, ...],
    source_path: str,
) -> str:
    """Restore fence languages after build-time syntax highlighting."""

    marker = '<div class="codehilite"><pre><span></span><code>'
    if rendered.count(marker) != len(languages):
        raise CatalogError(
            f"Tutorial code fence/render count mismatch for {source_path}."
        )
    for language in languages:
        rendered = rendered.replace(
            marker,
            '<div class="codehilite"><pre><span></span>'
            f'<code class="language-{language}">',
            1,
        )
    return rendered


class ReadmeHTMLSanitizer(HTMLParser):
    """Allow the Markdown subset used by example READMEs and rewrite local URLs."""

    ALLOWED_TAGS = {
        "a",
        "abbr",
        "blockquote",
        "br",
        "code",
        "dd",
        "div",
        "dl",
        "dt",
        "em",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "iframe",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
    VOID_TAGS = {"br", "hr", "img"}

    def __init__(
        self,
        root: Path,
        entry: CatalogEntry,
        catalog_by_readme: dict[str, CatalogEntry],
        copied_assets: set[str],
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.root = root
        self.entry = entry
        self.tutorial_mode = entry.is_tutorial
        self.catalog_by_readme = catalog_by_readme
        self.copied_assets = copied_assets
        self.output: list[str] = []
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.fragments: set[str] = set()
        self._open_tags: list[str] = []
        self._source_path = entry.content_path
        self._source_dir = PurePosixPath(self._source_path).parent.as_posix()
        self._detail_dir = PurePosixPath(entry.detail_path).parent.as_posix()

    def _repo_target(self, raw_path: str) -> str | None:
        decoded_path = raw_path.replace("\\", "/")
        if decoded_path.startswith("/"):
            target = posixpath.normpath(decoded_path.lstrip("/"))
        else:
            target = posixpath.normpath(posixpath.join(self._source_dir, decoded_path))
        if target == ".." or target.startswith("../"):
            self.errors.append(f"README URL escapes the repository: {raw_path}")
            return None
        return target

    def _rewrite_href(self, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme:
            if parts.scheme not in {"https", "mailto"}:
                self.errors.append(f"Unsupported README link scheme: {value}")
                return "#"
            return value
        if parts.netloc:
            self.errors.append(f"Protocol-relative README link is not allowed: {value}")
            return "#"
        if not parts.path:
            if parts.fragment:
                self.fragments.add(parts.fragment)
            return value
        target = self._repo_target(parts.path)
        if target is None:
            return "#"
        target_path = self.root / target
        if not target_path.exists():
            self.errors.append(
                f"README link target does not exist in the repository: {value}"
            )
            return "#"
        if target == self._source_path:
            rewritten_path = ""
            if parts.fragment:
                self.fragments.add(unquote(parts.fragment))
        elif target in self.catalog_by_readme:
            target_detail_dir = PurePosixPath(
                self.catalog_by_readme[target].detail_path
            ).parent.as_posix()
            rewritten_path = posixpath.relpath(target_detail_dir, self._detail_dir) + "/"
        else:
            route = "tree" if target_path.is_dir() else "blob"
            rewritten_path = (
                f"https://github.com/NVIDIA/nemoclaw-community/{route}/main/"
                f"{quote(target, safe='/')}"
            )
        return urlunsplit(("", "", rewritten_path, parts.query, parts.fragment))

    def _rewrite_src(self, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme:
            self.errors.append(
                f"Remote README images must render as outbound links: {value}"
            )
            return ""
        if parts.netloc:
            self.errors.append(f"Protocol-relative README image is not allowed: {value}")
            return ""
        target = self._repo_target(parts.path)
        if target is None:
            return ""
        target_path = self.root / target
        if not is_regular_repo_file(self.root, target_path):
            self.errors.append(f"README image target is not a regular file: {value}")
            return ""
        if target_path.suffix.casefold() not in {
            ".gif",
            ".jpeg",
            ".jpg",
            ".png",
            ".webp",
        }:
            self.errors.append(f"Unsupported README image type: {value}")
            return ""
        if target_path.stat().st_size > 5 * 1024 * 1024:
            self.errors.append(f"README image exceeds the 5 MiB limit: {value}")
            return ""
        self.copied_assets.add(target)
        relative = posixpath.relpath(target, self._detail_dir)
        return urlunsplit(("", "", relative, parts.query, parts.fragment))

    def _safe_attributes(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> list[tuple[str, str]]:
        values = {name: value or "" for name, value in attrs}
        safe: list[tuple[str, str]] = []
        if tag == "a":
            href = values.get("href")
            if href is None:
                self.errors.append("README link is missing href.")
            else:
                safe.append(("href", self._rewrite_href(href)))
            if values.get("title"):
                safe.append(("title", values["title"]))
        elif tag == "img":
            src = values.get("src")
            alt = values.get("alt")
            if not src:
                self.errors.append("README image is missing src.")
            else:
                safe.append(("src", self._rewrite_src(src)))
            if alt is None or not alt.strip():
                self.errors.append("README image is missing meaningful alt text.")
            else:
                safe.append(("alt", alt))
            for name in ("title", "width", "height"):
                if values.get(name):
                    if name in {"width", "height"} and not values[name].isdigit():
                        self.errors.append(f"README image {name} must be numeric.")
                    else:
                        safe.append((name, values[name]))
            safe.extend((("loading", "lazy"), ("decoding", "async")))
            if urlsplit(src or "").scheme:
                safe.append(("referrerpolicy", "no-referrer"))
        elif tag == "iframe":
            source = values.get("src", "")
            parts = urlsplit(source)
            prefix = TUTORIAL_IFRAME_PATHS.get(parts.hostname or "")
            if (
                not self.tutorial_mode
                or parts.scheme != "https"
                or parts.username is not None
                or parts.password is not None
                or prefix is None
                or not parts.path.startswith(prefix)
            ):
                self.errors.append(f"Unsupported tutorial iframe source: {source}")
            title = values.get("title", "").strip()
            if not title:
                self.errors.append("Tutorial iframe is missing a meaningful title.")
            safe.extend(
                (
                    ("src", source),
                    ("title", title),
                    ("loading", "lazy"),
                    ("referrerpolicy", "strict-origin-when-cross-origin"),
                    ("sandbox", "allow-scripts allow-same-origin allow-presentation"),
                )
            )
            if "allowfullscreen" in values:
                safe.append(("allowfullscreen", ""))
        elif tag in {"h2", "h3", "h4", "h5", "h6"}:
            heading_id = values.get("id")
            if not heading_id:
                self.errors.append(f"README {tag} is missing a generated id.")
            elif heading_id in self.ids:
                self.errors.append(f"Duplicate README heading id: {heading_id}")
            else:
                self.ids.add(heading_id)
                safe.append(("id", heading_id))
        elif tag == "code" and values.get("class"):
            class_name = values["class"]
            if re.fullmatch(r"language-[A-Za-z0-9_+.-]+", class_name):
                safe.append(("class", class_name))
            else:
                self.errors.append(f"Unexpected README code class: {class_name}")
        elif tag in {"th", "td"} and values.get("align"):
            if values["align"] not in {"left", "center", "right"}:
                self.errors.append(f"Unexpected README table alignment: {values['align']}")
            else:
                safe.append(("align", values["align"]))
        elif tag == "ol" and values.get("start"):
            if values["start"].isdigit():
                safe.append(("start", values["start"]))
            else:
                self.errors.append("README ordered-list start must be numeric.")
        elif tag == "abbr" and values.get("title"):
            safe.append(("title", values["title"]))
        elif tag == "span":
            class_name = values.get("class", "")
            if class_name and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_-]*(?: [A-Za-z][A-Za-z0-9_-]*)*",
                class_name,
            ):
                safe.append(("class", class_name))
            elif class_name:
                self.errors.append(
                    f"Unexpected tutorial highlight class: {class_name}"
                )
        elif tag == "div":
            class_name = values.get("class")
            if class_name == "toc" or (
                self.tutorial_mode and class_name == "codehilite"
            ):
                safe.append(("class", class_name))
            else:
                self.errors.append(
                    "Unexpected generated README div class."
                )

        allowed_names = {name for name, _ in safe}
        ignored_generated = {"class"} if tag == "div" else set()
        if tag == "iframe":
            ignored_generated.update(
                {"allow", "allowfullscreen", "frameborder", "height", "width"}
            )
        unexpected = set(values) - allowed_names - ignored_generated
        if unexpected:
            self.errors.append(
                f"Unsupported attributes on README {tag}: "
                + ", ".join(sorted(unexpected))
            )
        return safe

    def _start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        self_closing: bool,
    ) -> None:
        if tag in {"iframe", "span"} and not self.tutorial_mode:
            self.errors.append(f"Unsupported README HTML element: {tag}")
            return
        if tag not in self.ALLOWED_TAGS:
            self.errors.append(f"Unsupported README HTML element: {tag}")
            return
        if tag == "img":
            values = {name: value or "" for name, value in attrs}
            source = values.get("src", "")
            source_parts = urlsplit(source)
            if source_parts.scheme or source_parts.netloc:
                alt = values.get("alt", "").strip()
                if (
                    source_parts.scheme != "https"
                    or source_parts.hostname is None
                    or source_parts.username is not None
                    or source_parts.password is not None
                ):
                    self.errors.append(
                        "Remote README image must use credential-free HTTPS: "
                        f"{source}"
                    )
                    return
                if not alt:
                    self.errors.append("Remote README image is missing meaningful alt text.")
                    return
                host = html.escape(source_parts.hostname)
                self.output.append(
                    '<a class="readme-image-link" href="'
                    f'{html.escape(source, quote=True)}" rel="noreferrer">'
                    f'View external image from {host}: '
                    f'{html.escape(alt)} <span aria-hidden="true">↗</span></a>'
                )
                return
        if tag == "table":
            self.output.append('<div class="table-wrapper">')
        safe_attrs = self._safe_attributes(tag, attrs)
        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in safe_attrs
        )
        self.output.append(f"<{tag}{rendered_attrs}>")
        if not self_closing and tag not in self.VOID_TAGS:
            self._open_tags.append(tag)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._start(tag, attrs, False)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._start(tag, attrs, True)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.ALLOWED_TAGS or tag in self.VOID_TAGS:
            return
        if not self._open_tags or self._open_tags[-1] != tag:
            self.errors.append(f"Unbalanced README HTML closing tag: {tag}")
            return
        self._open_tags.pop()
        self.output.append(f"</{tag}>")
        if tag == "table":
            self.output.append("</div>")

    def handle_data(self, data: str) -> None:
        self.output.append(html.escape(data))

    def handle_comment(self, data: str) -> None:
        return

    def result(self) -> str:
        if self._open_tags:
            self.errors.append(
                "Unclosed README HTML elements: " + ", ".join(self._open_tags)
            )
        if self.errors:
            raise CatalogError("\n".join(self.errors))
        return "".join(self.output)


def render_readme_html(
    root: Path,
    entry: CatalogEntry,
    catalog_by_readme: dict[str, CatalogEntry],
    copied_assets: set[str],
) -> tuple[str, str, str, bool]:
    """Compile one source README to sanitized themed-page HTML."""

    if markdown is None:
        raise CatalogError(
            "Catalog detail pages require the pinned Markdown package. Run "
            "`python3 -m pip install --require-hashes -r "
            "scripts/catalog-requirements.txt`."
        )
    try:
        source = (root / entry.content_path).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise CatalogError(
            f"Example source must be valid UTF-8: {entry.content_path}"
        ) from error
    if entry.is_tutorial:
        if pygments is None:
            raise CatalogError(
                "Tutorial pages require the pinned Pygments package. Run "
                "`python3 -m pip install --require-hashes -r "
                "scripts/catalog-requirements.txt`."
            )
        page_title, markdown_body = prepare_tutorial_markdown(
            source, entry.content_path
        )
        toc_depth = "2-4"
    else:
        page_title, markdown_body, toc_depth = entry.title, entry.readme_body, "2-3"
    mermaid_sources = extract_mermaid_sources(source, entry.content_path)
    from markdown.extensions.tables import TableExtension

    extensions: list[Any] = [
        "fenced_code",
        TableExtension(use_align_attribute=True),
        "sane_lists",
        "toc",
    ]
    extension_configs: dict[str, Any] = {
        "toc": {
            "slugify": github_heading_slug,
            "toc_depth": toc_depth,
        }
    }
    if entry.is_tutorial:
        extensions.append("codehilite")
        extension_configs["codehilite"] = {
            "guess_lang": False,
            "noclasses": False,
            "use_pygments": True,
        }
    renderer = markdown.Markdown(
        extensions=extensions,
        extension_configs=extension_configs,
        output_format="html5",
    )
    rendered_body = renderer.convert(markdown_body)
    if entry.is_tutorial:
        rendered_body = annotate_tutorial_code_languages(
            rendered_body,
            tutorial_fence_languages(markdown_body, entry.content_path),
            entry.content_path,
        )
    body_sanitizer = ReadmeHTMLSanitizer(
        root, entry, catalog_by_readme, copied_assets
    )
    body_sanitizer.feed(rendered_body)
    safe_body = body_sanitizer.result()

    if renderer.toc:
        toc_sanitizer = ReadmeHTMLSanitizer(
            root, entry, catalog_by_readme, copied_assets
        )
        toc_sanitizer.feed(renderer.toc)
        safe_toc = toc_sanitizer.result()
        unresolved_toc = toc_sanitizer.fragments - body_sanitizer.ids
        if unresolved_toc:
            raise CatalogError(
                f"Generated README table of contents has unresolved fragments for "
                f"{entry.content_path}: "
                + ", ".join(sorted(unresolved_toc))
            )
    else:
        safe_toc = '<p class="toc-empty">This short guide has no subsections.</p>'
    unresolved_fragments = body_sanitizer.fragments - body_sanitizer.ids
    if unresolved_fragments:
        raise CatalogError(
            f"README has unresolved local fragments for {entry.content_path}: "
            + ", ".join(sorted(unresolved_fragments))
        )
    rendered_mermaid_count = safe_body.count('class="language-mermaid"')
    if rendered_mermaid_count != len(mermaid_sources):
        raise CatalogError(
            f"Mermaid source/render count mismatch for {entry.content_path}."
        )
    return page_title, safe_body, safe_toc, bool(mermaid_sources)
