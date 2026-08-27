#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate catalog metadata and build the static GitHub Pages catalog."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import posixpath
import re
import shutil
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

try:
    import markdown
except ModuleNotFoundError:  # Report a targeted build error when dependencies are absent.
    markdown = None


INDUSTRIES: tuple[str, ...] = (
    "Academia/Education",
    "AEC",
    "Aerospace",
    "Agriculture",
    "Automotive/Transportation",
    "Cloud Services",
    "Consumer Internet",
    "Energy",
    "Financial Services",
    "Gaming",
    "Hardware/Semiconductor",
    "Health and Life Sciences",
    "HPC/Scientific Computing",
    "Manufacturing",
    "Media & Entertainment",
    "Public Sector",
    "Restaurant/Quick Service",
    "Retail/Consumer Packaged Goods",
    "Smart Cities/Spaces",
    "Telecommunications",
    "Other",
)

COLLECTIONS: tuple[str, ...] = ("hackathon",)
PATH_SEGMENT_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
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
    requirements: str
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
    def detail_path(self) -> str:
        return f"examples/{self.path}/index.html"

    @property
    def detail_url(self) -> str:
        return f"examples/{self.path}/"

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
            self.requirements,
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
    if manifest.get("schema_version") != 2:
        raise CatalogError("Unsupported catalog schema_version; expected 2.")
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
        "requirements",
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
        requirements = _required_string(record, "requirements", index)
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
            requirements=requirements,
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
                    f'<a class="category-tile" href="?category={category.id}#catalog">',
                    f'  <span class="category-name">{html.escape(category.title)}</span>',
                    f'  <span class="category-count">{_plural(count)} <span aria-hidden="true">→</span></span>',
                    "</a>",
                )
            )
        )
    hackathon_count = sum("hackathon" in entry.collections for entry in entries)
    tiles.append(
        "\n".join(
            (
                '<a class="category-tile category-tile-collection" '
                'href="?category=hackathon-recipes#catalog">',
                '  <span class="category-name">Hackathon Recipes '
                '<small>Collection</small></span>',
                f'  <span class="category-count">{_plural(hackathon_count)} '
                '<span aria-hidden="true">→</span></span>',
                "</a>",
            )
        )
    )
    return "\n".join(tiles)


def render_industry_nav(entries: list[CatalogEntry]) -> str:
    counts = {industry: 0 for industry in INDUSTRIES}
    for entry in entries:
        counts[entry.industry] += 1
    return "\n".join(
        "\n".join(
            (
                f'<a class="industry-tile" data-empty="{str(counts[industry] == 0).lower()}" '
                f'href="?view=industry&amp;industry={slugify(industry)}#catalog">',
                f'  <span>{html.escape(industry)}</span>',
                f'  <span class="industry-tile-count" aria-label="{_plural(counts[industry])}">'
                f'{counts[industry]}</span>',
                "</a>",
            )
        )
        for industry in INDUSTRIES
    )


def category_filter_options(entries: list[CatalogEntry]) -> str:
    grouped = group_entries(entries)
    recipe_categories = CATEGORIES[:3]
    other_categories = CATEGORIES[3:]
    recipe_options = "\n".join(
        f'<option value="{category.id}">{html.escape(category.title)} '
        f'({len(grouped[category.id])})</option>'
        for category in recipe_categories
    )
    other_options = "\n".join(
        f'<option value="{category.id}">{html.escape(category.title)} '
        f'({len(grouped[category.id])})</option>'
        for category in other_categories
    )
    hackathon_count = sum("hackathon" in entry.collections for entry in entries)
    return "\n".join(
        (
            f'<option value="all">All examples ({len(entries)})</option>',
            '<optgroup label="Recipes by source">',
            indent(recipe_options, 2),
            "</optgroup>",
            '<optgroup label="Collections">',
            f'  <option value="hackathon-recipes">Hackathon recipes ({hackathon_count})</option>',
            "</optgroup>",
            '<optgroup label="Other example formats">',
            indent(other_options, 2),
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
  <h3 id="{entry.id}-title"><a class="example-title-link" href="{entry.detail_url}">{html.escape(entry.title)}</a></h3>
  <p class="outcome">{html.escape(entry.description)}</p>
  <ul class="card-tags" aria-label="Discovery fields">
    <li class="tag">{html.escape(entry.industry)}</li>{collection_tags}
  </ul>
  <dl class="requirements">
    <div><dt>Requirements &amp; limits</dt><dd>{html.escape(entry.requirements)}</dd></div>
  </dl>
  <div class="card-footer">
    <a class="card-action" href="{entry.detail_url}">View example<span class="sr-only">: {html.escape(entry.title)}</span>&nbsp;<span aria-hidden="true">→</span></a>
  </div>
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
        "{{CATEGORY_COUNT}}": str(len(CATEGORIES)),
        "{{CATEGORY_NAV}}": indent(render_category_nav(entries), 14),
        "{{INDUSTRY_NAV}}": indent(render_industry_nav(entries), 14),
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
        "schema_version": 2,
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
                "requirements": entry.requirements,
                "source_path": entry.readme_path,
                "guide_url": entry.guide_url,
                "detail_url": entry.detail_url,
            }
            for entry in entries
        ],
    }


