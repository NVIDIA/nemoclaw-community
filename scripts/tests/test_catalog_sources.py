# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for catalog source discovery and metadata parsing."""

from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.catalog.model import CatalogError
from scripts.catalog.sources import (
    CATALOG_METADATA_HEADING,
    latest_committed_activity,
    load_catalog,
    load_discovery_groups,
)

from scripts.tests.catalog_test_support import CatalogFixtureMixin


class CatalogSourcesTests(CatalogFixtureMixin, unittest.TestCase):
    def test_browse_group_readmes_are_required_structured_sources(self) -> None:
        cases = {
            "missing": None,
            "marked-up description": (
                "# Community Recipes\n\n"
                "Uses **marked-up** metadata.\n\n"
                "## Examples\n"
            ),
            "Markdown block description": (
                "# Community Recipes\n\n"
                "---\n\n"
                "## Examples\n"
            ),
            "missing Examples heading": (
                "# Community Recipes\n\n"
                "A valid plain-text description.\n"
            ),
        }
        for case, content in cases.items():
            with self.subTest(case=case):
                root = self._fixture_root()
                readme = root / "examples" / "recipes" / "community" / "README.md"
                if content is None:
                    readme.unlink()
                else:
                    readme.write_text(content, encoding="utf-8")
                with self.assertRaises(CatalogError):
                    load_discovery_groups(root)

    def test_collection_directories_are_index_only(self) -> None:
        root = self._fixture_root()
        extra_file = root / "examples" / "collections" / "hackathon" / "notes.md"
        extra_file.write_text("Not an example index.\n", encoding="utf-8")

        with self.assertRaisesRegex(CatalogError, "may contain only README.md"):
            load_catalog(root)

    def test_new_empty_example_cannot_bypass_catalog_discovery(self) -> None:
        root = self._fixture_root()
        readme = (
            root
            / "examples"
            / "recipes"
            / "community"
            / "empty-example"
            / "README.md"
        )
        readme.parent.mkdir(parents=True)
        readme.write_text("", encoding="utf-8")

        with self.assertRaisesRegex(CatalogError, "Example README is empty"):
            load_catalog(root)

    def test_committed_activity_requires_a_git_checkout(self) -> None:
        root = self._fixture_root()
        entry = load_catalog(root)[0]

        with self.assertRaisesRegex(CatalogError, "requires Git history"):
            latest_committed_activity(root, entry)

    def test_committed_activity_uses_a_utc_epoch(self) -> None:
        root = self._fixture_root()
        (root / ".git").mkdir()
        entry = load_catalog(root)[0]

        with patch("scripts.catalog.sources.subprocess.run") as run:
            run.return_value = SimpleNamespace(
                returncode=0,
                stdout="1788136200\n",
                stderr="",
            )
            activity = latest_committed_activity(root, entry)

        self.assertEqual(activity, dt.date(2026, 8, 31))
        self.assertIn("--format=%ct", run.call_args.args[0])

    def test_uncommitted_new_example_uses_the_build_date(self) -> None:
        root = self._fixture_root()
        (root / ".git").mkdir()
        entry = load_catalog(root)[0]

        with patch("scripts.catalog.sources.subprocess.run") as run:
            run.side_effect = (
                SimpleNamespace(returncode=0, stdout="", stderr=""),
                SimpleNamespace(
                    returncode=0,
                    stdout=f"?? examples/{entry.path}/README.md\n",
                    stderr="",
                ),
            )
            activity = latest_committed_activity(root, entry)

        self.assertIsNone(activity)
        self.assertEqual(run.call_count, 2)
        self.assertIn("status", run.call_args.args[0])

    def test_clean_example_without_history_requires_a_full_checkout(self) -> None:
        root = self._fixture_root()
        (root / ".git").mkdir()
        entry = load_catalog(root)[0]

        with patch("scripts.catalog.sources.subprocess.run") as run:
            run.side_effect = (
                SimpleNamespace(returncode=0, stdout="", stderr=""),
                SimpleNamespace(returncode=0, stdout="", stderr=""),
            )
            with self.assertRaisesRegex(CatalogError, "full-history checkout"):
                latest_committed_activity(root, entry)

    def test_path_derives_kind_and_recipe_provenance(self) -> None:
        entry = load_catalog(self._fixture_root())[0]

        self.assertEqual(entry.category.kind, "recipe")
        self.assertEqual(entry.category.provenance, "community")
        self.assertEqual(entry.industry, "Other")

    def test_build_a_claw_demo_path_derives_demo_kind(self) -> None:
        entry = load_catalog(
            self._fixture_root({"path": "demos/build-a-claw/tutorial"})
        )[0]

        self.assertEqual(entry.category.id, "build-a-claw-demos")
        self.assertEqual(entry.category.kind, "demo")
        self.assertIsNone(entry.category.provenance)
        self.assertEqual(entry.collection_ids, ("build-a-claw",))
        self.assertFalse(entry.is_tutorial)
        self.assertEqual(entry.content_path, entry.readme_path)

    def test_tutorial_source_uses_exact_name_and_is_not_symlinked(self) -> None:
        root = self._fixture_root()
        directory = root / "examples/recipes/community/sample"
        (directory / "guide.md").write_text("# Guide\n", encoding="utf-8")
        self.assertFalse(load_catalog(root)[0].is_tutorial)

        tutorial = directory / "tutorial.md"
        tutorial.write_text("# Tutorial\n", encoding="utf-8")
        entry = load_catalog(root)[0]
        self.assertTrue(entry.is_tutorial)
        self.assertEqual(
            entry.tutorial_path,
            "examples/recipes/community/sample/tutorial.md",
        )

        root = self._fixture_root()
        directory = root / "examples/recipes/community/sample"
        (directory / "Tutorial.md").write_text("# Tutorial\n", encoding="utf-8")
        with self.assertRaisesRegex(CatalogError, "named exactly `tutorial.md`"):
            load_catalog(root)

        root = self._fixture_root()
        directory = root / "examples/recipes/community/sample"
        target = root / "outside.md"
        target.write_text("# Outside\n", encoding="utf-8")
        (directory / "tutorial.md").symlink_to(target)
        with self.assertRaisesRegex(CatalogError, "non-symlinked"):
            load_catalog(root)

    def test_unknown_industry_is_rejected(self) -> None:
        root = self._fixture_root({"industry": "Software"})

        with self.assertRaisesRegex(CatalogError, "documented emoji and title"):
            load_catalog(root)

    def test_wrong_industry_emoji_is_rejected(self) -> None:
        root = self._fixture_root({"industry_cell": "🎓 Other"})

        with self.assertRaisesRegex(CatalogError, "documented emoji and title"):
            load_catalog(root)

    def test_description_is_required_in_catalog_table(self) -> None:
        root = self._fixture_root()
        readme = root / "examples" / "recipes" / "community" / "sample" / "README.md"
        content = readme.read_text(encoding="utf-8").replace(
            "| Description | Produces a small observable fixture result. |\n",
            "",
        )
        readme.write_text(content, encoding="utf-8")

        with self.assertRaisesRegex(CatalogError, "Missing.*Description"):
            load_catalog(root)

    def test_runtime_stack_rows_are_required_and_strict(self) -> None:
        for field, value in (
            ("NemoClaw", "latest"),
            ("Harness", "AnyAgent 1.0.0"),
            ("OpenShell", "current"),
        ):
            with self.subTest(field=field):
                root = self._fixture_root({field.casefold(): value})
                with self.assertRaisesRegex(CatalogError, "runtime stack metadata"):
                    load_catalog(root)

    def test_catalog_table_requires_a_supported_position(self) -> None:
        root = self._fixture_root()
        readme = root / "examples" / "recipes" / "community" / "sample" / "README.md"
        content = readme.read_text(encoding="utf-8").replace(
            "# Sample Example\n\n| Catalog field | Value |",
            "# Sample Example\n\nA legacy description paragraph.\n\n"
            "| Catalog field | Value |",
        )
        readme.write_text(content, encoding="utf-8")

        with self.assertRaisesRegex(CatalogError, "must follow the README title"):
            load_catalog(root)

    def test_catalog_table_can_be_the_final_readme_section(self) -> None:
        root = self._fixture_root()
        readme = root / "examples" / "recipes" / "community" / "sample" / "README.md"
        title, remainder = readme.read_text(encoding="utf-8").split("\n\n", 1)
        table, body = remainder.split("\n\n", 1)
        readme.write_text(
            f"{title}\n\n{body.rstrip()}\n\n"
            f"{CATALOG_METADATA_HEADING}\n\n{table}\n",
            encoding="utf-8",
        )

        entry = load_catalog(root)[0]

        self.assertEqual(entry.description, "Produces a small observable fixture result.")
        self.assertEqual(entry.readme_body, "A small fixture.")

    def test_description_row_must_be_plain_text_and_at_most_300_characters(self) -> None:
        invalid_descriptions = (
            ("x" * 301, "at most 300 characters"),
            ("Uses `inline code`.", "must be plain text"),
        )
        for description, message in invalid_descriptions:
            with self.subTest(description=description[:20]):
                root = self._fixture_root({"description": description})

                with self.assertRaisesRegex(CatalogError, message):
                    load_catalog(root)

    def test_optional_lifecycle_and_review_date_are_strict(self) -> None:
        entry = load_catalog(
            self._fixture_root(
                {"lifecycle": "Active", "reviewed": "2026-08-01"}
            )
        )[0]
        self.assertEqual(entry.lifecycle, "Active")
        self.assertEqual(entry.reviewed.isoformat(), "2026-08-01")

        for record in (
            {"lifecycle": "Stable"},
            {"lifecycle": "Archived"},
            {"reviewed": "2026-02-30"},
            {"reviewed": "August 1, 2026"},
        ):
            with self.subTest(record=record):
                with self.assertRaises(CatalogError):
                    load_catalog(self._fixture_root(record))

    def test_non_kebab_case_catalog_path_is_rejected(self) -> None:
        root = self._fixture_root({"path": "recipes/community/Bad Name"})

        with self.assertRaisesRegex(CatalogError, "canonical example taxonomy"):
            load_catalog(root)

    def test_every_discovered_example_requires_readme_metadata(self) -> None:
        root = self._fixture_root()
        unlisted = root / "examples" / "tools" / "unlisted"
        unlisted.mkdir(parents=True)
        with self.assertRaisesRegex(CatalogError, "requires a regular README.md"):
            load_catalog(root)

    def test_partner_recipe_requires_contributor(self) -> None:
        root = self._fixture_root(
            {"path": "recipes/partners/acme/sample"}
        )

        with self.assertRaisesRegex(CatalogError, "requires a Contributor row"):
            load_catalog(root)

    def test_hackathon_collection_does_not_replace_provenance(self) -> None:
        entry = load_catalog(self._fixture_root({"collection": "Hackathon"}))[0]

        self.assertEqual(entry.category.provenance, "community")
        self.assertEqual(entry.collection_ids, ("hackathon",))

    def test_build_a_claw_collection_does_not_replace_provenance(self) -> None:
        entry = load_catalog(
            self._fixture_root({"collection": "Build-a-Claw"})
        )[0]

        self.assertEqual(entry.category.provenance, "community")
        self.assertEqual(entry.collection_ids, ("build-a-claw",))

    def test_upstream_requires_credential_free_absolute_https(self) -> None:
        accepted = "https://example.com/project?view=source#readme"
        entry = load_catalog(self._fixture_root({"upstream": accepted}))[0]
        self.assertEqual(entry.upstream_url, accepted)

        rejected = (
            "http://example.com/project",
            "../project",
            "//example.com/project",
            "https://user:secret@example.com/project",
            "https://example.com/a path",
            "https://example.com/project>",
            "https://example.com:invalid/project",
        )
        for upstream in rejected:
            with self.subTest(upstream=upstream):
                with self.assertRaisesRegex(CatalogError, "absolute HTTPS URL"):
                    load_catalog(self._fixture_root({"upstream": upstream}))


if __name__ == "__main__":
    unittest.main()
