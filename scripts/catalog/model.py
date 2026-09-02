# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Core data structures and taxonomy for the generated catalog."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

try:
    from scripts.catalog_maintenance import MaintenanceStatus
    from scripts.example_stack_facts import StackDeclaration, StackFacts
except ModuleNotFoundError:  # Support direct execution via scripts/build_catalog.py.
    from catalog_maintenance import MaintenanceStatus  # type: ignore[no-redef]
    from example_stack_facts import (  # type: ignore[no-redef]
        StackDeclaration,
        StackFacts,
    )


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
        "build-a-claw",
        "build-a-claw",
        "Build-a-Claw",
        "examples/collections/build-a-claw/README.md",
        automatic_category_ids=("build-a-claw-demos",),
    ),
    Collection(
        "hackathon",
        "hackathon-recipes",
        "Hackathon",
        "examples/collections/hackathon/README.md",
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