def github_heading_slug(value: str, separator: str) -> str:
    """Approximate GitHub's stable heading IDs for README fragment links."""

    normalized = html.unescape(value).strip().casefold()
    normalized = re.sub(r"[^\w\- ]", "", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", separator, normalized).strip(separator)


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


def _readme_title_and_body(content: str, readme_path: str) -> tuple[str, str]:
    lines = content.splitlines()
    title_index = next(
        (index for index, line in enumerate(lines) if re.fullmatch(r"#\s+\S.*", line)),
        None,
    )
    if title_index is None:
        raise CatalogError(f"Example README has no level-one title: {readme_path}")
    source_title = lines[title_index][2:].strip()
    plain_title = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", source_title)
    plain_title = re.sub(r"[`*_~]", "", plain_title).strip()
    if not plain_title:
        raise CatalogError(f"Example README has an empty title: {readme_path}")
    del lines[title_index]
    return plain_title, "\n".join(lines).strip()


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
        "img",
        "li",
        "ol",
        "p",
        "pre",
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
        self.catalog_by_readme = catalog_by_readme
        self.copied_assets = copied_assets
        self.output: list[str] = []
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.fragments: set[str] = set()
        self._open_tags: list[str] = []
        self._source_dir = PurePosixPath(entry.readme_path).parent.as_posix()
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
        if target == self.entry.readme_path:
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
        if not target_path.is_file() or target_path.is_symlink():
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
        elif tag == "div":
            if values.get("class") == "toc":
                safe.append(("class", "toc"))
            else:
                self.errors.append("Only the generated README toc div is allowed.")

        allowed_names = {name for name, _ in safe}
        ignored_generated = {"class"} if tag == "div" else set()
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
        if tag not in self.ALLOWED_TAGS:
            self.errors.append(f"Unsupported README HTML element: {tag}")
            return
        if tag == "img":
            values = {name: value or "" for name, value in attrs}
            source = values.get("src", "")
            source_parts = urlsplit(source)
            if source_parts.scheme or source_parts.netloc:
                alt = values.get("alt", "").strip()
                if source_parts.scheme != "https" or source_parts.netloc == "":
                    self.errors.append(f"Remote README image must use HTTPS: {source}")
                    return
                if not alt:
                    self.errors.append("Remote README image is missing meaningful alt text.")
                    return
                self.output.append(
                    '<a class="readme-image-link" href="'
                    f'{html.escape(source, quote=True)}">View image: '
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
    source = (root / entry.readme_path).read_text(encoding="utf-8")
    mermaid_sources = extract_mermaid_sources(source, entry.readme_path)
    readme_title, body = _readme_title_and_body(source, entry.readme_path)
    from markdown.extensions.tables import TableExtension

    renderer = markdown.Markdown(
        extensions=[
            "fenced_code",
            TableExtension(use_align_attribute=True),
            "sane_lists",
            "toc",
        ],
        extension_configs={
            "toc": {
                "slugify": github_heading_slug,
                "toc_depth": "2-3",
            }
        },
        output_format="html5",
    )
    rendered_body = renderer.convert(body)
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
                f"Generated README toc has unresolved fragments for {entry.readme_path}: "
                + ", ".join(sorted(unresolved_toc))
            )
    else:
        safe_toc = '<p class="toc-empty">This short guide has no subsections.</p>'
    unresolved_fragments = body_sanitizer.fragments - body_sanitizer.ids
    if unresolved_fragments:
        raise CatalogError(
            f"README has unresolved local fragments for {entry.readme_path}: "
            + ", ".join(sorted(unresolved_fragments))
        )
    rendered_mermaid_count = safe_body.count('class="language-mermaid"')
    if rendered_mermaid_count != len(mermaid_sources):
        raise CatalogError(
            f"Mermaid source/render count mismatch for {entry.readme_path}."
        )
    return readme_title, safe_body, safe_toc, bool(mermaid_sources)


def _detail_relative(entry: CatalogEntry, target: str) -> str:
    detail_dir = PurePosixPath(entry.detail_path).parent.as_posix()
    return posixpath.relpath(target, detail_dir)


def render_detail_pages(
    root: Path,
    entries: list[CatalogEntry],
    template: str,
) -> tuple[dict[str, str], set[str]]:
    """Render one static, themed README page per catalog entry."""

    catalog_by_readme = {entry.readme_path: entry for entry in entries}
    copied_assets: set[str] = set()
    pages: dict[str, str] = {}
    for entry in entries:
        readme_title, readme_html, toc_html, has_mermaid = render_readme_html(
            root, entry, catalog_by_readme, copied_assets
        )
        collection_tags = "".join(
            f'\n              <li class="tag tag-collection">'
            f'{html.escape(collection.title())}</li>'
            for collection in entry.collections
        )
        if entry.contributor:
            attribution_fact = (
                f"<div><dt>Contributor</dt><dd>{html.escape(entry.contributor)}</dd></div>"
            )
        elif entry.environment:
            attribution_fact = (
                f"<div><dt>Environment</dt><dd>{html.escape(entry.environment)}</dd></div>"
            )
        else:
            attribution_fact = ""
        diagram_scripts = ""
        if has_mermaid:
            mermaid_url = _detail_relative(
                entry, "assets/vendor/mermaid.tiny.js"
            )
            diagrams_url = _detail_relative(entry, "diagrams.mjs")
            diagram_scripts = (
                f'    <script src="{mermaid_url}" integrity="{MERMAID_SRI}"></script>\n'
                f'    <script type="module" src="{diagrams_url}"></script>'
            )
        replacements = {
            "{{META_DESCRIPTION}}": html.escape(entry.description, quote=True),
            "{{PAGE_TITLE}}": html.escape(readme_title),
            "{{STYLES_URL}}": _detail_relative(entry, "styles.css"),
            "{{LOGO_URL}}": _detail_relative(entry, "assets/nvidia-logo.png"),
            "{{CATALOG_URL}}": _detail_relative(entry, "index.html"),
            "{{SOURCE_URL}}": html.escape(entry.guide_url, quote=True),
            "{{DISPLAY_LABEL}}": html.escape(entry.display_label),
            "{{DESCRIPTION}}": html.escape(entry.description),
            "{{INDUSTRY}}": html.escape(entry.industry),
            "{{COLLECTION_TAGS}}": collection_tags,
            "{{CATEGORY}}": html.escape(entry.category.title),
            "{{ATTRIBUTION_FACT}}": attribution_fact,
            "{{REQUIREMENTS}}": html.escape(entry.requirements),
            "{{TABLE_OF_CONTENTS}}": toc_html,
            "{{README_HTML}}": indent(readme_html, 12),
            "{{DIAGRAM_SCRIPTS}}": diagram_scripts,
        }
        rendered = template
        for marker, value in replacements.items():
            expected_counts = {
                "{{CATALOG_URL}}": 3,
                "{{INDUSTRY}}": 2,
                "{{PAGE_TITLE}}": 2,
                "{{SOURCE_URL}}": 2,
                "{{TABLE_OF_CONTENTS}}": 2,
            }
            expected_count = expected_counts.get(marker, 1)
            if rendered.count(marker) != expected_count:
                raise CatalogError(
                    f"Expected {expected_count} {marker} marker(s) in "
                    "site/detail.template.html."
                )
            rendered = rendered.replace(marker, value)
        leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)
        if leftover:
            raise CatalogError(
                "Unknown detail template markers: " + ", ".join(sorted(leftover))
            )
        pages[entry.detail_path] = rendered
    return pages, copied_assets


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
                    self.fragments.add(unquote(value[1:]))
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
        parser = GeneratedHTMLValidator()
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
        if has_mermaid:
            expected_scripts = [
                {
                    "src": _detail_relative(
                        entry, "assets/vendor/mermaid.tiny.js"
                    ),
                    "integrity": MERMAID_SRI,
                },
                {
                    "type": "module",
                    "src": _detail_relative(entry, "diagrams.mjs"),
                },
            ]
            if parser.scripts != expected_scripts:
                errors.append(
                    "Mermaid detail pages must contain only the pinned local "
                    "runtime and diagram module."
                )
            for script in expected_scripts:
                if script["src"] not in parser.resources:
                    errors.append(
                        f"Mermaid detail page is missing {script['src']}."
                    )
        elif parser.scripts:
            errors.append("Detail pages without Mermaid must not contain scripts.")
        if parser.content_security_policies != [DETAIL_CONTENT_SECURITY_POLICY]:
            errors.append("Detail page Content Security Policy changed unexpectedly.")
        expected_styles = _detail_relative(entry, "styles.css")
        expected_logo = _detail_relative(entry, "assets/nvidia-logo.png")
        if expected_styles not in parser.resources:
            errors.append("Detail page is missing the shared stylesheet.")
        if expected_logo not in parser.resources:
            errors.append("Detail page is missing the local NVIDIA logo.")
        required_links = {
            entry.guide_url,
            _detail_relative(entry, "index.html"),
            "https://github.com/NVIDIA/nemoclaw-community/blob/main/SUPPORT.md",
            "https://github.com/NVIDIA/nemoclaw-community/blob/main/SECURITY.md",
        }
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
            "site/diagrams.mjs",
            "site/assets/vendor/mermaid-LICENSE.txt",
        ):
            if not (root / relative).is_file():
                raise CatalogError(f"Missing required diagram source: {relative}")


