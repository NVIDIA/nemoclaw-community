#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate catalog metadata and build the static GitHub Pages catalog."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


INDUSTRIES: tuple[str, ...] = (
    "Academia/education",
    "AEC",
    "Aerospace",
    "Agriculture",
    "Automotive/transportation",
    "Cloud services",
    "Consumer internet",
    "Energy",
    "Financial services",
    "Gaming",
    "Hardware/semiconductor",
    "Health and life sciences",
    "HPC/scientific computing",
    "Manufacturing",
    "Media & entertainment",
    "Public sector",
    "Restaurant/quick service",
    "Retail/consumer packaged goods",
    "Smart cities/spaces",
    "Telecommunications",
    "Other",
)

COLLECTIONS: tuple[str, ...] = ("hackathon",)
PATH_SEGMENT_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


@dataclass(frozen=True)
class Category:
    """One canonical artifact/provenance category."""

    id: str
    title: str
    singular: str
    description: str
    kind: str
    provenance: str | None = None


CATEGORIES: tuple[Category, ...] = (
    Category(
        "nvidia-recipes",
        "NVIDIA Recipes",
        "NVIDIA recipe",
        "Reusable agent recipes authored or maintained by NVIDIA. Placement does not state a support or maturity level.",
        "recipe",
        "nvidia",
    ),
    Category(
        "partner-recipes",
        "Partner Recipes",
        "Partner recipe",
        "Reusable agent recipes contributed by named partner organizations. Partner attribution remains visible on each entry.",
        "recipe",
        "partner",
    ),
    Category(
        "community-recipes",
        "Community Recipes",
        "Community recipe",
        "Reusable agent recipes contributed independently without formal organizational provenance.",
        "recipe",
        "community",
    ),
    Category(
        "nvidia-field-demos",
        "NVIDIA Field Demos",
        "NVIDIA field demo",
        "Bounded NVIDIA demonstrations for named hardware and software environments.",
        "demo",
    ),
    Category(
        "launchables",
        "Launchables",
        "Launchable",
        "Provisioning and onboarding paths for a specific environment.",
        "launchable",
    ),
    Category(
        "developer-tools",
        "Developer Tools",
        "Developer tool",
        "Standalone development and evaluation utilities, separate from deployed agent blueprints.",
        "tool",
    ),
)

CATEGORY_BY_ID = {category.id: category for category in CATEGORIES}


@dataclass(frozen=True)
class CatalogEntry:
    """Validated source metadata plus taxonomy derived from its path."""

    path: str
    title: str
    description: str
    industry: str
    fit: str
    collections: tuple[str, ...]
    category: Category
    contributor: str | None = None
    environment: str | None = None

    @property
    def readme_path(self) -> str:
        return f"examples/{self.path}/README.md"

    @property
    def guide_url(self) -> str:
        return (
            "https://github.com/NVIDIA/nemoclaw-community/blob/main/"
            f"{self.readme_path}"
        )

    @property
    def id(self) -> str:
        return f"example-{slugify(self.title)}"

    @property
    def industry_id(self) -> str:
        return slugify(self.industry)

    @property
    def display_label(self) -> str:
        if self.category.id == "partner-recipes":
            return f"{self.category.singular} · {self.contributor}"
        if self.category.id == "launchables":
            return f"{self.category.singular} · {self.environment}"
        return self.category.singular

    @property
    def search_text(self) -> str:
        values = (
            self.title,
            self.description,
            self.industry,
            self.fit,
            self.category.title,
            self.display_label,
            self.contributor or "",
            self.environment or "",
            " ".join(self.collections),
        )
        return " ".join(value for value in values if value)


class CatalogError(ValueError):
    """Raised when source metadata or generated output is invalid."""


