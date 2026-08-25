#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Verify that the static site matches the canonical example catalog."""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

CATEGORY_IDS: dict[str, str] = {
    "NVIDIA Recipes": "nvidia-recipes",
    "Partner Recipes": "partner-recipes",
    "Community Recipes": "community-recipes",
    "NVIDIA Field Demos": "nvidia-field-demos",
    "Launchables": "launchables",
    "Developer Tools": "developer-tools",
}

CATEGORY_HEADERS: dict[str, tuple[str, ...]] = {
    "NVIDIA Recipes": ("Example", "Description"),
    "Partner Recipes": ("Contributor", "Example", "Description"),
    "Community Recipes": ("Example", "Description"),
    "NVIDIA Field Demos": ("Example", "Description"),
    "Launchables": ("Environment", "Example", "Description"),
    "Developer Tools": ("Example", "Description"),
}

REQUIRED_CARD_FIELDS: set[str] = {"Fit"}
REQUIRED_POLICY_LINKS: set[str] = {
    "https://github.com/NVIDIA/nemoclaw-community",
    "https://github.com/NVIDIA/nemoclaw-community/blob/main/CONTRIBUTING.md",
    "https://github.com/NVIDIA/nemoclaw-community/blob/main/SUPPORT.md",
    "https://github.com/NVIDIA/nemoclaw-community/blob/main/SECURITY.md",
    "https://github.com/brevdev/nemoclaw-demos",
}
GITHUB_BLOB_PREFIX = "https://github.com/NVIDIA/nemoclaw-community/blob/main/"
SUPPORT_BOUNDARY = (
    "NemoClaw Community support is best-effort unless a specific NVIDIA product "
    "agreement says otherwise."
)

