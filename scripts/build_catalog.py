#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate catalog metadata and build the static GitHub Pages catalog."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import posixpath
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

if __package__:
    from .catalog_maintenance import (
        LIFECYCLES,
        MaintenancePolicyError,
        MaintenanceStatus,
        compute_status,
        load_policy,
    )
    from .example_stack_facts import (
        StackDeclaration,
        StackFacts,
        extract_example_stack_facts,
        parse_stack_declaration,
    )
else:
    from catalog_maintenance import (  # type: ignore[no-redef]
        LIFECYCLES,
        MaintenancePolicyError,
        MaintenanceStatus,
        compute_status,
        load_policy,
    )
    from example_stack_facts import (  # type: ignore[no-redef]
        StackDeclaration,
        StackFacts,
        extract_example_stack_facts,
        parse_stack_declaration,
    )

try:
    import markdown
except ModuleNotFoundError:  # Report a targeted build error when dependencies are absent.
    markdown = None

try:
    import pygments
except ModuleNotFoundError:  # Tutorial code highlighting is an optional build path.
    pygments = None


INDUSTRY_EMOJIS: dict[str, str] = {
    "Academia/Education": "🎓",
    "AEC": "🏗️",
    "Aerospace": "🚀",
    "Agriculture": "🌾",
    "Automotive/Transportation": "🚗",
    "Cloud Services": "☁️",
    "Consumer Internet": "🌐",
    "Energy": "⚡",
    "Financial Services": "💳",
    "Gaming": "🎮",
    "Hardware/Semiconductor": "🖥️",
    "Health and Life Sciences": "🧬",
    "HPC/Scientific Computing": "🔬",
    "Manufacturing": "🏭",
    "Media & Entertainment": "🎬",
    "Public Sector": "🏛️",
    "Restaurant/Quick Service": "🍽️",
    "Retail/Consumer Packaged Goods": "🛍️",
    "Smart Cities/Spaces": "🏙️",
    "Telecommunications": "📡",
    "Other": "✨",
}
INDUSTRIES: tuple[str, ...] = tuple(INDUSTRY_EMOJIS)

PAGES_BASE_URL = "https://nvidia.github.io/nemoclaw-community/"
FEATURED_TUTORIAL_URL = "examples/demos/build-a-claw/tutorial/"
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
TUTORIAL_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https:; font-src 'self'; connect-src 'none'; "
    "object-src 'none'; frame-src https://www.linkedin.com https://www.youtube.com; "
    "worker-src 'none'; base-uri 'none'; form-action 'none'"
)
TUTORIAL_IFRAME_PATHS = {
    "www.linkedin.com": "/embed/",
    "www.youtube.com": "/embed/",
}


@dataclass(frozen=True)
class Category:
    """One canonical artifact/provenance category."""

    id: str
    singular: str
    kind: str
    provenance: str | None = None
    readme_path: str = ""
    title: str = ""
    description: str = ""
    browse: bool = True


CATEGORY_DEFINITIONS: tuple[Category, ...] = (
    Category(
        "nvidia-recipes",
        "NVIDIA recipe",
        "recipe",
        "nvidia",
        "examples/recipes/nvidia/README.md",
    ),
    Category(
        "partner-recipes",
        "Partner recipe",
        "recipe",
        "partner",
        "examples/recipes/partners/README.md",
    ),
    Category(
        "community-recipes",
        "Community recipe",
        "recipe",
        "community",
        "examples/recipes/community/README.md",
    ),
    Category(
        "nvidia-field-demos",
        "NVIDIA field demo",
        "demo",
        readme_path="examples/demos/field/README.md",
    ),
    Category(
        "build-a-claw-demos",
        "Build-a-Claw demo",
        "demo",
        readme_path="examples/demos/build-a-claw/README.md",
        browse=False,
    ),
    Category(
        "developer-tools",
        "Developer tool",
        "tool",
        readme_path="examples/tools/README.md",
    ),
)

CATEGORY_DEFINITION_BY_ID = {
    category.id: category for category in CATEGORY_DEFINITIONS
}


@dataclass(frozen=True)
class Collection:
    """One cross-cutting discovery collection and its browse presentation."""

    id: str
    browse_id: str
    metadata_value: str
    readme_path: str
    title: str = ""
    description: str = ""
    automatic_category_ids: tuple[str, ...] = ()


COLLECTION_DEFINITIONS: tuple[Collection, ...] = (
    Collection(
        "hackathon",
        "hackathon-recipes",
        "Hackathon",
        "examples/collections/hackathon/README.md",
    ),
    Collection(
        "build-a-claw",
        "build-a-claw",
        "Build-a-Claw",
        "examples/collections/build-a-claw/README.md",
        automatic_category_ids=("build-a-claw-demos",),
    ),
)

COLLECTION_DEFINITION_BY_VALUE = {
    collection.metadata_value: collection for collection in COLLECTION_DEFINITIONS
}


