# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate generated catalog HTML, resources, and security constraints."""

from __future__ import annotations

import hashlib
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from .detail_pages import _detail_relative
from .markdown import (
    DETAIL_CONTENT_SECURITY_POLICY,
    MERMAID_CACHE_PATH,
    MERMAID_SHA256,
    MERMAID_SRI,
    MERMAID_VERSION,
    TUTORIAL_CONTENT_SECURITY_POLICY,
    TUTORIAL_IFRAME_PATHS,
)
from .model import CatalogEntry, CatalogError, Category, Collection
from .sources import is_regular_repo_file


class GeneratedHTMLValidator(HTMLParser):
    """Small dependency-free safety and accessibility check for generated HTML."""

    def __init__(self, *, tutorial_mode: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.tutorial_mode = tutorial_mode
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.fragments: set[str] = set()
        self.cards: list[dict[str, str]] = []
        self.category_groups: list[dict[str, str]] = []
        self.category_info_controls: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.anchors: list[dict[str, str]] = []
        self.links: set[str] = set()
        self.resources: list[str] = []
        self.labels_for: set[str] = set()
        self.tag_counts: dict[str, int] = {}
        self.content_security_policies: list[str] = []
        self.html_language = ""
        self.has_viewport = False
        self.h1_count = 0
        self._inside_script = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {name: value or "" for name, value in attrs}
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
        if tag == "html":
            self.html_language = values.get("lang", "")
        if tag == "meta" and values.get("name") == "viewport":
            self.has_viewport = bool(values.get("content"))
        if tag == "meta" and values.get("http-equiv", "").casefold() == (
            "content-security-policy"
        ):
            self.content_security_policies.append(values.get("content", ""))
        if tag == "label" and values.get("for"):
            self.labels_for.add(values["for"])
        if tag == "a" and values.get("href"):
            self.anchors.append(values)
            self.links.add(values["href"])
        if tag in {"object", "embed"} or (tag == "iframe" and not self.tutorial_mode):
            self.errors.append(f"Forbidden embedded resource element: {tag}")
        if tag == "iframe" and self.tutorial_mode:
            source = values.get("src", "")
            parts = urlsplit(source)
            prefix = TUTORIAL_IFRAME_PATHS.get(parts.hostname or "")
            if (
                parts.scheme != "https"
                or prefix is None
                or not parts.path.startswith(prefix)
                or values.get("sandbox")
                != "allow-scripts allow-same-origin allow-presentation"
            ):
                self.errors.append(f"Unsafe tutorial iframe: {source}")
        if tag == "img" and not values.get("alt"):
            self.errors.append("Every catalog image must have non-empty alt text.")
        element_id = values.get("id")
        if element_id:
            if element_id in self.ids:
                self.errors.append(f"Duplicate HTML id: {element_id}")
            self.ids.add(element_id)
        if tag == "h1":
            self.h1_count += 1
        if tag == "article" and "data-catalog-entry" in values:
            self.cards.append(values)
        if tag == "section" and "data-catalog-category" in values:
            self.category_groups.append(values)
        if tag == "button" and values.get("aria-controls", "").endswith(
            "-description"
        ):
            self.category_info_controls.append(values)
        if tag == "script":
            self.scripts.append(values)
            self._inside_script = True
        for name, value in values.items():
            if name.startswith("on"):
                self.errors.append(f"Inline event handler is not allowed: {name}")
            if name == "style":
                self.errors.append("Inline style attributes are not allowed.")
            if name in {"href", "src"}:
                if value.startswith("/"):
                    self.errors.append(f"Root-relative URL breaks project Pages: {value}")
                if value.startswith("#"):
                    self.fragments.add(unquote(value[1:]))
        if tag in {"img", "link", "script"}:
            resource = values.get("src") or values.get("href") or ""
            if resource:
                self.resources.append(resource)
            remote_tutorial_image = (
                self.tutorial_mode and tag == "img" and resource.startswith("https://")
            )
            if (
                resource.startswith(("http://", "https://", "//"))
                and not remote_tutorial_image
            ):
                self.errors.append(f"Remote page resource is not allowed: {resource}")
        if tag == "form" and values.get("action"):
            self.errors.append("The catalog filter form must not submit externally.")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside_script = False

    def handle_data(self, data: str) -> None:
        if self._inside_script and data.strip():
            self.errors.append("Inline script content is not allowed.")


def validate_generated_site(
    root: Path,
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
    site_html: str,
) -> None:
    parser = GeneratedHTMLValidator()
    parser.feed(site_html)
    errors = list(parser.errors)
    required_ids = {
        "browse-category-panel",
        "browse-industry-panel",
        "catalog",
        "catalog-controls",
        "catalog-search",
        "catalog-view-category",
        "catalog-view-controls",
        "catalog-view-industry",
        "catalog-category",
        "catalog-industry",
        "catalog-maintenance",
        "catalog-reset",
        "catalog-status",
        "catalog-empty",
        "catalog-results",
    }
    missing_ids = required_ids - parser.ids
    if missing_ids:
        errors.append("Missing required catalog IDs: " + ", ".join(sorted(missing_ids)))
    unresolved_fragments = parser.fragments - parser.ids
    if unresolved_fragments:
        errors.append(
            "Unresolved HTML fragments: " + ", ".join(sorted(unresolved_fragments))
        )
    if parser.h1_count != 1:
        errors.append(f"Expected exactly one h1; found {parser.h1_count}.")
    if parser.html_language != "en":
        errors.append("The generated page must declare html lang=\"en\".")
    if not parser.has_viewport:
        errors.append("The generated page must include a viewport meta tag.")
    if parser.tag_counts.get("header", 0) < 1:
        errors.append("The generated page must include a header landmark.")
    for landmark in ("main", "footer"):
        if parser.tag_counts.get(landmark) != 1:
            errors.append(f"Expected exactly one {landmark} landmark.")
    required_labels = {
        "catalog-search",
        "catalog-view-category",
        "catalog-view-industry",
        "catalog-category",
        "catalog-industry",
        "catalog-maintenance",
    }
    missing_labels = required_labels - parser.labels_for
    if missing_labels:
        errors.append(
            "Missing explicit control labels: " + ", ".join(sorted(missing_labels))
        )
    if parser.scripts != [{"type": "module", "src": "scripts/catalog.mjs"}]:
        errors.append("Expected exactly one local module script: scripts/catalog.mjs.")
    expected_resources = [
        "assets/nvidia-favicon.png",
        "styles/shared.css",
        "styles/catalog.css",
        "assets/nvidia-logo.png",
        "scripts/catalog.mjs",
    ]
    if parser.resources != expected_resources:
        errors.append(
            "Generated local page resources changed unexpectedly: "
            + ", ".join(parser.resources)
        )

    expected_cards = [
        {
            "data-readme": entry.readme_path,
            "data-category": entry.category.id,
            "data-industry": entry.industry_id,
            "data-collections": " ".join(entry.collection_ids),
            "data-maintenance": (
                entry.maintenance.id if entry.maintenance else "current"
            ),
        }
        for entry in entries
    ]
    actual_cards = [
        {key: card.get(key, "") for key in expected_cards[0]}
        for card in parser.cards
    ] if expected_cards else []
    if actual_cards != expected_cards:
        errors.append("Generated card metadata or order does not match the READMEs.")
    for entry, card in zip(entries, parser.cards):
        if card.get("id") != entry.id:
            errors.append(f"Generated card ID does not match {entry.title}.")
        if card.get("aria-labelledby") != f"{entry.id}-title":
            errors.append(f"Generated card label does not match {entry.title}.")
    for category in categories:
        category_attrs = next(
            (
                attrs
                for attrs in parser.category_groups
                if attrs.get("data-catalog-category") == category.id
            ),
            None,
        )
        if category_attrs is None or category_attrs.get("tabindex") != "-1":
            errors.append(f"Category fragment is not focusable: {category.id}")

    browse_groups: tuple[Category | Collection, ...] = (
        *(category for category in categories if category.browse),
        *collections,
    )
    expected_info_controls = [
        {
            "aria-label": f"About {group.title}",
            "aria-controls": (
                f"{group.id}-description"
                if isinstance(group, Category)
                else f"{group.browse_id}-description"
            ),
            "aria-expanded": "false",
            "type": "button",
        }
        for group in browse_groups
    ]
    actual_info_controls = [
        {
            key: control.get(key, "") for key in expected_info_controls[0]
        }
        for control in parser.category_info_controls
    ] if expected_info_controls else []
    if actual_info_controls != expected_info_controls:
        errors.append("Browse-group information controls are incomplete or mislabeled.")
    for control in actual_info_controls:
        if control["aria-controls"] not in parser.ids:
            errors.append(
                "Browse-group information control has no description: "
                + control["aria-controls"]
            )

    required_links = {
        "catalog.json",
        "llms.txt",
        "https://brev.nvidia.com/launchable/deploy?launchableID=env-3Azt0aYgVNFEuz7opyx3gscmowS",
        "https://github.com/NVIDIA/nemoclaw-community/blob/main/CONTRIBUTING.md#add-a-new-example",
        "https://github.com/NVIDIA/nemoclaw-community/blob/main/SUPPORT.md",
        "https://github.com/NVIDIA/nemoclaw-community/blob/main/SECURITY.md",
    }
    missing_links = required_links - parser.links
    if missing_links:
        errors.append("Missing required catalog links: " + ", ".join(sorted(missing_links)))
    new_tab_links = {
        "https://brev.nvidia.com/launchable/deploy?launchableID=env-3Azt0aYgVNFEuz7opyx3gscmowS": (
            "Launch NemoClaw on Brev (opens in a new tab)"
        ),
        "https://github.com/NVIDIA/nemoclaw-community": (
            "GitHub repository (opens in a new tab)"
        ),
    }
    for href, expected_label in new_tab_links.items():
        anchor = next(
            (item for item in parser.anchors if item.get("href") == href),
            None,
        )
        if anchor is None:
            errors.append(f"Missing header link: {href}")
            continue
        rel = set(anchor.get("rel", "").split())
        if anchor.get("target") != "_blank" or not {
            "noopener",
            "noreferrer",
        }.issubset(rel):
            errors.append(f"Header link must open safely in a new tab: {href}")
        if anchor.get("aria-label") != expected_label:
            errors.append(f"Header link must announce its new-tab behavior: {href}")
    if "NemoClaw Community support is best-effort" not in site_html:
        errors.append("The catalog support boundary no longer matches SUPPORT.md.")

    style_sources = [
        "site/styles/shared.css",
        "site/styles/catalog.css",
        "site/styles/detail.css",
    ]
    if any(entry.is_tutorial for entry in entries):
        style_sources.append("site/styles/tutorial.css")
    required_site_sources = (
        *style_sources,
        "site/scripts/catalog-state.mjs",
        "site/scripts/catalog.mjs",
        "site/assets/nvidia-logo.png",
        "site/assets/nvidia-favicon.png",
    )
    for relative in required_site_sources:
        if not is_regular_repo_file(root, root / relative):
            errors.append(f"Missing required site source: {relative}")
    for relative in style_sources:
        css_path = root / relative
        if not is_regular_repo_file(root, css_path):
            continue
        css = css_path.read_text(encoding="utf-8")
        if re.search(r"@import\b", css, flags=re.IGNORECASE):
            errors.append(f"CSS @import is not allowed in {relative}.")
        if re.search(r"url\(\s*['\"]?(?:https?:)?//", css, flags=re.IGNORECASE):
            errors.append(f"Remote CSS resources are not allowed in {relative}.")
    root_readme = (root / "README.md").read_text(encoding="utf-8")
    if "https://nvidia.github.io/nemoclaw-community/" not in root_readme:
        errors.append("README.md must include the published catalog URL.")
    if errors:
        raise CatalogError("\n".join(errors))


def validate_detail_pages(
    root: Path,
    entries: list[CatalogEntry],
    detail_pages: dict[str, str],
) -> None:
    expected_paths = {entry.detail_path for entry in entries}
    if set(detail_pages) != expected_paths:
        raise CatalogError("Generated detail-page paths do not match the catalog.")
    parsers: dict[str, GeneratedHTMLValidator] = {}
    for entry in entries:
        parser = GeneratedHTMLValidator(tutorial_mode=entry.is_tutorial)
        parser.feed(detail_pages[entry.detail_path])
        parsers[entry.detail_path] = parser

    for entry in entries:
        page = detail_pages[entry.detail_path]
        parser = parsers[entry.detail_path]
        errors = list(parser.errors)
        if parser.html_language != "en":
            errors.append("Detail page must declare html lang=\"en\".")
        if not parser.has_viewport:
            errors.append("Detail page must include a viewport meta tag.")
        if parser.h1_count != 1:
            errors.append(
                f"Detail page must contain one h1; found {parser.h1_count}."
            )
        for landmark in ("main", "footer"):
            if parser.tag_counts.get(landmark) != 1:
                errors.append(f"Detail page must contain one {landmark} landmark.")
        required_ids = {"detail-title", "facts-title", "toc-title", "readme"}
        missing_ids = required_ids - parser.ids
        if missing_ids:
            errors.append(
                "Detail page is missing required IDs: "
                + ", ".join(sorted(missing_ids))
            )
        unresolved_fragments = parser.fragments - parser.ids
        if unresolved_fragments:
            errors.append(
                "Detail page has unresolved fragments: "
                + ", ".join(sorted(unresolved_fragments))
            )
        current_dir = PurePosixPath(entry.detail_path).parent.as_posix()
        for href in parser.links:
            parts = urlsplit(href)
            if (
                not parts.fragment
                or not parts.path
                or parts.scheme
                or parts.netloc
            ):
                continue
            target_path = posixpath.normpath(
                posixpath.join(current_dir, unquote(parts.path))
            )
            if parts.path.endswith("/"):
                target_path = posixpath.join(target_path, "index.html")
            target_parser = parsers.get(target_path)
            if (
                target_parser is not None
                and unquote(parts.fragment) not in target_parser.ids
            ):
                errors.append(
                    "Detail page links to an unresolved README fragment: "
                    f"{href}"
                )
        has_mermaid = 'class="language-mermaid"' in page
        expected_scripts: list[dict[str, str]] = []
        if has_mermaid:
            expected_scripts.extend([
                {
                    "src": _detail_relative(
                        entry, "assets/vendor/mermaid.tiny.js"
                    ),
                    "integrity": MERMAID_SRI,
                },
                {
                    "type": "module",
                    "src": _detail_relative(entry, "scripts/diagrams.mjs"),
                },
            ])
        if entry.is_tutorial:
            expected_scripts.append(
                {
                    "type": "module",
                    "src": _detail_relative(entry, "scripts/tutorial.mjs"),
                }
            )
        if parser.scripts != expected_scripts:
            errors.append("Detail-page local scripts changed unexpectedly.")
        for script in expected_scripts:
            if script["src"] not in parser.resources:
                errors.append(f"Detail page is missing {script['src']}.")
        expected_policy = (
            TUTORIAL_CONTENT_SECURITY_POLICY
            if entry.is_tutorial
            else DETAIL_CONTENT_SECURITY_POLICY
        )
        if parser.content_security_policies != [expected_policy]:
            errors.append("Detail page Content Security Policy changed unexpectedly.")
        expected_styles = _detail_relative(entry, "styles/shared.css")
        expected_detail_styles = _detail_relative(entry, "styles/detail.css")
        expected_logo = _detail_relative(entry, "assets/nvidia-logo.png")
        expected_favicon = _detail_relative(entry, "assets/nvidia-favicon.png")
        if expected_styles not in parser.resources:
            errors.append("Detail page is missing the shared stylesheet.")
        if expected_detail_styles not in parser.resources:
            errors.append("Detail page is missing the detail stylesheet.")
        tutorial_styles = _detail_relative(entry, "styles/tutorial.css")
        if entry.is_tutorial and tutorial_styles not in parser.resources:
            errors.append("Tutorial page is missing its stylesheet.")
        if not entry.is_tutorial and tutorial_styles in parser.resources:
            errors.append("Regular detail page loads the tutorial stylesheet.")
        if expected_logo not in parser.resources:
            errors.append("Detail page is missing the local NVIDIA logo.")
        if expected_favicon not in parser.resources:
            errors.append("Detail page is missing the local NVIDIA favicon.")
        required_links = {
            entry.content_url,
            _detail_relative(entry, "index.html"),
            "https://github.com/NVIDIA/nemoclaw-community/blob/main/SUPPORT.md",
            "https://github.com/NVIDIA/nemoclaw-community/blob/main/SECURITY.md",
        }
        if entry.upstream_url:
            required_links.add(entry.upstream_url)
        missing_links = required_links - parser.links
        if missing_links:
            errors.append(
                "Detail page is missing required links: "
                + ", ".join(sorted(missing_links))
            )
        if "NemoClaw Community support is best-effort" not in page:
            errors.append("Detail-page support text no longer matches SUPPORT.md.")
        if ">Fit<" in page or ">Fit:" in page:
            errors.append("Detail page still exposes the ambiguous Fit label.")
        if errors:
            raise CatalogError(
                f"Invalid generated detail page for {entry.title}:\n"
                + "\n".join(errors)
            )

    if any('class="language-mermaid"' in page for page in detail_pages.values()):
        for relative in (
            "site/scripts/diagrams.mjs",
            "site/assets/vendor/mermaid-LICENSE.txt",
        ):
            if not is_regular_repo_file(root, root / relative):
                raise CatalogError(f"Missing required diagram source: {relative}")
    if any(entry.is_tutorial for entry in entries):
        for relative in (
            "site/styles/tutorial.css",
            "site/scripts/tutorial.mjs",
        ):
            if not is_regular_repo_file(root, root / relative):
                raise CatalogError(f"Missing required tutorial source: {relative}")


def verified_mermaid_asset(root: Path) -> Path:
    """Return the pinned Mermaid bundle only when its local cache is trustworthy."""

    asset = root / MERMAID_CACHE_PATH
    if (
        not is_regular_repo_file(root, asset)
    ):
        raise CatalogError(
            "The pinned Mermaid browser asset is missing. Run "
            "`python3 scripts/fetch_catalog_assets.py`."
        )
    digest = hashlib.sha256()
    with asset.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != MERMAID_SHA256:
        raise CatalogError(
            f"The cached Mermaid {MERMAID_VERSION} asset failed its SHA-256 "
            "check. Run `python3 scripts/fetch_catalog_assets.py` to replace it."
        )
    return asset