CATALOG_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+README\.md(?:#[^)]+)?)\)")
INLINE_CODE_RE = re.compile(r"`([^`]*)`")
TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


@dataclass(frozen=True)
class CatalogEntry:
    """One row in examples/README.md."""

    category: str
    name: str
    readme: str
    outcome: str
    provenance: str


@dataclass
class SiteEntry:
    """One canonical example card in the static page."""

    category: str
    name: str
    readme: str
    element_id: str
    tabindex: str
    labelledby: str
    heading_id: str = ""
    outcome_chunks: list[str] = field(default_factory=list)
    heading_chunks: list[str] = field(default_factory=list)
    provenance_chunks: list[str] = field(default_factory=list)
    field_labels: list[str] = field(default_factory=list)
    field_values: dict[str, list[str]] = field(default_factory=dict)
    guide_links: list[str] = field(default_factory=list)
    guide_texts: list[str] = field(default_factory=list)

    @property
    def outcome(self) -> str:
        return normalize_text(" ".join(self.outcome_chunks))

    @property
    def heading(self) -> str:
        return normalize_text(" ".join(self.heading_chunks))

    @property
    def provenance(self) -> str:
        return normalize_text(" ".join(self.provenance_chunks))


@dataclass(frozen=True)
class CategoryNavLink:
    """One visible category shortcut in the first-screen navigation."""

    href: str
    text: str


def normalize_text(value: str) -> str:
    """Collapse display whitespace and decode HTML entities."""

    return " ".join(html.unescape(value).split())


def normalize_markdown_text(value: str) -> str:
    """Normalize the limited inline Markdown used by catalog outcomes."""

    return normalize_text(INLINE_CODE_RE.sub(r"\1", value))


def find_repo_root() -> Path:
    """Find the repository root from the current working directory."""

    candidate = Path.cwd().resolve()
    while candidate != candidate.parent:
        if (candidate / ".git").exists():
            return candidate
        candidate = candidate.parent
    raise RuntimeError("Run this check from inside the repository.")


def parse_catalog(path: Path) -> list[CatalogEntry]:
    """Read category, name, link, and outcome from examples/README.md."""

    entries: list[CatalogEntry] = []
    seen_headers: Counter[str] = Counter()
    category: str | None = None
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if line.startswith("## "):
            heading = line.removeprefix("## ").strip()
            category = heading if heading in CATEGORY_IDS else None
            continue

        if not line.lstrip().startswith("|"):
            continue

        if category is None:
            if CATALOG_LINK_RE.search(line):
                raise ValueError(
                    "Catalog data row appears outside a canonical category at "
                    f"{path}:{line_number}"
                )
            continue

        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        expected_headers = CATEGORY_HEADERS[category]
        example_column = expected_headers.index("Example")
        is_header = len(cells) > example_column and cells[example_column] == "Example"
        if is_header:
            if tuple(cells) != expected_headers:
                raise ValueError(
                    f"Unexpected catalog table header at {path}:{line_number}; "
                    f"expected {list(expected_headers)}, found {cells}"
                )
            seen_headers[category] += 1
            continue

        is_separator = bool(cells) and all(
            TABLE_SEPARATOR_RE.fullmatch(cell) for cell in cells
        )
        if is_separator:
            if len(cells) != len(expected_headers):
                raise ValueError(
                    f"Unexpected catalog separator width at {path}:{line_number}; "
                    f"expected {len(expected_headers)} columns, found {len(cells)}"
                )
            continue

        if len(cells) != len(expected_headers):
            raise ValueError(
                f"Unexpected catalog row width at {path}:{line_number}; expected "
                f"{len(expected_headers)} columns, found {len(cells)}"
            )

        link_match = CATALOG_LINK_RE.fullmatch(cells[example_column])
        if link_match is None:
            raise ValueError(
                f"Catalog data row has no README link at {path}:{line_number}"
            )

        name, linked_readme = link_match.groups()
        normalized_name = normalize_markdown_text(name)
        outcome = normalize_markdown_text(cells[-1])
        if not normalized_name:
            raise ValueError(f"Catalog name is empty at {path}:{line_number}")
        if not outcome:
            raise ValueError(f"Catalog outcome is empty at {path}:{line_number}")

        if category == "Partner Recipes":
            contributor = normalize_markdown_text(cells[0])
            if not contributor:
                raise ValueError(
                    f"Partner contributor is empty at {path}:{line_number}"
                )
            provenance = f"Partner recipe · {contributor}"
        elif category == "Launchables":
            environment = normalize_markdown_text(cells[0])
            if not environment:
                raise ValueError(
                    f"Launchable environment is empty at {path}:{line_number}"
                )
            provenance = f"Launchable · {environment}"
        else:
            provenance = {
                "NVIDIA Recipes": "NVIDIA recipe",
                "Community Recipes": "Community recipe",
                "NVIDIA Field Demos": "NVIDIA field demo",
                "Developer Tools": "Developer tool",
            }[category]
        relative_readme = linked_readme.partition("#")[0]
        parsed_readme = urlparse(relative_readme)
        if parsed_readme.scheme or relative_readme.startswith("/"):
            raise ValueError(
                f"Catalog README link must be repository-relative at {path}:{line_number}"
            )

        readme_parts = PurePosixPath(relative_readme)
        if ".." in readme_parts.parts:
            raise ValueError(
                f"Catalog README link leaves examples/ at {path}:{line_number}"
            )

        source_readme = (path.parent / Path(*readme_parts.parts)).resolve()
        try:
            source_readme.relative_to(path.parent.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Catalog README link leaves examples/ at {path}:{line_number}"
            ) from exc
        if not source_readme.is_file():
            raise ValueError(
                f"Catalog README link does not exist at {path}:{line_number}: "
                f"{relative_readme}"
            )

        readme = str(PurePosixPath("examples") / readme_parts)
        entries.append(
            CatalogEntry(
                category=category,
                name=normalized_name,
                readme=readme,
                outcome=outcome,
                provenance=provenance,
            )
        )

    invalid_header_counts = {
        category_name: seen_headers[category_name]
        for category_name in CATEGORY_IDS
        if seen_headers[category_name] != 1
    }
    if invalid_header_counts:
        raise ValueError(
            "Each canonical category must have one exact table header in "
            f"{path}: {invalid_header_counts}"
        )

    return entries


class SiteParser(HTMLParser):
    """Collect catalog structure and local-link evidence from the static page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[SiteEntry] = []
        self.ids: list[str] = []
        self.element_tabindexes: dict[str, str] = {}
        self.fragment_links: list[str] = []
        self.resource_paths: list[str] = []
        self.external_links: set[str] = set()
        self.root_relative_urls: list[str] = []
        self.category_stack: list[str | None] = []
        self.current_category: str | None = None
        self.current_entry: SiteEntry | None = None
        self.current_outcome = False
        self.current_heading = False
        self.current_provenance = False
        self.current_field = False
        self.current_field_chunks: list[str] = []
        self.pending_field_label: str | None = None
        self.current_field_value = False
        self.current_field_value_chunks: list[str] = []
        self.current_guide = False
        self.current_guide_chunks: list[str] = []
        self.current_category_nav = False
        self.current_category_nav_href: str | None = None
        self.current_category_nav_chunks: list[str] = []
        self.category_nav_links: list[CategoryNavLink] = []
        self.current_group_heading = False
        self.current_group_heading_chunks: list[str] = []
        self.group_headings: dict[str, list[str]] = {}
        self.catalog_seen = False
        self.category_nav_before_catalog = False
        self.element_tags: dict[str, str] = {}
        self.element_labelledby: dict[str, str] = {}
        self.landmarks: Counter[str] = Counter()
        self.h1_count = 0
        self.script_count = 0
        self.forbidden_embed_tags: Counter[str] = Counter()
        self.inline_event_handlers: list[str] = []
        self.inline_style_count = 0
        self.remote_resource_urls: list[str] = []
        self.image_alts: list[str | None] = []
        self.document_text_chunks: list[str] = []
        self.document_lang: str | None = None
        self.has_viewport = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())

        if tag == "html":
            self.document_lang = values.get("lang")
        if tag == "meta" and values.get("name") == "viewport":
            self.has_viewport = True
        if tag in {"header", "main", "footer", "nav"}:
            self.landmarks[tag] += 1
        if tag == "h1":
            self.h1_count += 1
        if tag == "script":
            self.script_count += 1
        if tag in {"audio", "embed", "form", "iframe", "object", "style", "video"}:
            self.forbidden_embed_tags[tag] += 1
        if tag == "img":
            self.image_alts.append(values.get("alt"))
        for attribute in values:
            if attribute.lower().startswith("on"):
                self.inline_event_handlers.append(attribute)
        if "style" in values:
            self.inline_style_count += 1

        element_id = values.get("id")
        if element_id:
            self.ids.append(element_id)
            self.element_tabindexes[element_id] = values.get("tabindex") or ""
            self.element_tags[element_id] = tag
            self.element_labelledby[element_id] = values.get("aria-labelledby") or ""
        if element_id == "catalog":
            self.catalog_seen = True

        if tag == "nav" and "category-nav" in classes:
            self.current_category_nav = True
            self.category_nav_before_catalog = not self.catalog_seen
        if tag == "a" and self.current_category_nav and values.get("href"):
            self.current_category_nav_href = values["href"] or ""
            self.current_category_nav_chunks = []

        if tag == "section":
            self.category_stack.append(self.current_category)
            category = values.get("data-catalog-category")
            if category:
                self.current_category = category

        if tag == "h2" and self.current_category is not None:
            self.current_group_heading = True
            self.current_group_heading_chunks = []

        if tag == "article" and "data-catalog-entry" in values:
            self.current_entry = SiteEntry(
                category=self.current_category or "",
                name=values.get("data-name") or "",
                readme=values.get("data-readme") or "",
                element_id=element_id or "",
                tabindex=values.get("tabindex") or "",
                labelledby=values.get("aria-labelledby") or "",
            )

        if self.current_entry is not None:
            if tag == "p" and "outcome" in classes:
                self.current_outcome = True
            if tag == "h3":
                self.current_heading = True
                self.current_entry.heading_id = values.get("id") or ""
            if tag == "p" and "provenance" in classes:
                self.current_provenance = True
            if tag == "dt":
                self.current_field = True
                self.current_field_chunks = []
            if tag == "dd":
                self.current_field_value = True
                self.current_field_value_chunks = []
            if tag == "a" and "guide-link" in classes and values.get("href"):
                self.current_entry.guide_links.append(values["href"] or "")
                self.current_guide = True
                self.current_guide_chunks = []

        for attribute in ("data", "href", "poster", "src", "srcset"):
            url = values.get(attribute)
            if not url:
                continue
            if url.startswith("#"):
                if len(url) > 1:
                    self.fragment_links.append(url[1:])
                continue
            if url.startswith("/"):
                self.root_relative_urls.append(url)
                continue
            parsed = urlparse(url)
            if parsed.scheme in {"http", "https", "mailto"}:
                self.external_links.add(url)
                resource_attributes = {
                    "embed": {"src"},
                    "iframe": {"src"},
                    "img": {"src"},
                    "link": {"href"},
                    "object": {"data"},
                    "script": {"src"},
                    "source": {"src", "srcset"},
                }
                if attribute in resource_attributes.get(tag, set()):
                    self.remote_resource_urls.append(url)
                continue
            self.resource_paths.append(url)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_category_nav_href is not None:
            self.category_nav_links.append(
                CategoryNavLink(
                    href=self.current_category_nav_href,
                    text=normalize_text(" ".join(self.current_category_nav_chunks)),
                )
            )
            self.current_category_nav_href = None
            self.current_category_nav_chunks = []

        if tag == "h2" and self.current_group_heading:
            category = self.current_category or ""
            heading = normalize_text(" ".join(self.current_group_heading_chunks))
            self.group_headings.setdefault(category, []).append(heading)
            self.current_group_heading = False
            self.current_group_heading_chunks = []

        if self.current_entry is not None:
            if tag == "p" and self.current_outcome:
                self.current_outcome = False
            if tag == "h3" and self.current_heading:
                self.current_heading = False
            if tag == "p" and self.current_provenance:
                self.current_provenance = False
            if tag == "dt" and self.current_field:
                self.pending_field_label = normalize_text(
                    " ".join(self.current_field_chunks)
                )
                self.current_entry.field_labels.append(self.pending_field_label)
                self.current_field = False
                self.current_field_chunks = []
            if tag == "dd" and self.current_field_value:
                field_value = normalize_text(" ".join(self.current_field_value_chunks))
                field_label = self.pending_field_label or ""
                self.current_entry.field_values.setdefault(field_label, []).append(
                    field_value
                )
                self.pending_field_label = None
                self.current_field_value = False
                self.current_field_value_chunks = []
            if tag == "a" and self.current_guide:
                self.current_entry.guide_texts.append(
                    normalize_text(" ".join(self.current_guide_chunks))
                )
                self.current_guide = False
                self.current_guide_chunks = []
            if tag == "article":
                self.entries.append(self.current_entry)
                self.current_entry = None
                self.current_outcome = False
                self.current_heading = False
                self.current_provenance = False
                self.current_field = False
                self.pending_field_label = None
                self.current_field_value = False
                self.current_guide = False

        if tag == "nav" and self.current_category_nav:
            self.current_category_nav = False
            self.current_category_nav_href = None
            self.current_category_nav_chunks = []
        if tag == "section":
            self.current_category = self.category_stack.pop()

    def handle_data(self, data: str) -> None:
        self.document_text_chunks.append(data)
        if self.current_category_nav_href is not None:
            self.current_category_nav_chunks.append(data)
        if self.current_group_heading:
            self.current_group_heading_chunks.append(data)
        if self.current_entry is None:
            return
        if self.current_outcome:
            self.current_entry.outcome_chunks.append(data)
        if self.current_heading:
            self.current_entry.heading_chunks.append(data)
        if self.current_provenance:
            self.current_entry.provenance_chunks.append(data)
        if self.current_field:
            self.current_field_chunks.append(data)
        if self.current_field_value:
            self.current_field_value_chunks.append(data)
        if self.current_guide:
            self.current_guide_chunks.append(data)


def parse_site(path: Path) -> SiteParser:
    """Parse the static catalog page."""

    parser = SiteParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser


def check_catalog_parity(root: Path) -> list[str]:
    """Return validation errors for the source catalog and static site."""

    errors: list[str] = []
    catalog_path = root / "examples" / "README.md"
    site_path = root / "site" / "index.html"
    root_readme_path = root / "README.md"
    support_path = root / "SUPPORT.md"

    try:
        expected = parse_catalog(catalog_path)
    except (OSError, ValueError) as exc:
        return [str(exc)]

    if not site_path.is_file():
        return [f"Missing static catalog: {site_path.relative_to(root)}"]

    parser = parse_site(site_path)
    expected_readmes = [entry.readme for entry in expected]
    actual_readmes = [entry.readme for entry in parser.entries]

    for readme, count in Counter(expected_readmes).items():
        if count != 1:
            errors.append(f"Canonical catalog contains {count} rows for {readme}.")

    for readme, count in Counter(actual_readmes).items():
        if count != 1:
            errors.append(
                f"Static catalog contains {count} canonical cards for {readme}."
            )

    expected_by_readme = {entry.readme: entry for entry in expected}
    actual_by_readme = {entry.readme: entry for entry in parser.entries}

    for readme in expected_readmes:
        source_entry = expected_by_readme[readme]
        site_entry = actual_by_readme.get(readme)
        if site_entry is None:
            errors.append(f"Static catalog is missing {source_entry.name}: {readme}")
            continue

        if site_entry.category != source_entry.category:
            errors.append(
                f"{source_entry.name} is in {site_entry.category!r}; "
                f"expected {source_entry.category!r}."
            )
        if site_entry.name != source_entry.name:
            errors.append(
                f"Card data-name {site_entry.name!r} does not match {source_entry.name!r}."
            )
        if site_entry.heading != source_entry.name:
            errors.append(
                f"Card heading {site_entry.heading!r} does not match {source_entry.name!r}."
            )
        if site_entry.outcome != source_entry.outcome:
            errors.append(
                f"Outcome drift for {source_entry.name}.\n"
                f"  site:    {site_entry.outcome}\n"
                f"  catalog: {source_entry.outcome}"
            )
        if Counter(site_entry.field_labels) != Counter(REQUIRED_CARD_FIELDS):
            errors.append(
                f"{source_entry.name} fields are {site_entry.field_labels}; "
                f"expected {sorted(REQUIRED_CARD_FIELDS)}."
            )
        for field_label in sorted(REQUIRED_CARD_FIELDS):
            field_values = site_entry.field_values.get(field_label, [])
            if len(field_values) != 1 or not field_values[0]:
                errors.append(
                    f"{source_entry.name} must have one nonempty {field_label!r} value."
                )
        if site_entry.provenance != source_entry.provenance:
            errors.append(
                f"{source_entry.name} provenance/type is {site_entry.provenance!r}; "
                f"expected {source_entry.provenance!r}."
            )
        expected_guide = f"{GITHUB_BLOB_PREFIX}{readme}"
        if site_entry.guide_links != [expected_guide]:
            errors.append(
                f"{source_entry.name} must have one source guide link: {expected_guide}"
            )
        guide_text = f"Get Started with {source_entry.name}"
        if site_entry.guide_texts != [guide_text]:
            errors.append(
                f"{source_entry.name} must have one meaningful guide link name: "
                f"{guide_text!r}"
            )
        if not site_entry.element_id:
            errors.append(
                f"{source_entry.name} card needs an id for direct navigation."
            )
        if site_entry.tabindex != "-1":
            errors.append(
                f'{source_entry.name} card must use tabindex="-1" for fragment focus.'
            )
        expected_heading_id = f"{site_entry.element_id}-title"
        if site_entry.heading_id != expected_heading_id:
            errors.append(
                f"{source_entry.name} heading id must be {expected_heading_id!r}."
            )
        if site_entry.labelledby != expected_heading_id:
            errors.append(
                f"{source_entry.name} card must be labelled by its heading id."
            )

    for readme in sorted(set(actual_readmes) - set(expected_readmes)):
        errors.append(f"Static catalog has an unknown canonical card: {readme}")

    if actual_readmes != expected_readmes:
        errors.append("Static catalog card order does not match examples/README.md.")

    duplicate_ids = sorted(
        element_id for element_id, count in Counter(parser.ids).items() if count > 1
    )
    if duplicate_ids:
        errors.append(f"Duplicate HTML ids: {', '.join(duplicate_ids)}")

    missing_fragments = sorted(set(parser.fragment_links) - set(parser.ids))
    if missing_fragments:
        errors.append(f"Missing fragment targets: {', '.join(missing_fragments)}")

    expected_category_ids = set(CATEGORY_IDS.values())
    missing_category_ids = sorted(expected_category_ids - set(parser.ids))
    if missing_category_ids:
        errors.append(f"Missing category anchors: {', '.join(missing_category_ids)}")

    expected_category_counts = Counter(entry.category for entry in expected)
    expected_category_links = []
    for category, category_id in CATEGORY_IDS.items():
        count = expected_category_counts[category]
        noun = "example" if count == 1 else "examples"
        expected_category_links.append(
            CategoryNavLink(
                href=f"#{category_id}",
                text=f"{category} {count} {noun} →".casefold(),
            )
        )
    actual_category_links = [
        CategoryNavLink(href=link.href, text=link.text.casefold())
        for link in parser.category_nav_links
    ]
    if actual_category_links != expected_category_links:
        errors.append(
            "The first-screen category navigation must visibly name, count, and link "
            "once to all categories in "
            f"canonical order. Expected {expected_category_links}; "
            f"found {actual_category_links}."
        )
    if not parser.category_nav_before_catalog:
        errors.append("The category navigation must appear before the catalog.")

    for category in CATEGORY_IDS:
        headings = parser.group_headings.get(category, [])
        if len(headings) != 1 or headings[0].casefold() != category.casefold():
            errors.append(
                f"Catalog group {category!r} must have one matching visible heading; "
                f"found {headings}."
            )

    focus_target_ids = {"catalog", *expected_category_ids}
    missing_focus_targets = sorted(
        element_id
        for element_id in focus_target_ids
        if parser.element_tabindexes.get(element_id) != "-1"
    )
    if missing_focus_targets:
        errors.append(
            'Fragment destinations must use tabindex="-1": '
            + ", ".join(missing_focus_targets)
        )
    if (
        parser.element_tags.get("catalog") != "section"
        or parser.element_labelledby.get("catalog") != "catalog-title"
    ):
        errors.append(
            "The catalog fragment target must be the catalog section labelled by "
            "catalog-title."
        )

    if parser.root_relative_urls:
        errors.append(
            "Root-relative URLs break the /nemoclaw-community/ Pages path: "
            + ", ".join(sorted(set(parser.root_relative_urls)))
        )

    site_root = site_path.parent
    for resource in sorted(set(parser.resource_paths)):
        resource_path = (site_root / resource).resolve()
        try:
            resource_path.relative_to(site_root.resolve())
        except ValueError:
            errors.append(f"Local resource leaves the site root: {resource}")
            continue
        if not resource_path.is_file():
            errors.append(f"Missing local resource: site/{resource}")

    missing_policy_links = sorted(REQUIRED_POLICY_LINKS - parser.external_links)
    if missing_policy_links:
        errors.append(
            "Missing required public links: " + ", ".join(missing_policy_links)
        )

    if parser.document_lang != "en":
        errors.append('The document must declare html lang="en".')
    if not parser.has_viewport:
        errors.append("The document must include a viewport meta tag.")
    if parser.h1_count != 1:
        errors.append(f"Expected one h1; found {parser.h1_count}.")
    for landmark in ("header", "main", "footer", "nav"):
        if parser.landmarks[landmark] < 1:
            errors.append(f"Missing semantic {landmark} landmark.")
    if parser.script_count:
        errors.append("The v1 catalog must not include client-side scripts.")
    if parser.inline_event_handlers:
        errors.append(
            "Inline event handlers are not allowed: "
            + ", ".join(sorted(set(parser.inline_event_handlers)))
        )
    if parser.inline_style_count:
        errors.append("Inline style attributes are not allowed in the v1 catalog.")
    if parser.forbidden_embed_tags:
        errors.append(
            "Embedded remote-content elements are not allowed: "
            + ", ".join(sorted(parser.forbidden_embed_tags))
        )
    if parser.remote_resource_urls:
        errors.append(
            "Remote page resources are not allowed: "
            + ", ".join(sorted(set(parser.remote_resource_urls)))
        )
    if not parser.image_alts or any(alt is None for alt in parser.image_alts):
        errors.append("Every image must include an alt attribute.")
    document_text = normalize_text(" ".join(parser.document_text_chunks))
    if SUPPORT_BOUNDARY not in document_text:
        errors.append(f"The page must state the support boundary: {SUPPORT_BOUNDARY}")
    policy_boundary = SUPPORT_BOUNDARY.removeprefix("NemoClaw Community ")
    support_policy = normalize_text(support_path.read_text(encoding="utf-8"))
    if policy_boundary.casefold() not in support_policy.casefold():
        errors.append("The catalog support boundary no longer matches SUPPORT.md.")

    stylesheet_path = site_root / "styles.css"
    if not stylesheet_path.is_file():
        errors.append("Missing site/styles.css.")
    else:
        stylesheet = stylesheet_path.read_text(encoding="utf-8")
        if re.search(r"@import\b", stylesheet, flags=re.IGNORECASE):
            errors.append("CSS @import is not allowed in the v1 catalog.")
        for _, css_url in CSS_URL_RE.findall(stylesheet):
            parsed_css_url = urlparse(css_url)
            if (
                parsed_css_url.scheme
                or parsed_css_url.netloc
                or css_url.startswith("/")
            ):
                errors.append(
                    f"Remote or root-relative CSS resource is not allowed: {css_url}"
                )
                continue
            css_resource = (stylesheet_path.parent / css_url).resolve()
            try:
                css_resource.relative_to(site_root.resolve())
            except ValueError:
                errors.append(f"CSS resource leaves the site root: {css_url}")
                continue
            if not css_resource.is_file():
                errors.append(f"Missing CSS resource: site/{css_url}")

    root_readme = root_readme_path.read_text(encoding="utf-8")
    if "https://nvidia.github.io/nemoclaw-community/" not in root_readme:
        errors.append("README.md must include the published catalog URL.")

    return errors


def main() -> int:
    """Run the catalog parity check."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the site. This flag is accepted for consistency with other checks.",
    )
    parser.parse_args()

    root = find_repo_root()
    errors = check_catalog_parity(root)
    if errors:
        print("Catalog parity check failed:")
        for error in errors:
            print(f"  ERROR: {error}")
        return 1

    entries = parse_catalog(root / "examples" / "README.md")
    print(
        "Catalog parity check passed: "
        f"{len(entries)} entries across {len(CATEGORY_IDS)} categories."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
