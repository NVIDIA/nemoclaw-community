# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render catalog indexes, navigation, JSON records, and agent guidance."""

from __future__ import annotations

import html
import posixpath
import re
from pathlib import PurePosixPath
from typing import Any, Iterable

from .model import (
    CATEGORY_DEFINITIONS,
    COLLECTION_DEFINITIONS,
    FEATURED_TUTORIAL_URL,
    INDUSTRIES,
    INDUSTRY_EMOJIS,
    PAGES_BASE_URL,
    CatalogEntry,
    CatalogError,
    Category,
    Collection,
    slugify,
)
from .sources import EXAMPLES_HEADING


def _markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def group_entries(
    entries: Iterable[CatalogEntry],
    categories: Iterable[Category],
) -> dict[str, list[CatalogEntry]]:
    grouped = {category.id: [] for category in categories}
    for entry in entries:
        grouped[entry.category.id].append(entry)
    return grouped


def entries_for_collection(
    entries: Iterable[CatalogEntry],
    collection: Collection,
) -> list[CatalogEntry]:
    return [
        entry for entry in entries if collection.id in entry.collection_ids
    ]


def _render_markdown_entries(
    entries: list[CatalogEntry],
    relative_to: PurePosixPath,
    *,
    show_category: bool = False,
    show_contributor: bool = False,
) -> list[str]:
    if not entries:
        return ["_No examples are currently in this group._"]
    headers = ["Example"]
    if show_category:
        headers.append("Category")
    if show_contributor:
        headers.append("Contributor")
    headers.extend(("Industry", "Description"))
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for entry in entries:
        relative_readme = posixpath.relpath(entry.readme_path, relative_to.as_posix())
        cells = [f"[{_markdown_cell(entry.title)}]({relative_readme})"]
        if show_category:
            cells.append(_markdown_cell(entry.category.title))
        if show_contributor:
            cells.append(_markdown_cell(entry.contributor or ""))
        cells.extend(
            (
                _markdown_cell(entry.industry_label),
                _markdown_cell(entry.description),
            )
        )
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_discovery_readmes(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> dict[str, str]:
    """Render the generated membership list in every browse-group README."""

    grouped = group_entries(entries, categories)
    rendered: dict[str, str] = {}
    groups: tuple[Category | Collection, ...] = (*categories, *collections)
    for group in groups:
        if isinstance(group, Category):
            members = grouped[group.id]
            show_category = False
            show_contributor = group.id == "partner-recipes"
        else:
            members = entries_for_collection(entries, group)
            show_category = True
            show_contributor = False
        lines = [
            "<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->",
            "<!-- SPDX-License-Identifier: Apache-2.0 -->",
            "",
            f"# {group.title}",
            "",
            group.description,
            "",
            EXAMPLES_HEADING,
            "",
            *_render_markdown_entries(
                members,
                PurePosixPath(group.readme_path).parent,
                show_category=show_category,
                show_contributor=show_contributor,
            ),
            "",
        ]
        rendered[group.readme_path] = "\n".join(lines)
    return rendered


def render_readme(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> str:
    """Render the human-readable source catalog from canonical metadata."""

    grouped = group_entries(entries, categories)
    lines = [
        "<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->",
        "<!-- SPDX-License-Identifier: Apache-2.0 -->",
        "",
        "# NemoClaw Community Example Catalog",
        "",
        "Examples are organized first by artifact type. Reusable recipes are organized",
        "again by contributor provenance. Industry is an independent discovery field.",
        "This file is generated from the catalog metadata table in each",
        "example README. Edit that README, then run",
        "`python3 scripts/build_catalog.py --write` from the repository root.",
        "",
    ]
    for category in categories:
        category_entries = grouped[category.id]
        category_link = posixpath.relpath(category.readme_path, "examples")
        lines.extend(
            (
                f"## [{category.title}]({category_link})",
                "",
                category.description,
                "",
                *_render_markdown_entries(
                    category_entries,
                    PurePosixPath("examples"),
                    show_contributor=category.id == "partner-recipes",
                ),
                "",
            )
        )

    lines.extend(("## Collections", ""))
    for collection in collections:
        collection_link = posixpath.relpath(collection.readme_path, "examples")
        lines.extend(
            (
                f"### [{collection.title}]({collection_link})",
                "",
                collection.description,
                "",
                *_render_markdown_entries(
                    entries_for_collection(entries, collection),
                    PurePosixPath("examples"),
                    show_category=True,
                ),
                "",
            )
        )

    lines.extend(
        (
            "## Contributing An Example",
            "",
            "Read [CONTRIBUTING.md](../CONTRIBUTING.md) and the canonical",
            "[example taxonomy and naming policy](../.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md).",
            "Runnable examples must remain independently deployable and must document their",
            "prerequisites, credentials, policies, startup behavior, verification, and",
            "teardown behavior. Documentation-only tutorials keep their canonical content",
            "in a root `tutorial.md` beside `README.md`. Add structured catalog metadata as",
            "described in the",
            "[contributor guide](../CONTRIBUTING.md#catalog-metadata).",
            "",
        )
    )
    return "\n".join(lines)


def _plural(count: int, noun: str = "example") -> str:
    return f"{count} {noun if count == 1 else noun + 's'}"


def _render_category_tile(
    browse_id: str,
    title: str,
    description: str,
    count: int,
    *,
    is_collection: bool,
) -> str:
    tile_classes = "category-tile"
    if is_collection:
        tile_classes += " category-tile-collection"
    collection_label = "\n      <small>Collection</small>" if is_collection else ""
    info_id = f"{browse_id}-description"
    return f'''<div class="{tile_classes}" data-empty="{str(count == 0).lower()}">
  <a class="category-tile-link" href="?category={browse_id}#catalog">
    <span class="category-name">{html.escape(title)}{collection_label}</span>
    <span class="category-count">{_plural(count)} <span aria-hidden="true">→</span></span>
  </a>
  <div class="category-info" data-category-info>
    <button type="button" aria-label="About {html.escape(title, quote=True)}" aria-controls="{info_id}" aria-expanded="false"><span aria-hidden="true">i</span></button>
    <p id="{info_id}" role="tooltip">{html.escape(description)}</p>
  </div>
</div>'''


def render_category_nav(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> str:
    grouped = group_entries(entries, categories)
    tiles = []
    for category in categories:
        if not category.browse:
            continue
        count = len(grouped[category.id])
        tiles.append(
            _render_category_tile(
                category.id,
                category.title,
                category.description,
                count,
                is_collection=False,
            )
        )
    for collection in collections:
        tiles.append(
            _render_category_tile(
                collection.browse_id,
                collection.title,
                collection.description,
                len(entries_for_collection(entries, collection)),
                is_collection=collection.id != "build-a-claw",
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
                f'  <span>{html.escape(INDUSTRY_EMOJIS[industry])} '
                f'{html.escape(industry).replace("/", "/<wbr>")}</span>',
                f'  <span class="industry-tile-count" aria-label="{_plural(counts[industry])}">'
                f'{counts[industry]}</span>',
                "</a>",
            )
        )
        for industry in INDUSTRIES
    )


def category_filter_options(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> str:
    grouped = group_entries(entries, categories)
    recipe_categories = tuple(
        category
        for category in categories
        if category.kind == "recipe" and category.browse
    )
    other_categories = tuple(
        category
        for category in categories
        if category.kind != "recipe" and category.browse
    )
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
    collection_options = "\n".join(
        f'<option value="{collection.browse_id}">{html.escape(collection.title)} '
        f'({len(entries_for_collection(entries, collection))})</option>'
        for collection in collections
    )
    return "\n".join(
        (
            f'<option value="all">All examples ({len(entries)})</option>',
            '<optgroup label="Recipes by source">',
            indent(recipe_options, 2),
            "</optgroup>",
            '<optgroup label="Collections">',
            indent(collection_options, 2),
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
        f'<option value="{slugify(industry)}">{html.escape(INDUSTRY_EMOJIS[industry])} '
        f'{html.escape(industry)} ({counts[industry]})</option>'
        for industry in INDUSTRIES
    )
    return "\n".join(options)


def render_card(entry: CatalogEntry) -> str:
    collections = " ".join(entry.collection_ids)
    maintenance_id = entry.maintenance.id if entry.maintenance else "current"
    collection_tags = "".join(
        f'<li class="tag tag-collection">{html.escape(collection.metadata_value)}</li>'
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
  data-maintenance="{maintenance_id}"
  data-search="{html.escape(entry.search_text, quote=True)}"
  tabindex="-1"
>
  <p class="provenance">{html.escape(entry.display_label)}</p>
  <h3 id="{entry.id}-title"><a class="example-title-link" href="{entry.detail_url}">{html.escape(entry.title)}</a></h3>
  <p class="outcome">{html.escape(entry.description)}</p>
  <ul class="card-tags" aria-label="Discovery fields">
    <li class="tag">{html.escape(entry.industry_label)}</li>{collection_tags}
  </ul>
  <dl class="requirements">
    <div><dt>Requirements &amp; limits</dt><dd>{html.escape(entry.requirements)}</dd></div>
  </dl>
  <div class="card-footer">
    <a class="card-action" href="{entry.detail_url}">View example<span class="sr-only">: {html.escape(entry.title)}</span>&nbsp;<span aria-hidden="true">→</span></a>
  </div>
</article>'''


def render_catalog_groups(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> str:
    grouped = group_entries(entries, categories)
    sections = []
    for category in categories:
        presentation: Category | Collection = next(
            (
                collection
                for collection in collections
                if category.id in collection.automatic_category_ids
            ),
            category,
        )
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
      <h2 id="{category.id}-title">{html.escape(presentation.title)}</h2>
      <p>{html.escape(presentation.description)}</p>
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


def render_site(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
    template: str,
) -> str:
    represented_industries = len({entry.industry for entry in entries})
    replacements = {
        "{{EXAMPLE_COUNT}}": str(len(entries)),
        "{{INDUSTRY_COUNT}}": str(len(INDUSTRIES)),
        "{{REPRESENTED_INDUSTRY_COUNT}}": str(represented_industries),
        "{{BROWSE_GROUP_COUNT}}": str(
            sum(category.browse for category in categories) + len(collections)
        ),
        "{{TUTORIAL_URL}}": FEATURED_TUTORIAL_URL,
        "{{CATEGORY_NAV}}": indent(
            render_category_nav(entries, categories, collections), 14
        ),
        "{{INDUSTRY_NAV}}": indent(render_industry_nav(entries), 14),
        "{{CATEGORY_OPTIONS}}": indent(
            category_filter_options(entries, categories, collections), 18
        ),
        "{{INDUSTRY_OPTIONS}}": indent(industry_filter_options(entries), 18),
        "{{CATALOG_GROUPS}}": indent(
            render_catalog_groups(entries, categories, collections), 8
        ),
    }
    rendered = template
    for marker, value in replacements.items():
        count = rendered.count(marker)
        expected_count = 2 if marker in {
            "{{EXAMPLE_COUNT}}",
            "{{TUTORIAL_URL}}",
        } else 1
        if count != expected_count:
            raise CatalogError(
                f"Expected {expected_count} {marker} marker(s) in "
                "site/templates/index.html."
            )
        rendered = rendered.replace(marker, value)
    leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)
    if leftover:
        raise CatalogError("Unknown template markers: " + ", ".join(sorted(leftover)))
    return rendered


def public_catalog(
    entries: list[CatalogEntry],
    categories: tuple[Category, ...],
    collections: tuple[Collection, ...],
) -> dict[str, Any]:
    grouped = group_entries(entries, categories)
    industry_counts = {industry: 0 for industry in INDUSTRIES}
    for entry in entries:
        industry_counts[entry.industry] += 1
    return {
        "schema_version": 4,
        "source": "https://github.com/NVIDIA/nemoclaw-community/tree/main/examples",
        "categories": [
            {
                "id": category.id,
                "label": category.title,
                "description": category.description,
                "kind": category.kind,
                "provenance": category.provenance,
                "count": len(grouped[category.id]),
                "source_path": category.readme_path,
            }
            for category in categories
        ],
        "industries": [
            {
                "id": slugify(industry),
                "label": industry,
                "emoji": INDUSTRY_EMOJIS[industry],
                "count": industry_counts[industry],
            }
            for industry in INDUSTRIES
        ],
        "collections": [
            {
                "id": collection.id,
                "browse_id": collection.browse_id,
                "label": collection.title,
                "description": collection.description,
                "count": len(entries_for_collection(entries, collection)),
                "source_path": collection.readme_path,
            }
            for collection in collections
        ],
        "examples": [
            {
                "id": entry.id,
                "title": entry.title,
                "description": entry.description,
                "industry": {
                    "id": entry.industry_id,
                    "label": entry.industry,
                    "emoji": entry.industry_emoji,
                },
                "kind": entry.category.kind,
                "provenance": entry.category.provenance,
                "category": {
                    "id": entry.category.id,
                    "label": entry.category.title,
                },
                "contributor": entry.contributor,
                "collections": list(entry.collection_ids),
                "requirements": entry.requirements,
                "lifecycle": entry.lifecycle,
                "reviewed": entry.reviewed.isoformat() if entry.reviewed else None,
                "last_activity": (
                    entry.last_activity.isoformat() if entry.last_activity else None
                ),
                "stack": entry.stack.as_dict() if entry.stack else None,
                "maintenance": (
                    entry.maintenance.to_dict() if entry.maintenance else None
                ),
                "upstream_url": entry.upstream_url,
                "source_path": entry.readme_path,
                "guide_url": entry.guide_url,
                "detail_url": entry.detail_url,
            }
            for entry in entries
        ],
    }
def render_llms(entries: list[CatalogEntry]) -> str:
    """Render a concise website-navigation index for language-model clients."""

    lines = [
        "# NemoClaw Community",
        "",
        "> A catalog of constrained, inspectable agent recipes, field demos, and developer tools built with NemoClaw.",
        "",
        "Use the industry and category fields below to select an example. Requirements are short summaries; read the linked source guide before running an example.",
        "",
        "## Catalog data",
        "",
        f"- [Browse the catalog]({PAGES_BASE_URL})",
        f"- [Machine-readable catalog]({PAGES_BASE_URL}catalog.json)",
        "",
        "## Examples",
        "",
    ]
    for entry in entries:
        lines.extend(
            (
                f"- [{entry.title}]({entry.absolute_detail_url})",
                f"  - Description: {entry.description}",
                f"  - Category: {entry.category.title}",
                f"  - Industry: {entry.industry_label}",
                f"  - Requirements: {entry.requirements}",
                f"  - Lifecycle: {entry.lifecycle}",
                f"  - Source: [README]({entry.guide_url})",
            )
        )
        if entry.stack:
            nemoclaw_version = (
                entry.stack.nemoclaw.version
                or (
                    "N/A"
                    if entry.stack.nemoclaw.status == "not-applicable"
                    else "Unknown"
                )
            )
            harness_na = entry.stack.harness.status == "not-applicable"
            harness_name = entry.stack.harness.name or (
                "N/A" if harness_na else "Unknown"
            )
            harness_version = (
                entry.stack.harness.version
                or ("N/A" if harness_na else "Unknown")
            )
            openshell_version = (
                entry.stack.openshell.version
                or (
                    "N/A"
                    if entry.stack.openshell.status == "not-applicable"
                    else "Unknown"
                )
            )
            lines.extend(
                (
                    f"  - NemoClaw version: {nemoclaw_version}",
                    f"  - Harness: {harness_name}",
                    f"  - Harness version: {harness_version}",
                    f"  - OpenShell version: {openshell_version}",
                    f"  - Stack verification: {entry.stack.status}",
                )
            )
        if entry.maintenance:
            lines.append(f"  - Maintenance: {entry.maintenance.label}")
        if entry.collections:
            lines.append(
                "  - Collections: "
                + ", ".join(collection.title for collection in entry.collections)
            )
        if entry.upstream_url:
            lines.append(f"  - Upstream: [Project](<{entry.upstream_url}>)")
    lines.append("")
    return "\n".join(lines)


def taxonomy_contract() -> dict[str, Any]:
    """Return stable browser identifiers for cross-language contract tests."""

    return {
        "categories": [
            "all",
            *(
                category.id
                for category in CATEGORY_DEFINITIONS
                if category.browse
            ),
            *(collection.browse_id for collection in COLLECTION_DEFINITIONS),
        ],
        "collection_categories": {
            collection.browse_id: collection.id
            for collection in COLLECTION_DEFINITIONS
        },
        "industries": ["all", *(slugify(industry) for industry in INDUSTRIES)],
        "maintenance": [
            "maintained",
            "all",
            "current",
            "review-soon",
            "review-due",
            "review-overdue",
            "review-critical",
            "deprecated",
        ],
    }