@dataclass(frozen=True)
class CatalogEntry:
    """Validated README metadata plus taxonomy derived from its path."""

    path: str
    title: str
    description: str
    industry: str
    requirements: str
    collections: tuple[Collection, ...]
    category: Category
    contributor: str | None = None
    upstream_url: str | None = None
    readme_body: str = ""
    tutorial_path: str | None = None
    lifecycle: str = "Active"
    reviewed: dt.date | None = None
    last_activity: dt.date | None = None
    stack_declaration: StackDeclaration | None = None
    stack: StackFacts | None = None
    maintenance: MaintenanceStatus | None = None

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
    def is_tutorial(self) -> bool:
        return self.tutorial_path is not None

    @property
    def content_path(self) -> str:
        return self.tutorial_path or self.readme_path

    @property
    def content_url(self) -> str:
        return (
            "https://github.com/NVIDIA/nemoclaw-community/blob/main/"
            f"{self.content_path}"
        )

    @property
    def detail_path(self) -> str:
        return f"examples/{self.path}/index.html"

    @property
    def detail_url(self) -> str:
        return f"examples/{self.path}/"

    @property
    def absolute_detail_url(self) -> str:
        return f"{PAGES_BASE_URL}{self.detail_url}"

    @property
    def id(self) -> str:
        return f"example-{slugify(self.title)}"

    @property
    def industry_id(self) -> str:
        return slugify(self.industry)

    @property
    def industry_emoji(self) -> str:
        return INDUSTRY_EMOJIS[self.industry]

    @property
    def industry_label(self) -> str:
        return f"{self.industry_emoji} {self.industry}"

    @property
    def display_label(self) -> str:
        if self.category.id == "partner-recipes":
            return f"{self.category.singular} · {self.contributor}"
        return self.category.singular

    @property
    def collection_ids(self) -> tuple[str, ...]:
        return tuple(collection.id for collection in self.collections)

    @property
    def search_text(self) -> str:
        stack_values: tuple[str, ...] = ()
        if self.stack is not None:
            stack_values = tuple(
                value
                for component in (
                    self.stack.nemoclaw,
                    self.stack.harness,
                    self.stack.openshell,
                )
                if component.status != "not-applicable"
                for value in (
                    component.name,
                    component.version,
                    component.status,
                )
                if value
            ) + (self.stack.status,)
        values = (
            self.title,
            self.description,
            self.industry,
            self.requirements,
            self.category.title,
            self.display_label,
            self.contributor or "",
            " ".join(collection.title for collection in self.collections),
            self.lifecycle,
            self.maintenance.label if self.maintenance else "",
            *stack_values,
        )
        return " ".join(value for value in values if value)


class CatalogError(ValueError):
    """Raised when source metadata or generated output is invalid."""


def slugify(value: str) -> str:
    """Return the stable lowercase URL identifier used by the catalog UI."""

    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def path_uses_symlink(root: Path, path: Path) -> bool:
    """Return whether a repository-relative path contains any symlink."""

    root_absolute = root.absolute()
    path_absolute = path.absolute()
    try:
        relative = path_absolute.relative_to(root_absolute)
    except ValueError:
        return True
    current = root_absolute
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def is_regular_repo_file(root: Path, path: Path) -> bool:
    """Return whether path is a regular file contained in root without symlinks."""

    return (
        not path_uses_symlink(root, path)
        and path.is_file()
        and path.resolve().is_relative_to(root.resolve())
    )


def classify_path(
    path: str,
    categories_by_id: dict[str, Category] | None = None,
) -> Category:
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
    elif len(parts) == 3 and parts[:2] == ("demos", "build-a-claw"):
        category_id = "build-a-claw-demos"
    elif len(parts) == 2 and parts[0] == "tools":
        category_id = "developer-tools"

    if category_id is None or any(
        PATH_SEGMENT_PATTERN.fullmatch(part) is None for part in parts
    ):
        raise CatalogError(
            f"Catalog path does not match the canonical example taxonomy: {path!r}"
        )
    return (categories_by_id or CATEGORY_DEFINITION_BY_ID)[category_id]


def discover_example_paths(
    root: Path,
    categories_by_id: dict[str, Category] | None = None,
) -> set[str]:
    """Discover canonical example directories and require one safe root README."""

    examples = root / "examples"
    if not examples.is_dir() or examples.is_symlink():
        raise CatalogError("examples/ must be a regular directory.")
    allowed_roots = {"collections", "demos", "recipes", "tools"}
    unexpected_roots = {
        child.name
        for child in examples.iterdir()
        if child.is_dir() and child.name not in allowed_roots
    }
    if unexpected_roots:
        raise CatalogError(
            "Unexpected example taxonomy directories: "
            + ", ".join(sorted(unexpected_roots))
        )

    recipes = examples / "recipes"
    if recipes.is_dir():
        allowed_recipe_roots = {"community", "nvidia", "partners"}
        unexpected_recipe_roots = {
            child.name
            for child in recipes.iterdir()
            if child.is_dir() and child.name not in allowed_recipe_roots
        }
        if unexpected_recipe_roots:
            raise CatalogError(
                "Unexpected recipe provenance directories: "
                + ", ".join(sorted(unexpected_recipe_roots))
            )

    demos = examples / "demos"
    if demos.is_dir():
        allowed_demo_roots = {"build-a-claw", "field"}
        unexpected_demo_roots = {
            child.name
            for child in demos.iterdir()
            if child.is_dir() and child.name not in allowed_demo_roots
        }
        if unexpected_demo_roots:
            raise CatalogError(
                "Unexpected demo taxonomy directories: "
                + ", ".join(sorted(unexpected_demo_roots))
            )

    collections = examples / "collections"
    if collections.is_dir():
        expected_collection_roots = {
            PurePosixPath(collection.readme_path).parent.name
            for collection in COLLECTION_DEFINITIONS
        }
        unexpected_collection_roots = {
            child.name
            for child in collections.iterdir()
            if child.is_dir() and child.name not in expected_collection_roots
        }
        if unexpected_collection_roots:
            raise CatalogError(
                "Unexpected collection directories: "
                + ", ".join(sorted(unexpected_collection_roots))
            )
        for collection_root in expected_collection_roots:
            index = collections / collection_root
            if not index.is_dir():
                continue
            unexpected_entries = sorted(
                child.name for child in index.iterdir() if child.name != "README.md"
            )
            if unexpected_entries:
                raise CatalogError(
                    "Collection directories may contain only README.md: "
                    + ", ".join(
                        f"examples/collections/{collection_root}/{name}"
                        for name in unexpected_entries
                    )
                )

    patterns = (
        "recipes/nvidia/*",
        "recipes/community/*",
        "recipes/partners/*/*",
        "demos/field/*",
        "demos/build-a-claw/*",
        "tools/*",
    )
    paths: set[str] = set()
    for pattern in patterns:
        for directory in examples.glob(pattern):
            if not directory.is_dir():
                continue
            path = directory.relative_to(examples).as_posix()
            classify_path(path, categories_by_id)
            if path_uses_symlink(examples, directory):
                raise CatalogError(
                    f"Example directory must not be a symlink: examples/{path}"
                )
            if not directory.resolve().is_relative_to(examples.resolve()):
                raise CatalogError(
                    f"Example directory resolves outside examples/: examples/{path}"
                )
            readme = directory / "README.md"
            if not is_regular_repo_file(examples, readme):
                raise CatalogError(
                    f"Example directory requires a regular README.md: examples/{path}"
                )
            paths.add(path)
    return paths