def verified_mermaid_asset(root: Path) -> Path:
    """Return the pinned Mermaid bundle only when its local cache is trustworthy."""

    asset = root / MERMAID_CACHE_PATH
    if (
        not asset.is_file()
        or asset.is_symlink()
        or not asset.resolve().is_relative_to(root.resolve())
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


def expected_outputs(
    root: Path,
) -> tuple[
    list[CatalogEntry],
    str,
    str,
    str,
    dict[str, str],
    set[str],
]:
    entries = load_catalog(root)
    template_path = root / "site" / "index.template.html"
    detail_template_path = root / "site" / "detail.template.html"
    try:
        template = template_path.read_text(encoding="utf-8")
        detail_template = detail_template_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CatalogError(f"Unable to read site templates: {error}") from error
    rendered_readme = render_readme(entries)
    rendered_site = render_site(entries, template)
    rendered_json = json.dumps(public_catalog(entries), indent=2, ensure_ascii=False) + "\n"
    detail_pages, copied_assets = render_detail_pages(root, entries, detail_template)
    validate_generated_site(root, entries, rendered_site)
    validate_detail_pages(root, entries, detail_pages)
    if any('class="language-mermaid"' in page for page in detail_pages.values()):
        verified_mermaid_asset(root)
    return (
        entries,
        rendered_readme,
        rendered_site,
        rendered_json,
        detail_pages,
        copied_assets,
    )


def check_catalog(root: Path) -> list[CatalogEntry]:
    entries, expected_readme, _, _, _, _ = expected_outputs(root)
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


def build_site(
    root: Path,
    output: Path,
    site_html: str,
    catalog_json: str,
    detail_pages: dict[str, str] | None = None,
    copied_assets: set[str] | None = None,
) -> None:
    output = output.absolute()
    expected_output = root.resolve() / "_site"
    if output != expected_output:
        raise CatalogError("Catalog output is restricted to the generated _site directory.")
    if output.is_symlink():
        raise CatalogError("Refusing to replace a symlinked _site directory.")
    has_mermaid = any(
        'class="language-mermaid"' in page
        for page in (detail_pages or {}).values()
    )
    mermaid_asset: Path | None = None
    diagram_module: Path | None = None
    if has_mermaid:
        mermaid_asset = verified_mermaid_asset(root)
        diagram_module = root / "site" / "diagrams.mjs"
        if not diagram_module.is_file() or diagram_module.is_symlink():
            raise CatalogError("Refusing unsafe Mermaid diagram module.")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    (output / "index.html").write_text(site_html, encoding="utf-8")
    (output / "catalog.json").write_text(catalog_json, encoding="utf-8")
    shutil.copy2(root / "site" / "styles.css", output / "styles.css")
    shutil.copy2(root / "site" / "catalog.mjs", output / "catalog.mjs")
    shutil.copytree(root / "site" / "assets", output / "assets")
    if has_mermaid:
        assert mermaid_asset is not None
        assert diagram_module is not None
        vendor_directory = output / "assets" / "vendor"
        vendor_directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            mermaid_asset,
            vendor_directory / "mermaid.tiny.js",
        )
        shutil.copy2(diagram_module, output / "diagrams.mjs")
    for relative, content in (detail_pages or {}).items():
        destination = output / relative
        if not destination.absolute().is_relative_to(output):
            raise CatalogError(f"Detail output escapes _site: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    total_asset_size = 0
    for relative in sorted(copied_assets or set()):
        source = root / relative
        resolved_source = source.resolve()
        if (
            not resolved_source.is_relative_to(root.resolve())
            or not resolved_source.is_file()
            or source.is_symlink()
        ):
            raise CatalogError(f"Refusing unsafe README asset: {relative}")
        total_asset_size += resolved_source.stat().st_size
        if total_asset_size > 20 * 1024 * 1024:
            raise CatalogError("README assets exceed the 20 MiB catalog limit.")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved_source, destination)


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
        (
            entries,
            readme,
            site_html,
            catalog_json,
            detail_pages,
            copied_assets,
        ) = expected_outputs(root)
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
        build_site(
            root,
            output,
            site_html,
            catalog_json,
            detail_pages,
            copied_assets,
        )
        print(
            f"Built {len(entries)} catalog entries and detail pages in "
            f"{output.relative_to(root)}."
        )
        return 0
    except (CatalogError, OSError) as error:
        print(f"Catalog build failed:\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