def slugify(value: str) -> str:
    """Return the stable lowercase URL identifier used by the catalog UI."""

    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def classify_path(path: str) -> Category:
    """Derive artifact kind and recipe provenance from canonical placement."""

    parts = PurePosixPath(path).parts
    category_id: str | None = None
    if len(parts) == 3 and parts[:2] == ("recipes", "nvidia"):
        category_id = "nvidia-recipes"
    elif len(parts) == 3 and parts[:2] == ("recipes", "community"):
        category_id = "community-recipes"
    elif len(parts) == 4 and parts[:2] == ("recipes", "partners"):
        category_id = "partner-recipes"
    elif len(parts) == 3 and parts[:2] == ("demos", "field"):
        category_id = "nvidia-field-demos"
    elif len(parts) == 3 and parts[0] == "launchables":
        category_id = "launchables"
    elif len(parts) == 2 and parts[0] == "tools":
        category_id = "developer-tools"

    if category_id is None or any(
        PATH_SEGMENT_PATTERN.fullmatch(part) is None for part in parts
    ):
        raise CatalogError(
            f"Catalog path does not match the canonical example taxonomy: {path!r}"
        )
    return CATEGORY_BY_ID[category_id]


def _required_string(record: dict[str, Any], key: str, index: int) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CatalogError(
            f"examples[{index}].{key} must be a non-empty, trimmed string."
        )
    if "\n" in value or "\r" in value:
        raise CatalogError(f"examples[{index}].{key} must be one line.")
    return value


def _optional_string(record: dict[str, Any], key: str, index: int) -> str | None:
    if key not in record:
        return None
    return _required_string(record, key, index)


def discover_example_paths(root: Path) -> set[str]:
    """Discover catalog-level example READMEs at taxonomy-defined depths."""

    examples = root / "examples"
    patterns = (
        "recipes/nvidia/*/README.md",
        "recipes/community/*/README.md",
        "recipes/partners/*/*/README.md",
        "demos/field/*/README.md",
        "launchables/*/*/README.md",
        "tools/*/README.md",
    )
    paths: set[str] = set()
    for pattern in patterns:
        for readme in examples.glob(pattern):
            paths.add(readme.parent.relative_to(examples).as_posix())
    return paths


