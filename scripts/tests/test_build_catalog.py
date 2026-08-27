# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for structured catalog metadata and generation."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.build_catalog import (
    CatalogError,
    build_site,
    check_catalog,
    load_catalog,
    public_catalog,
)


ROOT = Path(__file__).resolve().parents[2]


class CatalogBuildTests(unittest.TestCase):
    def _fixture_root(self, record: dict[str, object] | None = None) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        example = root / "examples" / "recipes" / "community" / "sample"
        example.mkdir(parents=True)
        (example / "README.md").write_text(
            "# Sample Example\n\nA small fixture.\n", encoding="utf-8"
        )
        shutil.copy2(
            ROOT / "examples" / "catalog.schema.json",
            root / "examples" / "catalog.schema.json",
        )
        source_record: dict[str, object] = {
            "path": "recipes/community/sample",
            "title": "Sample Example",
            "description": "Produces a small observable fixture result.",
            "industry": "Other",
            "fit": "Python 3 · local/static",
            "collections": [],
        }
        if record:
            source_record.update(record)
        manifest = {
            "$schema": "catalog.schema.json",
            "schema_version": 1,
            "examples": [source_record],
        }
        (root / "examples" / "catalog.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return root

    def _rewrite_manifest(self, root: Path, mutate) -> None:
        path = root / "examples" / "catalog.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        mutate(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_current_catalog_and_generated_markdown_are_valid(self) -> None:
        entries = check_catalog(ROOT)

        self.assertGreater(len(entries), 0)
        index = public_catalog(entries)
        self.assertEqual(
            sum(category["count"] for category in index["categories"]),
            len(entries),
        )
        self.assertEqual(
            sum(industry["count"] for industry in index["industries"]),
            len(entries),
        )

    def test_path_derives_kind_and_recipe_provenance(self) -> None:
        entry = load_catalog(self._fixture_root())[0]

        self.assertEqual(entry.category.kind, "recipe")
        self.assertEqual(entry.category.provenance, "community")
        self.assertEqual(entry.industry, "Other")

    def test_unknown_industry_is_rejected(self) -> None:
        root = self._fixture_root({"industry": "Software"})

        with self.assertRaisesRegex(CatalogError, "documented values"):
            load_catalog(root)

    def test_non_kebab_case_catalog_path_is_rejected(self) -> None:
        root = self._fixture_root({"path": "recipes/community/Bad Name"})

        with self.assertRaisesRegex(CatalogError, "canonical example taxonomy"):
            load_catalog(root)

    def test_unlisted_top_level_example_is_rejected(self) -> None:
        root = self._fixture_root()
        unlisted = root / "examples" / "tools" / "unlisted"
        unlisted.mkdir(parents=True)
        (unlisted / "README.md").write_text("# Unlisted\n", encoding="utf-8")

        with self.assertRaisesRegex(CatalogError, "missing from examples/catalog.json"):
            load_catalog(root)

    def test_partner_recipe_requires_contributor(self) -> None:
        root = self._fixture_root()
        old = root / "examples" / "recipes" / "community" / "sample"
        new = root / "examples" / "recipes" / "partners" / "acme" / "sample"
        new.parent.mkdir(parents=True)
        old.rename(new)
        self._rewrite_manifest(
            root,
            lambda manifest: manifest["examples"][0].update(
                {"path": "recipes/partners/acme/sample"}
            ),
        )

        with self.assertRaisesRegex(CatalogError, "requires contributor"):
            load_catalog(root)

    def test_hackathon_collection_does_not_replace_provenance(self) -> None:
        entry = load_catalog(self._fixture_root({"collections": ["hackathon"]}))[0]

        self.assertEqual(entry.category.provenance, "community")
        self.assertEqual(entry.collections, ("hackathon",))

    def test_public_index_exposes_orthogonal_facets(self) -> None:
        entries = load_catalog(self._fixture_root())
        index = public_catalog(entries)
        example = index["examples"][0]

        self.assertEqual(example["kind"], "recipe")
        self.assertEqual(example["provenance"], "community")
        self.assertEqual(example["industry"]["id"], "other")
        self.assertEqual(example["collections"], [])

    def test_build_output_cannot_replace_source_or_follow_a_symlink(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        source = root / "site"
        source.mkdir()
        evidence = source / "keep.txt"
        evidence.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(CatalogError, "restricted to"):
            build_site(root, source, "", "")

        (root / "_site").symlink_to(source, target_is_directory=True)
        with self.assertRaisesRegex(CatalogError, "symlinked"):
            build_site(root, root / "_site", "", "")
        self.assertEqual(evidence.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
