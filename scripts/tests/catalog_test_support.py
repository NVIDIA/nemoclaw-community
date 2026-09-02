# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for catalog builder tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from scripts.catalog.model import (
    CATEGORY_DEFINITIONS,
    COLLECTION_DEFINITIONS,
    INDUSTRY_EMOJIS,
)


ROOT = Path(__file__).resolve().parents[2]


class CatalogFixtureMixin:
    _DISCOVERY_TITLES = {
        "nvidia-recipes": "NVIDIA Recipes",
        "partner-recipes": "Partner Recipes",
        "community-recipes": "Community Recipes",
        "nvidia-field-demos": "NVIDIA Field Demos",
        "build-a-claw-demos": "Build-a-Claw Demos",
        "developer-tools": "Developer Tools",
        "hackathon": "Hackathon Recipes",
        "build-a-claw": "Build-a-Claw",
    }

    def _write_fixture_discovery_readmes(self, root: Path) -> None:
        for definition in (*CATEGORY_DEFINITIONS, *COLLECTION_DEFINITIONS):
            title = self._DISCOVERY_TITLES[definition.id]
            readme = root / definition.readme_path
            readme.parent.mkdir(parents=True, exist_ok=True)
            readme.write_text(
                f"# {title}\n\n"
                f"Describes the {title} browse group for fixture tests.\n\n"
                "## Examples\n\n"
                "Fixture membership.\n",
                encoding="utf-8",
            )

    def _write_fixture_readme(
        self,
        root: Path,
        path: str,
        record: dict[str, str] | None = None,
        body: str = "A small fixture.\n",
    ) -> None:
        values = {
            "title": "Sample Example",
            "description": "Produces a small observable fixture result.",
            "industry": "Other",
            "requirements": "Python 3 · local/static",
            "nemoclaw": "N/A",
            "harness": "N/A",
            "openshell": "N/A",
        }
        if record:
            values.update(record)
        industry = values["industry"]
        industry_cell = values.get(
            "industry_cell",
            f"{INDUSTRY_EMOJIS.get(industry, '✨')} {industry}",
        )
        rows = [
            f"| Description | {values['description']} |",
            f"| Industry | {industry_cell} |",
            f"| Requirements | {values['requirements']} |",
            f"| NemoClaw | {values['nemoclaw']} |",
            f"| Harness | {values['harness']} |",
            f"| OpenShell | {values['openshell']} |",
        ]
        for field in (
            "Lifecycle",
            "Reviewed",
            "Upstream",
            "Contributor",
            "Collection",
        ):
            value = values.get(field.casefold())
            if value:
                rows.append(f"| {field} | {value} |")
        content = (
            f"# {values['title']}\n\n"
            "| Catalog field | Value |\n"
            "| --- | --- |\n"
            + "\n".join(rows)
            + "\n\n"
            + body
        )
        readme = root / "examples" / path / "README.md"
        readme.parent.mkdir(parents=True, exist_ok=True)
        readme.write_text(content, encoding="utf-8")

    def _fixture_root(
        self,
        record: dict[str, str] | None = None,
        body: str = "A small fixture.\n",
    ) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self._write_fixture_discovery_readmes(root)
        values = dict(record or {})
        path = values.pop("path", "recipes/community/sample")
        self._write_fixture_readme(
            root,
            path,
            values,
            body,
        )
        return root