def _validate_schema_contract(root: Path) -> None:
    schema_path = root / "examples" / "catalog.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        enum = schema["$defs"]["example"]["properties"]["industry"]["enum"]
        collection_enum = schema["$defs"]["example"]["properties"]["collections"][
            "items"
        ]["enum"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise CatalogError(f"Invalid catalog schema: {error}") from error
    if tuple(enum) != INDUSTRIES:
        raise CatalogError("catalog.schema.json industry enum is out of sync.")
    if tuple(collection_enum) != COLLECTIONS:
        raise CatalogError("catalog.schema.json collection enum is out of sync.")


def load_catalog(root: Path) -> list[CatalogEntry]:
    """Load and validate the canonical source manifest."""

    _validate_schema_contract(root)
    manifest_path = root / "examples" / "catalog.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"Invalid catalog manifest: {error}") from error

    if not isinstance(manifest, dict):
        raise CatalogError("examples/catalog.json must contain a JSON object.")
    allowed_manifest_keys = {"$schema", "schema_version", "examples"}
    unexpected_manifest = set(manifest) - allowed_manifest_keys
    if unexpected_manifest:
        raise CatalogError(
            "Unexpected catalog manifest keys: "
            + ", ".join(sorted(unexpected_manifest))
        )
    if manifest.get("$schema") != "catalog.schema.json":
        raise CatalogError("examples/catalog.json must reference catalog.schema.json.")
    if manifest.get("schema_version") != 1:
        raise CatalogError("Unsupported catalog schema_version; expected 1.")
    records = manifest.get("examples")
    if not isinstance(records, list):
        raise CatalogError("examples/catalog.json examples must be an array.")

    entries: list[CatalogEntry] = []
    seen_paths: set[str] = set()
    seen_titles: set[str] = set()
    seen_ids: set[str] = set()
    base_keys = {
        "path",
        "title",
        "description",
        "industry",
        "fit",
        "collections",
        "contributor",
        "environment",
    }
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise CatalogError(f"examples[{index}] must be a JSON object.")
        unexpected = set(record) - base_keys
        if unexpected:
            raise CatalogError(
                f"Unexpected keys in examples[{index}]: "
                + ", ".join(sorted(unexpected))
            )
        path = _required_string(record, "path", index)
        category = classify_path(path)
        title = _required_string(record, "title", index)
        description = _required_string(record, "description", index)
        industry = _required_string(record, "industry", index)
        fit = _required_string(record, "fit", index)
        contributor = _optional_string(record, "contributor", index)
        environment = _optional_string(record, "environment", index)
        collections_value = record.get("collections")
        if not isinstance(collections_value, list) or any(
            not isinstance(item, str) for item in collections_value
        ):
            raise CatalogError(f"examples[{index}].collections must be an array of strings.")
        if len(collections_value) != len(set(collections_value)):
            raise CatalogError(f"examples[{index}].collections contains duplicates.")
        unknown_collections = set(collections_value) - set(COLLECTIONS)
        if unknown_collections:
            raise CatalogError(
                f"examples[{index}] has unknown collections: "
                + ", ".join(sorted(unknown_collections))
            )
        if "hackathon" in collections_value and category.kind != "recipe":
            raise CatalogError("Only recipes can join the hackathon collection.")
        if industry not in INDUSTRIES:
            raise CatalogError(
                f"examples[{index}].industry must be one of the documented values; "
                f"got {industry!r}."
            )
        if category.id == "partner-recipes" and contributor is None:
            raise CatalogError(f"Partner recipe {path!r} requires contributor.")
        if category.id == "launchables" and environment is None:
            raise CatalogError(f"Launchable {path!r} requires environment.")
        if category.id != "launchables" and environment is not None:
            raise CatalogError(f"Only launchables can set environment ({path!r}).")

        entry = CatalogEntry(
            path=path,
            title=title,
            description=description,
            industry=industry,
            fit=fit,
            collections=tuple(collections_value),
            category=category,
            contributor=contributor,
            environment=environment,
        )
        if path in seen_paths:
            raise CatalogError(f"Duplicate catalog path: {path}")
        if title.casefold() in seen_titles:
            raise CatalogError(f"Duplicate catalog title: {title}")
        if entry.id in seen_ids:
            raise CatalogError(f"Duplicate generated catalog ID: {entry.id}")
        seen_paths.add(path)
        seen_titles.add(title.casefold())
        seen_ids.add(entry.id)
        entries.append(entry)

    discovered = discover_example_paths(root)
    missing = discovered - seen_paths
    unknown = seen_paths - discovered
    if missing:
        raise CatalogError(
            "Example directories missing from examples/catalog.json: "
            + ", ".join(sorted(missing))
        )
    if unknown:
        raise CatalogError(
            "Catalog paths without a top-level README: " + ", ".join(sorted(unknown))
        )

    for entry in entries:
        readme = root / entry.readme_path
        content = readme.read_text(encoding="utf-8")
        if re.search(r"^#\s+\S", content, flags=re.MULTILINE) is None:
            raise CatalogError(f"Example README has no level-one title: {entry.readme_path}")

    return entries


def _markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render_readme(entries: Iterable[CatalogEntry]) -> str:
    """Render the human-readable source catalog from canonical metadata."""

    grouped = group_entries(entries)
    lines = [
        "<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->",
        "<!-- SPDX-License-Identifier: Apache-2.0 -->",
        "",
        "# NemoClaw Community Example Catalog",
        "",
        "Examples are organized first by artifact type. Reusable recipes are organized",
        "again by contributor provenance. Industry is an independent discovery field.",
        "This file is generated from [`catalog.json`](catalog.json); edit the manifest and",
        "run `python3 scripts/build_catalog.py --write` from the repository root.",
        "",
    ]
    for category in CATEGORIES:
        category_entries = grouped[category.id]
        lines.extend((f"## {category.title}", ""))
        if category.id == "partner-recipes":
            lines.extend(
                (
                    "| Contributor | Example | Industry | Description |",
                    "| --- | --- | --- | --- |",
                )
            )
            for entry in category_entries:
                lines.append(
                    f"| {_markdown_cell(entry.contributor or '')} | "
                    f"[{_markdown_cell(entry.title)}]({entry.path}/README.md) | "
                    f"{_markdown_cell(entry.industry)} | "
                    f"{_markdown_cell(entry.description)} |"
                )
        elif category.id == "launchables":
            lines.extend(
                (
                    "| Environment | Example | Industry | Description |",
                    "| --- | --- | --- | --- |",
                )
            )
            for entry in category_entries:
                lines.append(
                    f"| {_markdown_cell(entry.environment or '')} | "
                    f"[{_markdown_cell(entry.title)}]({entry.path}/README.md) | "
                    f"{_markdown_cell(entry.industry)} | "
                    f"{_markdown_cell(entry.description)} |"
                )
        else:
            lines.extend(
                (
                    "| Example | Industry | Description |",
                    "| --- | --- | --- |",
                )
            )
            for entry in category_entries:
                lines.append(
                    f"| [{_markdown_cell(entry.title)}]({entry.path}/README.md) | "
                    f"{_markdown_cell(entry.industry)} | "
                    f"{_markdown_cell(entry.description)} |"
                )
        lines.append("")

    lines.extend(
        (
            "## Contributing An Example",
            "",
            "Read [CONTRIBUTING.md](../CONTRIBUTING.md) and the canonical",
            "[example taxonomy and naming policy](../.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md).",
            "Examples must remain independently deployable and must document their",
            "prerequisites, credentials, policies, startup behavior, verification, and",
            "teardown behavior. Add structured catalog metadata as described in the",
            "[contributor guide](../CONTRIBUTING.md#catalog-metadata).",
            "",
        )
    )
    return "\n".join(lines)


def group_entries(entries: Iterable[CatalogEntry]) -> dict[str, list[CatalogEntry]]:
    grouped = {category.id: [] for category in CATEGORIES}
    for entry in entries:
        grouped[entry.category.id].append(entry)
    return grouped


def _plural(count: int, noun: str = "example") -> str:
    return f"{count} {noun if count == 1 else noun + 's'}"


def render_category_nav(entries: list[CatalogEntry]) -> str:
    grouped = group_entries(entries)
    tiles = []
    for category in CATEGORIES:
        count = len(grouped[category.id])
        tiles.append(
            "\n".join(
                (
                    f'<a class="category-tile" href="#{category.id}">',
                    f'  <span class="category-name">{html.escape(category.title)}</span>',
                    f'  <span class="category-count">{_plural(count)} <span aria-hidden="true">→</span></span>',
                    "</a>",
                )
            )
        )
    return "\n".join(tiles)


def category_filter_options(entries: list[CatalogEntry]) -> str:
    grouped = group_entries(entries)
    type_values = [("all", "All example types", len(entries))]
    type_values.extend(
        (category.id, category.title, len(grouped[category.id]))
        for category in CATEGORIES
    )
    type_options = "\n".join(
        f'<option value="{value}">{html.escape(label)} ({count})</option>'
        for value, label, count in type_values
    )
    hackathon_count = sum("hackathon" in entry.collections for entry in entries)
    return "\n".join(
        (
            '<optgroup label="Example types">',
            indent(type_options, 2),
            "</optgroup>",
            '<optgroup label="Collections">',
            f'  <option value="hackathon-recipes">Hackathon recipes ({hackathon_count})</option>',
            "</optgroup>",
        )
    )


def industry_filter_options(entries: list[CatalogEntry]) -> str:
    counts = {industry: 0 for industry in INDUSTRIES}
    for entry in entries:
        counts[entry.industry] += 1
    options = [f'<option value="all">All industries ({len(entries)})</option>']
    options.extend(
        f'<option value="{slugify(industry)}">{html.escape(industry)} ({counts[industry]})</option>'
        for industry in INDUSTRIES
    )
    return "\n".join(options)


def render_card(entry: CatalogEntry) -> str:
    collections = " ".join(entry.collections)
    collection_tags = "".join(
        f'<li class="tag tag-collection">{html.escape(collection.title())}</li>'
        for collection in entry.collections
    )
    return f'''<article
  class="example-card"
  id="{entry.id}"
  aria-labelledby="{entry.id}-title"
  data-catalog-entry
  data-name="{html.escape(entry.title, quote=True)}"
  data-readme="{html.escape(entry.readme_path, quote=True)}"
  data-category="{entry.category.id}"
  data-industry="{entry.industry_id}"
  data-collections="{html.escape(collections, quote=True)}"
  data-search="{html.escape(entry.search_text, quote=True)}"
  tabindex="-1"
>
  <p class="provenance">{html.escape(entry.display_label)}</p>
  <h3 id="{entry.id}-title">{html.escape(entry.title)}</h3>
  <p class="outcome">{html.escape(entry.description)}</p>
  <ul class="card-tags" aria-label="Discovery fields">
    <li class="tag">{html.escape(entry.industry)}</li>{collection_tags}
  </ul>
  <dl class="fit">
    <div><dt>Fit</dt><dd>{html.escape(entry.fit)}</dd></div>
  </dl>
  <a class="guide-link" href="{entry.guide_url}">Get Started<span class="sr-only"> with {html.escape(entry.title)}</span></a>
</article>'''


def render_catalog_groups(entries: list[CatalogEntry]) -> str:
    grouped = group_entries(entries)
    sections = []
    for category in CATEGORIES:
        cards = "\n".join(render_card(entry) for entry in grouped[category.id])
        sections.append(
            f'''<section
  class="catalog-group"
  id="{category.id}"
  tabindex="-1"
  data-catalog-category="{category.id}"
  aria-labelledby="{category.id}-title"
>
  <div class="shell group-layout">
    <header class="group-heading">
      <h2 id="{category.id}-title">{html.escape(category.title)}</h2>
      <p>{html.escape(category.description)}</p>
    </header>
    <div class="card-grid">
{indent(cards, 6)}
    </div>
  </div>
</section>'''
        )
    return "\n".join(sections)


def indent(value: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else line for line in value.splitlines())


def render_site(entries: list[CatalogEntry], template: str) -> str:
    represented_industries = len({entry.industry for entry in entries})
    replacements = {
        "{{EXAMPLE_COUNT}}": str(len(entries)),
        "{{INDUSTRY_COUNT}}": str(len(INDUSTRIES)),
        "{{REPRESENTED_INDUSTRY_COUNT}}": str(represented_industries),
        "{{CATEGORY_NAV}}": indent(render_category_nav(entries), 14),
        "{{CATEGORY_OPTIONS}}": indent(category_filter_options(entries), 18),
        "{{INDUSTRY_OPTIONS}}": indent(industry_filter_options(entries), 18),
        "{{CATALOG_GROUPS}}": indent(render_catalog_groups(entries), 8),
    }
    rendered = template
    for marker, value in replacements.items():
        count = rendered.count(marker)
        expected_count = 2 if marker == "{{EXAMPLE_COUNT}}" else 1
        if count != expected_count:
            raise CatalogError(
                f"Expected {expected_count} {marker} marker(s) in "
                "site/index.template.html."
            )
        rendered = rendered.replace(marker, value)
    leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)
    if leftover:
        raise CatalogError("Unknown template markers: " + ", ".join(sorted(leftover)))
    return rendered