def discover_tutorial_path(root: Path, path: str, category: Category) -> str | None:
    """Return one optional top-level Markdown tutorial for a Build-a-Claw demo."""

    if category.id != "build-a-claw-demos":
        return None
    directory = root / "examples" / path
    candidates = sorted(
        (
            candidate
            for candidate in directory.iterdir()
            if candidate.name != "README.md"
            and candidate.suffix.casefold() == ".md"
        ),
        key=lambda candidate: candidate.name.casefold(),
    )
    for candidate in candidates:
        if not is_regular_repo_file(root, candidate):
            raise CatalogError(
                "Build-a-Claw tutorial source must be a regular, non-symlinked "
                f"repository file: {candidate.relative_to(root).as_posix()}"
            )
    if len(candidates) > 1:
        raise CatalogError(
            "Build-a-Claw demo may contain at most one top-level tutorial Markdown "
            f"file besides README.md: examples/{path}"
        )
    return candidates[0].relative_to(root).as_posix() if candidates else None


CATALOG_TABLE_HEADER = "| Catalog field | Value |"
CATALOG_TABLE_DIVIDER = "| --- | --- |"
CATALOG_METADATA_HEADING = "## Catalog Metadata"
CATALOG_FIELD_ORDER = (
    "Description",
    "Industry",
    "Requirements",
    "NemoClaw",
    "Harness",
    "OpenShell",
    "Lifecycle",
    "Reviewed",
    "Upstream",
    "Contributor",
    "Collection",
)
EXAMPLES_HEADING = "## Examples"


def _skip_leading_readme_comments(lines: list[str], readme_path: str) -> int:
    """Skip optional legacy YAML plus comments before the visible README title."""

    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index] == "---":
        index += 1
        while index < len(lines) and lines[index] != "---":
            index += 1
        if index >= len(lines):
            raise CatalogError(f"Unclosed leading YAML block in {readme_path}.")
        index += 1
    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines) or not lines[index].lstrip().startswith("<!--"):
            break
        while index < len(lines) and "-->" not in lines[index]:
            index += 1
        if index >= len(lines):
            raise CatalogError(f"Unclosed leading HTML comment in {readme_path}.")
        index += 1
    return index


def _parse_discovery_readme(
    root: Path,
    definition: Category | Collection,
) -> tuple[str, str]:
    """Read one browse-group title and description from its index README."""

    readme_path = definition.readme_path
    readme = root / readme_path
    if not is_regular_repo_file(root, readme):
        raise CatalogError(f"Browse group requires a regular README.md: {readme_path}")
    lines = readme.read_text(encoding="utf-8").splitlines()
    index = _skip_leading_readme_comments(lines, readme_path)
    if index >= len(lines):
        raise CatalogError(f"Browse-group README is empty: {readme_path}")
    title_match = re.fullmatch(r"# ([^#].*)", lines[index])
    if title_match is None:
        raise CatalogError(
            f"Browse-group README must begin with one level-one title: {readme_path}"
        )
    title = title_match.group(1).strip()
    if title != title_match.group(1) or len(title) > 100:
        raise CatalogError(
            f"Browse-group title must be trimmed and at most 100 characters: {readme_path}"
        )
    if any(ord(character) < 32 for character in title) or re.search(
        r"[`*_~\[\]<>]", title
    ):
        raise CatalogError(f"Browse-group title must be plain text: {readme_path}")
    expected_id = (
        definition.id if isinstance(definition, Category) else definition.browse_id
    )
    if slugify(title) != expected_id:
        raise CatalogError(
            f"Browse-group title must slugify to {expected_id!r}: {readme_path}"
        )

    index += 1
    if index >= len(lines) or lines[index].strip():
        raise CatalogError(
            f"Browse-group title must be followed by a blank line: {readme_path}"
        )
    index += 1
    description_lines: list[str] = []
    while index < len(lines) and lines[index].strip():
        description_lines.append(lines[index].strip())
        index += 1
    description = " ".join(description_lines)
    if not description:
        raise CatalogError(f"Browse-group description is required: {readme_path}")
    if len(description) > 300:
        raise CatalogError(
            f"Browse-group description must be at most 300 characters: {readme_path}"
        )
    if any(ord(character) < 32 for character in description) or re.search(
        r"[`*_~\[\]<>]", description
    ) or any(
        re.match(r"(?:#{1,6}|>|[-+]|\d+[.)])(?:\s|$)|-{3,}$", line)
        for line in description_lines
    ):
        raise CatalogError(
            f"Browse-group description must be plain text: {readme_path}"
        )
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or lines[index] != EXAMPLES_HEADING:
        raise CatalogError(
            f"Browse-group README requires {EXAMPLES_HEADING!r} after its "
            f"description: {readme_path}"
        )
    return title, description


def load_discovery_groups(
    root: Path,
) -> tuple[tuple[Category, ...], tuple[Collection, ...]]:
    """Load authored browse-group presentation from canonical README indexes."""

    categories: list[Category] = []
    for definition in CATEGORY_DEFINITIONS:
        title, description = _parse_discovery_readme(root, definition)
        categories.append(replace(definition, title=title, description=description))
    collections: list[Collection] = []
    for definition in COLLECTION_DEFINITIONS:
        title, description = _parse_discovery_readme(root, definition)
        collections.append(replace(definition, title=title, description=description))
    return tuple(categories), tuple(collections)


def _parse_catalog_row(line: str, readme_path: str) -> tuple[str, str]:
    match = re.fullmatch(r"\| ([A-Za-z]+) \| ([^|]+) \|", line)
    if match is None:
        raise CatalogError(
            f"Invalid catalog metadata row in {readme_path}: {line!r}. "
            "Use `| Field | Value |` with no additional columns."
        )
    field, value = match.groups()
    if field not in CATALOG_FIELD_ORDER:
        raise CatalogError(
            f"Unknown catalog metadata field in {readme_path}: {field!r}."
        )
    if value != value.strip() or not value.strip():
        raise CatalogError(
            f"Catalog metadata field {field!r} must have a trimmed value in "
            f"{readme_path}."
        )
    stack_field = field in {"NemoClaw", "Harness", "OpenShell"}
    marked_up = re.search(
        r"[`*_\[\]]" if stack_field else r"[`*_~\[\]<>]",
        value,
    )
    if any(ord(character) < 32 for character in value) or (
        field != "Upstream" and marked_up
    ):
        raise CatalogError(
            f"Catalog metadata field {field!r} must be plain text in {readme_path}."
        )
    return field, value