def public_catalog(entries: list[CatalogEntry]) -> dict[str, Any]:
    grouped = group_entries(entries)
    industry_counts = {industry: 0 for industry in INDUSTRIES}
    for entry in entries:
        industry_counts[entry.industry] += 1
    return {
        "schema_version": 1,
        "source": "https://github.com/NVIDIA/nemoclaw-community/blob/main/examples/catalog.json",
        "categories": [
            {
                "id": category.id,
                "label": category.title,
                "kind": category.kind,
                "provenance": category.provenance,
                "count": len(grouped[category.id]),
            }
            for category in CATEGORIES
        ],
        "industries": [
            {
                "id": slugify(industry),
                "label": industry,
                "count": industry_counts[industry],
            }
            for industry in INDUSTRIES
        ],
        "collections": [
            {
                "id": "hackathon",
                "label": "Hackathon recipes",
                "count": sum("hackathon" in entry.collections for entry in entries),
            }
        ],
        "examples": [
            {
                "id": entry.id,
                "title": entry.title,
                "description": entry.description,
                "industry": {
                    "id": entry.industry_id,
                    "label": entry.industry,
                },
                "kind": entry.category.kind,
                "provenance": entry.category.provenance,
                "category": {
                    "id": entry.category.id,
                    "label": entry.category.title,
                },
                "contributor": entry.contributor,
                "environment": entry.environment,
                "collections": list(entry.collections),
                "fit": entry.fit,
                "source_path": entry.readme_path,
                "guide_url": entry.guide_url,
            }
            for entry in entries
        ],
    }


class GeneratedHTMLValidator(HTMLParser):
    """Small dependency-free safety and accessibility check for generated HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.fragments: set[str] = set()
        self.cards: list[dict[str, str]] = []
        self.category_groups: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.links: set[str] = set()
        self.resources: list[str] = []
        self.labels_for: set[str] = set()
        self.tag_counts: dict[str, int] = {}
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
        if tag == "label" and values.get("for"):
            self.labels_for.add(values["for"])
        if tag == "a" and values.get("href"):
            self.links.add(values["href"])
        if tag in {"iframe", "object", "embed"}:
            self.errors.append(f"Forbidden embedded resource element: {tag}")
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
                    self.fragments.add(value[1:])
        if tag in {"img", "link", "script"}:
            resource = values.get("src") or values.get("href") or ""
            if resource:
                self.resources.append(resource)
            if resource.startswith(("http://", "https://", "//")):
                self.errors.append(f"Remote page resource is not allowed: {resource}")
        if tag == "form" and values.get("action"):
            self.errors.append("The catalog filter form must not submit externally.")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside_script = False

    def handle_data(self, data: str) -> None:
        if self._inside_script and data.strip():
            self.errors.append("Inline script content is not allowed.")


def validate_generated_site(root: Path, entries: list[CatalogEntry], site_html: str) -> None:
    parser = GeneratedHTMLValidator()
    parser.feed(site_html)
    errors = list(parser.errors)
    required_ids = {
        "catalog",
        "catalog-controls",
        "catalog-search",
        "catalog-view-category",
        "catalog-view-industry",
        "catalog-category",
        "catalog-industry",
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
    }
    missing_labels = required_labels - parser.labels_for
    if missing_labels:
        errors.append(
            "Missing explicit control labels: " + ", ".join(sorted(missing_labels))
        )
    if parser.scripts != [{"type": "module", "src": "catalog.mjs"}]:
        errors.append("Expected exactly one local module script: catalog.mjs.")
    expected_resources = ["styles.css", "assets/nvidia-logo.png", "catalog.mjs"]
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
            "data-collections": " ".join(entry.collections),
        }
        for entry in entries
    ]
    actual_cards = [
        {key: card.get(key, "") for key in expected_cards[0]}
        for card in parser.cards
    ] if expected_cards else []
    if actual_cards != expected_cards:
        errors.append("Generated card metadata or order does not match the manifest.")
    for entry, card in zip(entries, parser.cards):
        if card.get("id") != entry.id:
            errors.append(f"Generated card ID does not match {entry.title}.")
        if card.get("aria-labelledby") != f"{entry.id}-title":
            errors.append(f"Generated card label does not match {entry.title}.")
    for category in CATEGORIES:
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

    required_links = {
        "catalog.json",
        "https://github.com/NVIDIA/nemoclaw-community/blob/main/CONTRIBUTING.md#add-a-new-example",
        "https://github.com/NVIDIA/nemoclaw-community/blob/main/SUPPORT.md",
        "https://github.com/NVIDIA/nemoclaw-community/blob/main/SECURITY.md",
    }
    missing_links = required_links - parser.links
    if missing_links:
        errors.append("Missing required catalog links: " + ", ".join(sorted(missing_links)))
    if "NemoClaw Community support is best-effort" not in site_html:
        errors.append("The catalog support boundary no longer matches SUPPORT.md.")

    for relative in ("site/styles.css", "site/catalog.mjs", "site/assets/nvidia-logo.png"):
        if not (root / relative).is_file():
            errors.append(f"Missing required site source: {relative}")
    css = (root / "site" / "styles.css").read_text(encoding="utf-8")
    if re.search(r"@import\b", css, flags=re.IGNORECASE):
        errors.append("CSS @import is not allowed.")
    if re.search(r"url\(\s*['\"]?(?:https?:)?//", css, flags=re.IGNORECASE):
        errors.append("Remote CSS resources are not allowed.")
    root_readme = (root / "README.md").read_text(encoding="utf-8")
    if "https://nvidia.github.io/nemoclaw-community/" not in root_readme:
        errors.append("README.md must include the published catalog URL.")
    if errors:
        raise CatalogError("\n".join(errors))


def expected_outputs(root: Path) -> tuple[list[CatalogEntry], str, str, str]:
    entries = load_catalog(root)
    template_path = root / "site" / "index.template.html"
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CatalogError(f"Unable to read site template: {error}") from error
    rendered_readme = render_readme(entries)
    rendered_site = render_site(entries, template)
    rendered_json = json.dumps(public_catalog(entries), indent=2, ensure_ascii=False) + "\n"
    validate_generated_site(root, entries, rendered_site)
    return entries, rendered_readme, rendered_site, rendered_json


def check_catalog(root: Path) -> list[CatalogEntry]:
    entries, expected_readme, _, _ = expected_outputs(root)
    readme_path = root / "examples" / "README.md"
    actual_readme = readme_path.read_text(encoding="utf-8")
    if actual_readme != expected_readme:
        raise CatalogError(
            "examples/README.md is out of date. Run "
            "`python3 scripts/build_catalog.py --write`."
        )
    return entries


def write_readme(root: Path, content: str) -> None:
    (root / "examples" / "README.md").write_text(content, encoding="utf-8")


def build_site(root: Path, output: Path, site_html: str, catalog_json: str) -> None:
    output = output.absolute()
    expected_output = root.resolve() / "_site"
    if output != expected_output:
        raise CatalogError("Catalog output is restricted to the generated _site directory.")
    if output.is_symlink():
        raise CatalogError("Refusing to replace a symlinked _site directory.")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    (output / "index.html").write_text(site_html, encoding="utf-8")
    (output / "catalog.json").write_text(catalog_json, encoding="utf-8")
    shutil.copy2(root / "site" / "styles.css", output / "styles.css")
    shutil.copy2(root / "site" / "catalog.mjs", output / "catalog.mjs")
    shutil.copytree(root / "site" / "assets", output / "assets")


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists() or (candidate / ".git").is_file():
            return candidate
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Validate without writing files.")
    mode.add_argument(
        "--write",
        action="store_true",
        help="Regenerate examples/README.md and build the site.",
    )
    args = parser.parse_args(argv)
    root = find_repo_root()
    output = root / "_site"

    try:
        entries, readme, site_html, catalog_json = expected_outputs(root)
        if args.check:
            actual_readme = (root / "examples" / "README.md").read_text(
                encoding="utf-8"
            )
            if actual_readme != readme:
                raise CatalogError(
                    "examples/README.md is out of date. Run "
                    "`python3 scripts/build_catalog.py --write`."
                )
            print(
                f"Catalog metadata and generated sources are valid: "
                f"{len(entries)} examples across {len(CATEGORIES)} categories."
            )
            return 0
        if args.write:
            write_readme(root, readme)
        else:
            actual_readme = (root / "examples" / "README.md").read_text(
                encoding="utf-8"
            )
            if actual_readme != readme:
                raise CatalogError(
                    "examples/README.md is out of date. Run with --write first."
                )
        build_site(root, output, site_html, catalog_json)
        print(f"Built {len(entries)} catalog entries in {output.relative_to(root)}.")
        return 0
    except (CatalogError, OSError) as error:
        print(f"Catalog build failed:\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