def _validate_upstream_url(value: str, readme_path: str) -> str:
    """Require a safe absolute HTTPS URL for an optional upstream project."""

    if (
        len(value) > 2048
        or any(character.isspace() for character in value)
        or any(character in "<>" for character in value)
    ):
        raise CatalogError(
            f"Upstream must be an absolute HTTPS URL in {readme_path}."
        )
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        _ = parts.port
    except ValueError as error:
        raise CatalogError(
            f"Upstream must be an absolute HTTPS URL in {readme_path}."
        ) from error
    if (
        parts.scheme != "https"
        or not parts.netloc
        or not hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise CatalogError(
            f"Upstream must be an absolute HTTPS URL without credentials in {readme_path}."
        )
    return value


def parse_readme_metadata(
    root: Path,
    path: str,
    categories_by_id: dict[str, Category] | None = None,
    collections_by_value: dict[str, Collection] | None = None,
) -> CatalogEntry:
    """Parse the required human-readable metadata block from one example README."""

    category = classify_path(path, categories_by_id)
    tutorial_path = discover_tutorial_path(root, path, category)
    readme_path = f"examples/{path}/README.md"
    readme = root / readme_path
    if not is_regular_repo_file(root, readme):
        raise CatalogError(f"Example README is not a regular file: {readme_path}")
    lines = readme.read_text(encoding="utf-8").splitlines()
    index = _skip_leading_readme_comments(lines, readme_path)

    if index >= len(lines):
        raise CatalogError(f"Example README is empty: {readme_path}")
    title_match = re.fullmatch(r"# ([^#].*)", lines[index])
    if title_match is None:
        raise CatalogError(
            f"The first README content must be one level-one title in {readme_path}."
        )
    title = title_match.group(1).strip()
    if title != title_match.group(1) or len(title) > 100:
        raise CatalogError(
            f"README title must be trimmed and at most 100 characters in {readme_path}."
        )
    if any(ord(character) < 32 for character in title) or re.search(
        r"[`*_~\[\]<>]", title
    ):
        raise CatalogError(f"README title must be plain text in {readme_path}.")
    if not slugify(title):
        raise CatalogError(f"README title must contain letters or numbers in {readme_path}.")
    index += 1
    if index >= len(lines) or lines[index].strip():
        raise CatalogError(f"README title must be followed by a blank line in {readme_path}.")
    body_start = index + 1
    table_indices = [
        line_index
        for line_index in range(body_start, len(lines))
        if lines[line_index] == CATALOG_TABLE_HEADER
    ]
    if not table_indices:
        raise CatalogError(
            f"README requires `{CATALOG_TABLE_HEADER}` after the title or in a "
            f"final `{CATALOG_METADATA_HEADING}` section in {readme_path}."
        )
    if len(table_indices) > 1:
        raise CatalogError(f"Duplicate catalog metadata tables in {readme_path}.")
    table_index = table_indices[0]
    metadata_heading_index: int | None = None
    if table_index != body_start:
        metadata_heading_index = table_index - 2
        if (
            metadata_heading_index < body_start
            or lines[metadata_heading_index] != CATALOG_METADATA_HEADING
            or lines[metadata_heading_index + 1].strip()
        ):
            raise CatalogError(
                f"Catalog metadata must follow the README title or appear in a "
                f"final `{CATALOG_METADATA_HEADING}` section in {readme_path}."
            )
    index = table_index + 1
    if index >= len(lines) or lines[index] != CATALOG_TABLE_DIVIDER:
        raise CatalogError(
            f"README catalog table must use `{CATALOG_TABLE_DIVIDER}` in {readme_path}."
        )
    index += 1

    fields: dict[str, str] = {}
    field_names: list[str] = []
    while index < len(lines) and lines[index].startswith("|"):
        field, value = _parse_catalog_row(lines[index], readme_path)
        if field in fields:
            raise CatalogError(
                f"Duplicate catalog metadata field {field!r} in {readme_path}."
            )
        fields[field] = value
        field_names.append(field)
        index += 1
    expected_order = sorted(field_names, key=CATALOG_FIELD_ORDER.index)
    if field_names != expected_order:
        raise CatalogError(
            f"Catalog metadata fields are out of order in {readme_path}; use: "
            + ", ".join(CATALOG_FIELD_ORDER)
            + "."
        )
    missing_fields = {
        "Description",
        "Industry",
        "Requirements",
        "NemoClaw",
        "Harness",
        "OpenShell",
    } - set(fields)
    if missing_fields:
        raise CatalogError(
            f"Missing catalog metadata fields in {readme_path}: "
            + ", ".join(sorted(missing_fields))
        )
    if index < len(lines) and lines[index].strip():
        raise CatalogError(
            f"README catalog metadata table must be followed by a blank line in "
            f"{readme_path}."
        )
    if metadata_heading_index is not None and any(
        line.strip() for line in lines[index:]
    ):
        raise CatalogError(
            f"`{CATALOG_METADATA_HEADING}` must be the final README section in "
            f"{readme_path}."
        )
    while index < len(lines) and not lines[index].strip():
        index += 1

    if metadata_heading_index is None:
        readme_body = "\n".join(lines[index:]).strip()
    else:
        readme_body = "\n".join(lines[body_start:metadata_heading_index]).strip()

    description = fields["Description"]
    if len(description) > 300:
        raise CatalogError(
            f"Description must be at most 300 characters in {readme_path}."
        )
    industry_value = fields["Industry"]
    industry = next(
        (
            name
            for name, emoji in INDUSTRY_EMOJIS.items()
            if industry_value == f"{emoji} {name}"
        ),
        None,
    )
    if industry is None:
        raise CatalogError(
            f"Industry must use one documented emoji and title in {readme_path}; "
            f"got {industry_value!r}."
        )
    requirements = fields["Requirements"]
    if len(requirements) > 240:
        raise CatalogError(
            f"Requirements must be at most 240 characters in {readme_path}."
        )

    try:
        stack_declaration = parse_stack_declaration(
            fields["NemoClaw"],
            fields["Harness"],
            fields["OpenShell"],
        )
    except ValueError as error:
        raise CatalogError(f"Invalid runtime stack metadata in {readme_path}: {error}.") from error

    lifecycle = fields.get("Lifecycle", "Active")
    if lifecycle not in LIFECYCLES:
        raise CatalogError(
            f"Lifecycle must be Active or Deprecated in {readme_path}."
        )
    reviewed: dt.date | None = None
    if reviewed_value := fields.get("Reviewed"):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", reviewed_value) is None:
            raise CatalogError(f"Reviewed must use YYYY-MM-DD in {readme_path}.")
        try:
            reviewed = dt.date.fromisoformat(reviewed_value)
        except ValueError as error:
            raise CatalogError(
                f"Reviewed must be a valid calendar date in {readme_path}."
            ) from error

    upstream_url = fields.get("Upstream")
    if upstream_url is not None:
        upstream_url = _validate_upstream_url(upstream_url, readme_path)

    contributor = fields.get("Contributor")
    if contributor is not None and len(contributor) > 100:
        raise CatalogError(
            f"Contributor must be at most 100 characters in {readme_path}."
        )
    if category.id == "partner-recipes" and contributor is None:
        raise CatalogError(f"Partner recipe {path!r} requires a Contributor row.")
    if category.id != "partner-recipes" and contributor is not None:
        raise CatalogError(f"Only partner recipes can set Contributor ({path!r}).")

    collection_value = fields.get("Collection")
    collection_definitions = (
        collections_by_value or COLLECTION_DEFINITION_BY_VALUE
    )
    if (
        collection_value is not None
        and collection_value not in collection_definitions
    ):
        raise CatalogError(
            f"Unknown Collection value in {readme_path}: {collection_value!r}."
        )
    if collection_value is not None and category.kind != "recipe":
        raise CatalogError("Only recipes can declare a Collection row.")
    collections = tuple(
        collection
        for collection in collection_definitions.values()
        if collection.metadata_value == collection_value
        or category.id in collection.automatic_category_ids
    )

    return CatalogEntry(
        path=path,
        title=title,
        description=description,
        industry=industry,
        requirements=requirements,
        collections=collections,
        category=category,
        contributor=contributor,
        upstream_url=upstream_url,
        readme_body=readme_body,
        tutorial_path=tutorial_path,
        lifecycle=lifecycle,
        reviewed=reviewed,
        stack_declaration=stack_declaration,
    )


def load_catalog(
    root: Path,
    categories: tuple[Category, ...] | None = None,
    collections: tuple[Collection, ...] | None = None,
) -> list[CatalogEntry]:
    """Discover examples and validate catalog metadata in their READMEs."""

    if categories is None or collections is None:
        loaded_categories, loaded_collections = load_discovery_groups(root)
        categories = categories or loaded_categories
        collections = collections or loaded_collections
    categories_by_id = {category.id: category for category in categories}
    collections_by_value = {
        collection.metadata_value: collection for collection in collections
    }
    paths = discover_example_paths(root, categories_by_id)
    if not paths:
        raise CatalogError("No canonical example READMEs were discovered.")
    entries = [
        parse_readme_metadata(
            root,
            path,
            categories_by_id,
            collections_by_value,
        )
        for path in paths
    ]
    category_order = {
        category.id: index for index, category in enumerate(categories)
    }
    def sort_key(entry: CatalogEntry) -> tuple[int, str, str, str]:
        qualifier = ""
        if entry.category.id == "partner-recipes":
            qualifier = (entry.contributor or "").casefold()
        return (
            category_order[entry.category.id],
            qualifier,
            entry.title.casefold(),
            entry.path,
        )

    entries.sort(key=sort_key)

    seen_titles: set[str] = set()
    seen_ids: set[str] = set()
    for entry in entries:
        if entry.title.casefold() in seen_titles:
            raise CatalogError(f"Duplicate catalog title: {entry.title}")
        if entry.id in seen_ids:
            raise CatalogError(f"Duplicate generated catalog ID: {entry.id}")
        seen_titles.add(entry.title.casefold())
        seen_ids.add(entry.id)
    return entries


def latest_committed_activity(root: Path, entry: CatalogEntry) -> dt.date | None:
    """Return the last committed change date for one example."""

    if not (root / ".git").exists():
        raise CatalogError(
            "Catalog maintenance status requires Git history; build from a "
            "full Git checkout."
        )

    def run_git(arguments: list[str], operation: str) -> str:
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CatalogError(
                f"Unable to {operation} for {entry.path}: {error}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or f"git exited {result.returncode}"
            raise CatalogError(
                f"Unable to {operation} for {entry.path}: {detail}"
            )
        return result.stdout.strip()

    relative_path = f"examples/{entry.path}"
    value = run_git(
        ["log", "-1", "--format=%ct", "--", relative_path],
        "read committed activity",
    )
    if not value:
        status = run_git(
            [
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                relative_path,
            ],
            "inspect uncommitted activity",
        )
        if status:
            return None
        raise CatalogError(
            f"No Git history found for {entry.path}; use a full-history checkout."
        )
    try:
        return dt.datetime.fromtimestamp(
            int(value), tz=dt.timezone.utc
        ).date()
    except (OSError, OverflowError, ValueError) as error:
        raise CatalogError(
            f"Git returned an invalid activity timestamp for {entry.path}: {value!r}."
        ) from error


def enrich_catalog(
    root: Path,
    entries: list[CatalogEntry],
    *,
    today: dt.date | None = None,
    activity_dates: dict[str, dt.date] | None = None,
) -> list[CatalogEntry]:
    """Add read-only runtime stack facts and computed maintenance status."""

    current_day = today or dt.datetime.now(dt.timezone.utc).date()
    policy_path = root / "scripts" / "catalog-maintenance.json"
    try:
        policy = load_policy(policy_path) if policy_path.is_file() else load_policy()
        enriched: list[CatalogEntry] = []
        for entry in entries:
            committed_on = (
                activity_dates.get(entry.path)
                if activity_dates is not None and entry.path in activity_dates
                else latest_committed_activity(root, entry)
            )
            # A newly added, uncommitted example uses the build date for preview.
            committed_on = committed_on or current_day
            if entry.stack_declaration is None:
                raise CatalogError(f"Missing runtime stack declaration for {entry.path}.")
            try:
                stack = extract_example_stack_facts(
                    root / "examples" / entry.path,
                    entry.stack_declaration,
                )
            except (OSError, ValueError) as error:
                raise CatalogError(f"Invalid runtime stack contract: {error}") from error
            maintenance = compute_status(
                policy,
                committed_on=committed_on,
                reviewed_on=entry.reviewed,
                today=current_day,
                lifecycle=entry.lifecycle,
            )
            enriched.append(
                replace(
                    entry,
                    last_activity=committed_on,
                    stack=stack,
                    maintenance=maintenance,
                )
            )
        return enriched
    except MaintenancePolicyError as error:
        raise CatalogError(f"Invalid catalog maintenance policy: {error}") from error


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
            "teardown behavior. Documentation-only tutorials must identify their canonical",
            "content source. Add structured catalog metadata as described in the",
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
                "site/index.template.html."
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
    for line in source.splitlines():
        if fence:
            if re.fullmatch(
                rf" {{0,3}}{re.escape(fence[0])}{{{fence[1]},}}[ \t]*", line
            ):
                languages.append(fence[2])
                fence = None
            continue
        opening = re.fullmatch(
            r" {0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^`\r\n]*)", line
        )
        if not opening:
            continue
        marker = opening.group("fence")
        info = opening.group("info").strip()
        language = info.split(maxsplit=1)[0].casefold() if info else "text"
        if re.fullmatch(r"[a-z0-9_+.-]+", language) is None:
            language = "text"
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
            if (
                self.tutorial_mode
                and parts.scheme == "https"
                and parts.hostname
                and parts.username is None
                and parts.password is None
            ):
                return value
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
        if tag == "img" and not self.tutorial_mode:
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


def _detail_relative(entry: CatalogEntry, target: str) -> str:
    detail_dir = PurePosixPath(entry.detail_path).parent.as_posix()
    return posixpath.relpath(target, detail_dir)


def _display_stack_value(value: str | None, status: str) -> str:
    if status == "not-applicable":
        return "N/A"
    if value:
        return html.escape(value)
    return '<span class="fact-unknown">Unknown</span>'


def _fact_info(label: str, lines: list[str]) -> str:
    content = "".join(f"<span>{html.escape(line)}</span>" for line in lines)
    return (
        '<details class="fact-info">'
        f'<summary aria-label="{html.escape(label, quote=True)}">'
        '<span aria-hidden="true">i</span></summary>'
        f'<div class="fact-popover">{content}</div></details>'
    )


def render_stack_facts(entry: CatalogEntry) -> str:
    stack = entry.stack
    if stack is None:
        return ""
    if stack.harness.status == "not-applicable":
        harness = "N/A"
    elif stack.harness.name:
        harness = " ".join(
            (
                html.escape(stack.harness.name),
                _display_stack_value(stack.harness.version, stack.harness.status),
            )
        )
    else:
        harness = _display_stack_value(stack.harness.version, stack.harness.status)
    openshell_version = _display_stack_value(
        stack.openshell.version,
        stack.openshell.status,
    )
    status_label = {
        "confirmed": "Confirmed",
        "unconfirmed": "Unconfirmed",
        "unpinned": "Unpinned",
        "unknown": "Unknown",
        "conflict": "Conflict",
        "not-applicable": "Not applicable",
    }[stack.status]
    details = [
        re.sub(
            r" from NemoClaw v?\d+(?:\.\d+){2,3}",
            " from background release metadata",
            reason,
        )
        for reason in stack.reasons
        if not reason.startswith("NemoClaw")
    ] or ["All displayed runtime stack facts were confirmed."]
    if len(stack.evidence_paths) > 3:
        evidence = ", ".join(stack.evidence_paths[:2])
        evidence += f", and {len(stack.evidence_paths) - 2} more standardized files"
    else:
        evidence = ", ".join(stack.evidence_paths)
    details.append(
        f"Evidence: {evidence}."
        if evidence
        else "Evidence: no standardized runtime source found."
    )
    info = _fact_info("About stack metadata", details)
    status_value = (
        '<span class="status-label"><span class="status-dot" '
        f'aria-hidden="true"></span>{html.escape(status_label)}</span>'
    )
    return (
        f"<div><dt>Harness</dt><dd>{harness}</dd></div>"
        f"<div><dt>OpenShell</dt><dd>{openshell_version}</dd></div>"
        f'<div class="stack-status-fact stack-status-{stack.status}">'
        f"<dt>Stack verification</dt><dd>{status_value}{info}</dd></div>"
    )


def render_maintenance_fact(entry: CatalogEntry) -> str:
    status = entry.maintenance
    if status is None or entry.last_activity is None:
        return ""
    details = [
        status.summary,
        f"Last committed change: {entry.last_activity.isoformat()}.",
        f"Lifecycle: {entry.lifecycle}.",
        "This reflects repository activity only, not support, quality, or runtime health.",
    ]
    if entry.reviewed is not None:
        details.insert(2, f"Focused review: {entry.reviewed.isoformat()}.")
    info = _fact_info("About maintenance status", details)
    status_value = (
        '<span class="status-label"><span class="status-dot" '
        f'aria-hidden="true"></span>{html.escape(status.label)}</span>'
    )
    return (
        f'<div class="maintenance-fact maintenance-tone-{status.tone}">'
        f"<dt>Maintenance</dt><dd>{status_value}{info}</dd></div>"
    )


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
            f'{html.escape(collection.metadata_value)}</li>'
            for collection in entry.collections
        )
        if entry.contributor:
            attribution_fact = (
                f"<div><dt>Contributor</dt><dd>{html.escape(entry.contributor)}</dd></div>"
            )
        else:
            attribution_fact = ""
        upstream_fact = ""
        if entry.upstream_url:
            upstream_fact = (
                "<div><dt>Upstream project</dt><dd>"
                f'<a href="{html.escape(entry.upstream_url, quote=True)}">'
                "View upstream project <span aria-hidden=\"true\">↗</span>"
                "</a></dd></div>"
            )
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
        page_scripts = diagram_scripts
        if entry.is_tutorial:
            tutorial_script = (
                f'    <script type="module" '
                f'src="{_detail_relative(entry, "tutorial.mjs")}"></script>'
            )
            page_scripts = "\n".join(filter(None, (page_scripts, tutorial_script)))
        replacements = {
            "{{CONTENT_SECURITY_POLICY}}": html.escape(
                TUTORIAL_CONTENT_SECURITY_POLICY
                if entry.is_tutorial
                else DETAIL_CONTENT_SECURITY_POLICY,
                quote=True,
            ),
            "{{META_DESCRIPTION}}": html.escape(entry.description, quote=True),
            "{{PAGE_TITLE}}": html.escape(readme_title),
            "{{PAGE_CLASS}}": " tutorial-page" if entry.is_tutorial else "",
            "{{FAVICON_URL}}": _detail_relative(
                entry, "assets/nvidia-favicon.png"
            ),
            "{{STYLES_URL}}": _detail_relative(entry, "styles.css"),
            "{{LOGO_URL}}": _detail_relative(entry, "assets/nvidia-logo.png"),
            "{{CATALOG_URL}}": _detail_relative(entry, "index.html"),
            "{{TUTORIAL_URL}}": _detail_relative(
                entry, f"{FEATURED_TUTORIAL_URL}index.html"
            ),
            "{{SOURCE_URL}}": html.escape(entry.content_url, quote=True),
            "{{DISPLAY_LABEL}}": html.escape(entry.display_label),
            "{{DESCRIPTION}}": html.escape(entry.description),
            "{{INDUSTRY}}": html.escape(entry.industry_label),
            "{{COLLECTION_TAGS}}": collection_tags,
            "{{CATEGORY}}": html.escape(entry.category.singular),
            "{{FACTS_ATTRIBUTES}}": " hidden" if entry.is_tutorial else "",
            "{{ATTRIBUTION_FACT}}": attribution_fact,
            "{{UPSTREAM_FACT}}": upstream_fact,
            "{{STACK_FACTS}}": render_stack_facts(entry),
            "{{REQUIREMENTS}}": html.escape(entry.requirements),
            "{{MAINTENANCE_FACT}}": render_maintenance_fact(entry),
            "{{TABLE_OF_CONTENTS}}": toc_html,
            "{{CONTENT_LABEL}}": "Tutorial" if entry.is_tutorial else "Example guide",
            "{{CONTENT_CLASS}}": " tutorial-content" if entry.is_tutorial else "",
            "{{README_HTML}}": readme_html,
            "{{PAGE_SCRIPTS}}": page_scripts,
        }
        rendered = template
        for marker, value in replacements.items():
            expected_counts = {
                "{{CATALOG_URL}}": 3,
                "{{INDUSTRY}}": 2,
                "{{PAGE_TITLE}}": 2,
                "{{SOURCE_URL}}": 2,
                "{{TABLE_OF_CONTENTS}}": 2,
                "{{TUTORIAL_URL}}": 2,
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
    if parser.scripts != [{"type": "module", "src": "catalog.mjs"}]:
        errors.append("Expected exactly one local module script: catalog.mjs.")
    expected_resources = [
        "assets/nvidia-favicon.png",
        "styles.css",
        "assets/nvidia-logo.png",
        "catalog.mjs",
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

    for relative in (
        "site/styles.css",
        "site/catalog.mjs",
        "site/assets/nvidia-logo.png",
        "site/assets/nvidia-favicon.png",
    ):
        if not is_regular_repo_file(root, root / relative):
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
                    "src": _detail_relative(entry, "diagrams.mjs"),
                },
            ])
        if entry.is_tutorial:
            expected_scripts.append(
                {
                    "type": "module",
                    "src": _detail_relative(entry, "tutorial.mjs"),
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
        expected_styles = _detail_relative(entry, "styles.css")
        expected_logo = _detail_relative(entry, "assets/nvidia-logo.png")
        expected_favicon = _detail_relative(entry, "assets/nvidia-favicon.png")
        if expected_styles not in parser.resources:
            errors.append("Detail page is missing the shared stylesheet.")
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
            "site/diagrams.mjs",
            "site/assets/vendor/mermaid-LICENSE.txt",
        ):
            if not is_regular_repo_file(root, root / relative):
                raise CatalogError(f"Missing required diagram source: {relative}")
    if any(entry.is_tutorial for entry in entries) and not is_regular_repo_file(
        root, root / "site" / "tutorial.mjs"
    ):
        raise CatalogError("Missing required tutorial source: site/tutorial.mjs")


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


@dataclass(frozen=True)
class CatalogOutputs:
    entries: list[CatalogEntry]
    categories: tuple[Category, ...]
    collections: tuple[Collection, ...]
    readme: str
    discovery_readmes: dict[str, str]
    site_html: str
    catalog_json: str
    llms_txt: str
    detail_pages: dict[str, str]
    copied_assets: set[str]


def expected_outputs(
    root: Path,
    *,
    today: dt.date | None = None,
    activity_dates: dict[str, dt.date] | None = None,
) -> CatalogOutputs:
    categories, collections = load_discovery_groups(root)
    entries = load_catalog(root, categories, collections)
    entries = enrich_catalog(
        root,
        entries,
        today=today,
        activity_dates=activity_dates,
    )
    template_path = root / "site" / "index.template.html"
    detail_template_path = root / "site" / "detail.template.html"
    try:
        template = template_path.read_text(encoding="utf-8")
        detail_template = detail_template_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CatalogError(f"Unable to read site templates: {error}") from error
    rendered_readme = render_readme(entries, categories, collections)
    rendered_discovery_readmes = render_discovery_readmes(
        entries, categories, collections
    )
    rendered_site = render_site(entries, categories, collections, template)
    rendered_json = json.dumps(
        public_catalog(entries, categories, collections),
        indent=2,
        ensure_ascii=False,
    ) + "\n"
    rendered_llms = render_llms(entries)
    detail_pages, copied_assets = render_detail_pages(root, entries, detail_template)
    validate_generated_site(
        root, entries, categories, collections, rendered_site
    )
    validate_detail_pages(root, entries, detail_pages)
    if any('class="language-mermaid"' in page for page in detail_pages.values()):
        verified_mermaid_asset(root)
    return CatalogOutputs(
        entries=entries,
        categories=categories,
        collections=collections,
        readme=rendered_readme,
        discovery_readmes=rendered_discovery_readmes,
        site_html=rendered_site,
        catalog_json=rendered_json,
        llms_txt=rendered_llms,
        detail_pages=detail_pages,
        copied_assets=copied_assets,
    )


def check_catalog(root: Path) -> list[CatalogEntry]:
    outputs = expected_outputs(root)
    check_generated_readmes(root, outputs)
    return outputs.entries


def check_generated_readmes(root: Path, outputs: CatalogOutputs) -> None:
    """Require the root and browse-group indexes to match generated membership."""

    readme_path = root / "examples" / "README.md"
    actual_readme = readme_path.read_text(encoding="utf-8")
    if actual_readme != outputs.readme:
        raise CatalogError(
            "examples/README.md is out of date. Run "
            "`python3 scripts/build_catalog.py --write`."
        )
    stale_group_readmes = [
        path
        for path, expected in outputs.discovery_readmes.items()
        if (root / path).read_text(encoding="utf-8") != expected
    ]
    if stale_group_readmes:
        raise CatalogError(
            "Browse-group README membership is out of date: "
            + ", ".join(stale_group_readmes)
            + ". Run `python3 scripts/build_catalog.py --write`."
        )


def write_readmes(root: Path, outputs: CatalogOutputs) -> None:
    (root / "examples" / "README.md").write_text(outputs.readme, encoding="utf-8")
    for path, content in outputs.discovery_readmes.items():
        (root / path).write_text(content, encoding="utf-8")


def build_site(
    root: Path,
    output: Path,
    site_html: str,
    catalog_json: str,
    llms_txt: str = "",
    detail_pages: dict[str, str] | None = None,
    copied_assets: set[str] | None = None,
) -> None:
    output = output.absolute()
    expected_output = root.resolve() / "_site"
    if output != expected_output:
        raise CatalogError("Catalog output is restricted to the generated _site directory.")
    if output.is_symlink():
        raise CatalogError("Refusing to replace a symlinked _site directory.")
    has_tutorial = any(
        'class="detail-page tutorial-page"' in page
        for page in (detail_pages or {}).values()
    )
    shared_files = [
        root / "site" / "styles.css",
        root / "site" / "catalog.mjs",
    ]
    if has_tutorial:
        shared_files.append(root / "site" / "tutorial.mjs")
    for source in shared_files:
        if not is_regular_repo_file(root, source):
            raise CatalogError(
                f"Catalog site source must be a regular repository file: "
                f"{source.relative_to(root)}"
            )
    site_assets = root / "site" / "assets"
    if (
        path_uses_symlink(root, site_assets)
        or not site_assets.is_dir()
        or not site_assets.resolve().is_relative_to(root.resolve())
    ):
        raise CatalogError("Catalog site assets must be a regular repository directory.")
    for asset in site_assets.rglob("*"):
        if path_uses_symlink(root, asset) or not (asset.is_file() or asset.is_dir()):
            raise CatalogError(
                "Catalog site asset must not use a symlink or special file: "
                f"{asset.relative_to(root)}"
            )
    has_mermaid = any(
        'class="language-mermaid"' in page
        for page in (detail_pages or {}).values()
    )
    mermaid_asset: Path | None = None
    diagram_module: Path | None = None
    if has_mermaid:
        mermaid_asset = verified_mermaid_asset(root)
        diagram_module = root / "site" / "diagrams.mjs"
        if not diagram_module.is_file():
            raise CatalogError("Mermaid diagram module is not a regular file.")
        if diagram_module.is_symlink():
            raise CatalogError("Mermaid diagram module must not be a symlink.")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    (output / "index.html").write_text(site_html, encoding="utf-8")
    (output / "catalog.json").write_text(catalog_json, encoding="utf-8")
    (output / "llms.txt").write_text(llms_txt, encoding="utf-8")
    shutil.copy2(shared_files[0], output / "styles.css")
    shutil.copy2(shared_files[1], output / "catalog.mjs")
    if has_tutorial:
        shutil.copy2(shared_files[2], output / "tutorial.mjs")
    shutil.copytree(site_assets, output / "assets")
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
        if not is_regular_repo_file(root, source):
            raise CatalogError(
                f"README asset must be a regular repository file without symlinks: "
                f"{relative}"
            )
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
    mode.add_argument(
        "--validate-metadata",
        action="store_true",
        help="Validate example README catalog blocks without building the site.",
    )
    mode.add_argument(
        "--print-taxonomy",
        action="store_true",
        help="Print the generated browser taxonomy contract as JSON.",
    )
    args = parser.parse_args(argv)
    root = find_repo_root()
    output = root / "_site"

    try:
        if args.print_taxonomy:
            print(json.dumps(taxonomy_contract(), ensure_ascii=False))
            return 0
        if args.validate_metadata:
            entries = load_catalog(root)
            print(
                f"README catalog metadata is valid for {len(entries)} examples."
            )
            return 0
        outputs = expected_outputs(root)
        if args.check:
            check_generated_readmes(root, outputs)
            browse_groups = sum(
                category.browse for category in outputs.categories
            ) + len(outputs.collections)
            print(
                f"Catalog metadata and generated sources are valid: "
                f"{len(outputs.entries)} examples across "
                f"{browse_groups} browse groups."
            )
            return 0
        if args.write:
            write_readmes(root, outputs)
        else:
            check_generated_readmes(root, outputs)
        build_site(
            root,
            output,
            outputs.site_html,
            outputs.catalog_json,
            outputs.llms_txt,
            outputs.detail_pages,
            outputs.copied_assets,
        )
        print(
            f"Built {len(outputs.entries)} catalog entries and detail pages in "
            f"{output.relative_to(root)}."
        )
        return 0
    except (CatalogError, OSError) as error:
        print(f"Catalog build failed:\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
