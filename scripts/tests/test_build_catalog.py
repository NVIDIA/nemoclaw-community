# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for structured catalog metadata and generation."""

from __future__ import annotations

import datetime as dt
import html
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.build_catalog import (
    CATEGORY_DEFINITIONS,
    CATALOG_METADATA_HEADING,
    COLLECTION_DEFINITIONS,
    CatalogError,
    INDUSTRY_EMOJIS,
    MERMAID_SHA256,
    MERMAID_VERSION,
    PAGES_BASE_URL,
    build_site,
    category_filter_options,
    check_catalog,
    expected_outputs,
    extract_mermaid_sources,
    latest_committed_activity,
    load_catalog,
    load_discovery_groups,
    public_catalog,
    render_catalog_groups,
    render_category_nav,
    render_discovery_readmes,
    render_llms,
    render_industry_nav,
    render_detail_pages,
    render_readme_html,
    validate_detail_pages,
)
from scripts.fetch_catalog_assets import (
    MERMAID_SHA256 as FETCHED_MERMAID_SHA256,
    MERMAID_VERSION as FETCHED_MERMAID_VERSION,
)


ROOT = Path(__file__).resolve().parents[2]


class CatalogBuildTests(unittest.TestCase):
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

    def test_mermaid_fetch_and_build_pins_match(self) -> None:
        self.assertEqual(MERMAID_VERSION, FETCHED_MERMAID_VERSION)
        self.assertEqual(MERMAID_SHA256, FETCHED_MERMAID_SHA256)

    def test_current_catalog_and_generated_markdown_are_valid(self) -> None:
        entries = check_catalog(ROOT)
        categories, collections = load_discovery_groups(ROOT)

        self.assertGreater(len(entries), 0)
        index = public_catalog(entries, categories, collections)
        self.assertEqual(
            sum(category["count"] for category in index["categories"]),
            len(entries),
        )

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

    def test_browse_group_metadata_drives_navigation_json_and_indexes(self) -> None:
        root = self._fixture_root()
        readme = root / "examples" / "recipes" / "community" / "README.md"
        content = readme.read_text(encoding="utf-8").replace(
            "Describes the Community Recipes browse group for fixture tests.",
            "A distinctive community description from the README source.",
        )
        readme.write_text(content, encoding="utf-8")
        categories, collections = load_discovery_groups(root)
        entries = load_catalog(root, categories, collections)

        navigation = render_category_nav(entries, categories, collections)
        self.assertIn("A distinctive community description", navigation)
        self.assertIn("Build-a-Claw", navigation)
        self.assertIn('data-empty="true"', navigation)
        index = public_catalog(entries, categories, collections)
        community = next(
            category
            for category in index["categories"]
            if category["id"] == "community-recipes"
        )
        self.assertEqual(
            community["description"],
            "A distinctive community description from the README source.",
        )
        group_readmes = render_discovery_readmes(
            entries, categories, collections
        )
        community_readme = group_readmes[
            "examples/recipes/community/README.md"
        ]
        self.assertIn(
            "[Sample Example](sample/README.md)",
            community_readme,
        )
        self.assertIn(
            "A distinctive community description from the README source.\n\n"
            "## Examples\n\n| Example | Industry | Description |",
            community_readme,
        )
        self.assertIn(
            "_No examples are currently in this group._",
            group_readmes["examples/collections/build-a-claw/README.md"],
        )
        self.assertEqual(
            sum(industry["count"] for industry in index["industries"]),
            len(entries),
        )

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

        with patch("scripts.build_catalog.subprocess.run") as run:
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

        with patch("scripts.build_catalog.subprocess.run") as run:
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

        with patch("scripts.build_catalog.subprocess.run") as run:
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

    def test_build_a_claw_has_one_combined_website_browse_group(self) -> None:
        root = self._fixture_root({"path": "demos/build-a-claw/tutorial"})
        categories, collections = load_discovery_groups(root)
        entries = load_catalog(root, categories, collections)

        navigation = render_category_nav(entries, categories, collections)
        options = category_filter_options(entries, categories, collections)
        groups = render_catalog_groups(entries, categories, collections)
        self.assertEqual(navigation.count("?category=build-a-claw#catalog"), 1)
        self.assertNotIn("?category=build-a-claw-demos", navigation)
        self.assertNotIn("?category=build-a-claw-recipes", navigation)
        self.assertEqual(options.count('value="build-a-claw"'), 1)
        self.assertNotIn('value="build-a-claw-demos"', options)
        self.assertNotIn('value="build-a-claw-recipes"', options)
        self.assertIn(
            '<div class="category-tile" data-empty="false">\n'
            '  <a class="category-tile-link" '
            'href="?category=build-a-claw#catalog">',
            navigation,
        )
        self.assertIn(
            '<span class="category-name">Build-a-Claw</span>', navigation
        )
        self.assertIn(">Build-a-Claw</h2>", groups)
        self.assertNotIn(">Build-a-Claw Demos</h2>", groups)

        index = public_catalog(entries, categories, collections)
        build_a_claw = next(
            collection
            for collection in index["collections"]
            if collection["id"] == "build-a-claw"
        )
        self.assertEqual(build_a_claw["count"], 1)
        self.assertEqual(index["examples"][0]["collections"], ["build-a-claw"])

    def test_build_a_claw_tutorial_uses_one_authored_markdown_source(self) -> None:
        root = self._fixture_root({"path": "demos/build-a-claw/tutorial"})
        tutorial = (
            root / "examples/demos/build-a-claw/tutorial/getting-started.md"
        )
        source = (
            b"# Authored Tutorial\n\n[TOC]\n\n# Part One\n\n## First Step\n\n"
            b"```text\n# Preserved in code\n[TOC]\n```\n\n"
            b"```bash\necho \"$HOME\" # highlighted command\n```\n\n"
            b"![Remote image](https://images.example.com/tutorial.png)\n\n"
            b'<iframe src="https://www.youtube.com/embed/video" '
            b'title="Tutorial video" allowfullscreen></iframe>\n'
        )
        tutorial.write_bytes(source)

        entry = load_catalog(root)[0]
        title, body, toc, _ = render_readme_html(
            root, entry, {entry.readme_path: entry}, set()
        )

        self.assertTrue(entry.is_tutorial)
        self.assertEqual(entry.content_path, entry.tutorial_path)
        self.assertEqual(title, "Authored Tutorial")
        self.assertIn('<h2 id="part-one">Part One</h2>', body)
        self.assertIn('<h3 id="first-step">First Step</h3>', body)
        self.assertIn("# Preserved in code", body)
        self.assertIn('<code class="language-text">', body)
        self.assertIn('<code class="language-bash">', body)
        self.assertIn('<span class="nb">echo</span>', body)
        self.assertNotIn('<div class="toc">', body)
        self.assertIn('href="#first-step"', toc)
        self.assertIn('src="https://images.example.com/tutorial.png"', body)
        self.assertIn('src="https://www.youtube.com/embed/video"', body)
        self.assertEqual(tutorial.read_bytes(), source)

    def test_build_a_claw_tutorial_source_is_singular_and_not_symlinked(self) -> None:
        root = self._fixture_root({"path": "demos/build-a-claw/tutorial"})
        directory = root / "examples/demos/build-a-claw/tutorial"
        (directory / "one.md").write_text("# One\n", encoding="utf-8")
        (directory / "two.md").write_text("# Two\n", encoding="utf-8")
        with self.assertRaisesRegex(CatalogError, "at most one"):
            load_catalog(root)

        root = self._fixture_root({"path": "demos/build-a-claw/tutorial"})
        directory = root / "examples/demos/build-a-claw/tutorial"
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

    def test_industry_navigation_wraps_slash_labels_at_word_boundaries(self) -> None:
        entries = load_catalog(
            self._fixture_root({"industry": "Automotive/Transportation"})
        )

        self.assertIn(
            "Automotive/<wbr>Transportation",
            render_industry_nav(entries),
        )

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

    def test_public_index_exposes_orthogonal_facets(self) -> None:
        root = self._fixture_root()
        categories, collections = load_discovery_groups(root)
        entries = load_catalog(root, categories, collections)
        index = public_catalog(entries, categories, collections)
        example = index["examples"][0]

        self.assertEqual(example["kind"], "recipe")
        self.assertEqual(example["provenance"], "community")
        self.assertEqual(example["industry"]["id"], "other")
        self.assertEqual(example["industry"]["emoji"], "✨")
        self.assertEqual(example["collections"], [])
        self.assertIsNone(example["upstream_url"])
        self.assertNotIn("environment", example)
        self.assertEqual(
            example["description"],
            "Produces a small observable fixture result.",
        )
        self.assertEqual(example["requirements"], "Python 3 · local/static")
        self.assertEqual(example["lifecycle"], "Active")
        self.assertIsNone(example["stack"])
        self.assertIsNone(example["maintenance"])
        self.assertEqual(
            example["detail_url"], "examples/recipes/community/sample/"
        )

    def test_current_catalog_compiles_one_safe_detail_page_per_example(self) -> None:
        outputs = expected_outputs(ROOT)
        entries = outputs.entries
        detail_pages = outputs.detail_pages
        copied_assets = outputs.copied_assets

        self.assertEqual(len(detail_pages), len(entries))
        self.assertEqual(set(detail_pages), {entry.detail_path for entry in entries})
        self.assertIn(
            '<link rel="icon" type="image/png" sizes="64x64" '
            'href="assets/nvidia-favicon.png">',
            outputs.site_html,
        )
        self.assertTrue(copied_assets)
        mermaid_pages = 0
        mermaid_diagrams = 0
        for entry in entries:
            page = detail_pages[entry.detail_path]
            self.assertEqual(page.count("<h1"), 1)
            self.assertIn(
                f'<p class="detail-summary">{html.escape(entry.description)}</p>',
                page,
            )
            self.assertIn("Requirements &amp; limits", page)
            facts_panel = page.split('<aside class="detail-facts"', 1)[1].split(
                "</aside>", 1
            )[0]
            facts_attributes = facts_panel.split(">", 1)[0]
            self.assertIn("<dt>Harness</dt>", facts_panel)
            self.assertIn("<dt>OpenShell</dt>", facts_panel)
            self.assertNotIn("<dt>NemoClaw</dt>", facts_panel)
            self.assertNotIn("<dt>Harness version</dt>", facts_panel)
            self.assertNotRegex(facts_panel, r"NemoClaw v?\d")
            self.assertEqual(
                facts_panel.count('class="status-dot" aria-hidden="true"'),
                2,
            )
            self.assertEqual(facts_panel.count('<details class="fact-info">'), 2)
            self.assertIn(
                '<summary aria-label="About stack metadata">', facts_panel
            )
            self.assertIn(
                '<summary aria-label="About maintenance status">', facts_panel
            )
            self.assertNotIn('role="tooltip"', facts_panel)
            self.assertNotIn('tabindex="0"', facts_panel)
            self.assertIn(
                "This reflects repository activity only, not support, quality, "
                "or runtime health.",
                facts_panel,
            )
            self.assertIn("Maintenance", page)
            self.assertIn(f"stack-status-{entry.stack.status}", page)
            self.assertIn(f"maintenance-tone-{entry.maintenance.tone}", page)
            self.assertNotIn("Catalog field", page)
            self.assertIn('id="readme" tabindex="-1"', page)
            if entry.is_tutorial:
                self.assertIn(" hidden", facts_attributes)
                self.assertRegex(page, r'<iframe\b')
                self.assertRegex(page, r'<img[^>]+src="https://')
                self.assertIn('<div class="codehilite">', page)
                self.assertIn('<code class="language-bash">', page)
                self.assertIn("tutorial.mjs", page)
            else:
                self.assertNotIn(" hidden", facts_attributes)
                self.assertNotRegex(page, r'<(?:iframe|object|embed)\b')
                self.assertNotRegex(page, r'<img[^>]+src="https?://')
            self.assertRegex(
                page,
                r'<link rel="icon" type="image/png" sizes="64x64" '
                r'href="[^"]*assets/nvidia-favicon\.png">',
            )
            diagram_count = page.count('class="language-mermaid"')
            source = (ROOT / entry.content_path).read_text(encoding="utf-8")
            expected_diagram_count = len(
                extract_mermaid_sources(source, entry.content_path)
            )
            self.assertEqual(diagram_count, expected_diagram_count)
            mermaid_diagrams += diagram_count
            if diagram_count:
                mermaid_pages += 1
                self.assertIn("mermaid.tiny.js", page)
                self.assertIn('type="module"', page)
                self.assertIn("diagrams.mjs", page)
            elif not entry.is_tutorial:
                self.assertNotIn("<script", page)
        generated_index = public_catalog(
            entries,
            outputs.categories,
            outputs.collections,
        )
        self.assertEqual(generated_index["schema_version"], 4)
        self.assertTrue(
            all(example["stack"] for example in generated_index["examples"])
        )
        self.assertTrue(
            all(example["maintenance"] for example in generated_index["examples"])
        )
        self.assertGreater(mermaid_pages, 0)
        self.assertGreater(mermaid_diagrams, 0)

    def test_upstream_reaches_json_detail_page_and_llms_index(self) -> None:
        upstream_url = "https://example.com/upstream/project_(one)"
        root = self._fixture_root(
            {"upstream": upstream_url}
        )
        categories, collections = load_discovery_groups(root)
        entries = load_catalog(root, categories, collections)
        index = public_catalog(entries, categories, collections)
        self.assertEqual(
            index["examples"][0]["upstream_url"],
            upstream_url,
        )

        template = (ROOT / "site" / "detail.template.html").read_text(
            encoding="utf-8"
        )
        pages, _ = render_detail_pages(root, entries, template)
        page = pages[entries[0].detail_path]
        self.assertIn("Upstream project", page)
        self.assertIn(upstream_url, page)

        llms = render_llms(entries)
        self.assertIn(f"[Sample Example]({PAGES_BASE_URL}examples/", llms)
        self.assertIn(f"[Project](<{upstream_url}>)", llms)
        self.assertIn(entries[0].guide_url, llms)

    def test_readme_compiler_rejects_unsafe_mermaid(self) -> None:
        unsafe_sources = {
            "unsupported type": "pie\n    title Unsafe",
            "configuration directive": (
                "flowchart LR\n"
                "    %%{init: {'theme': 'dark'}}%%\n"
                "    A --> B"
            ),
            "click directive": (
                "flowchart LR\n"
                "    A --> B\n"
                "    click A href 'https://example.com'"
            ),
            "inline click directive": (
                "flowchart LR\n"
                "    A --> B; click A 'https://example.com'"
            ),
            "remote image shape": (
                "flowchart LR\n"
                '    A@{ img: "https://example.com/image.png" }'
            ),
            "active HTML": "graph TD\n    A[<script>alert(1)</script>]",
        }
        for case, diagram in unsafe_sources.items():
            with self.subTest(case=case):
                root = self._fixture_root(
                    body=f"```mermaid\n{diagram}\n```\n"
                )
                entry = load_catalog(root)[0]

                with self.assertRaises(CatalogError):
                    render_readme_html(
                        root,
                        entry,
                        {entry.readme_path: entry},
                        set(),
                    )

    def test_readme_compiler_allows_plain_text_mermaid_labels(self) -> None:
        root = self._fixture_root(
            body=(
            "```mermaid\n"
            "graph LR\n"
            "    A[Data: customer records] --> B[Metadata: status]\n"
            "    B --> C[JavaScript: browser client]\n"
            "```\n"
            )
        )
        entry = load_catalog(root)[0]

        _, body, _, has_mermaid = render_readme_html(
            root,
            entry,
            {entry.readme_path: entry},
            set(),
        )

        self.assertTrue(has_mermaid)
        self.assertIn('class="language-mermaid"', body)

    def test_readme_compiler_rejects_active_raw_html(self) -> None:
        root = self._fixture_root(
            body="<script>alert('unsafe')</script>\n"
        )
        entry = load_catalog(root)[0]

        with self.assertRaisesRegex(CatalogError, "Unsupported README HTML element"):
            render_readme_html(
                root,
                entry,
                {entry.readme_path: entry},
                set(),
            )

    def test_tutorial_compiler_rejects_unsupported_iframes(self) -> None:
        for source in (
            "http://www.youtube.com/embed/video",
            "https://example.com/embed/video",
        ):
            with self.subTest(source=source):
                root = self._fixture_root(
                    {"path": "demos/build-a-claw/tutorial"}
                )
                tutorial = root / "examples/demos/build-a-claw/tutorial/guide.md"
                tutorial.write_text(
                    "# Tutorial\n\n"
                    f'<iframe src="{source}" title="Video"></iframe>\n',
                    encoding="utf-8",
                )
                entry = load_catalog(root)[0]
                with self.assertRaisesRegex(
                    CatalogError, "Unsupported tutorial iframe source"
                ):
                    render_readme_html(
                        root, entry, {entry.readme_path: entry}, set()
                    )

    def test_readme_compiler_rejects_unsafe_links(self) -> None:
        unsafe_links = (
            "http://example.com",
            "//example.com/path",
            "javascript:alert(1)",
            "data:text/html,unsafe",
            "../../../../../outside",
        )
        for destination in unsafe_links:
            with self.subTest(destination=destination):
                root = self._fixture_root(
                    body=f"[Unsafe link]({destination})\n"
                )
                entry = load_catalog(root)[0]

                with self.assertRaises(CatalogError):
                    render_readme_html(
                        root,
                        entry,
                        {entry.readme_path: entry},
                        set(),
                    )

    def test_readme_compiler_rejects_unsafe_image_assets(self) -> None:
        for case in ("svg", "symlink", "symlinked-parent", "oversized"):
            with self.subTest(case=case):
                root = self._fixture_root()
                example = root / "examples" / "recipes" / "community" / "sample"
                assets = example / "assets"
                if case == "symlinked-parent":
                    real_assets = example / "real-assets"
                    real_assets.mkdir()
                    asset = real_assets / "unsafe.png"
                    asset.write_bytes(b"png")
                    assets.symlink_to(real_assets, target_is_directory=True)
                else:
                    assets.mkdir()
                if case == "svg":
                    asset = assets / "unsafe.svg"
                    asset.write_text(
                        '<svg xmlns="http://www.w3.org/2000/svg" '
                        'xmlns:s="http://www.w3.org/2000/svg">'
                        '<s:script>alert(1)</s:script></svg>',
                        encoding="utf-8",
                    )
                elif case == "symlink":
                    source = root / "source.png"
                    source.write_bytes(b"png")
                    asset = assets / "unsafe.png"
                    asset.symlink_to(source)
                elif case == "oversized":
                    asset = assets / "unsafe.png"
                    asset.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
                self._write_fixture_readme(
                    root,
                    "recipes/community/sample",
                    body=f"![Unsafe image](assets/{asset.name})\n",
                )
                entry = load_catalog(root)[0]

                with self.assertRaises(CatalogError):
                    render_readme_html(
                        root,
                        entry,
                        {entry.readme_path: entry},
                        set(),
                    )

    def test_readme_compiler_rejects_missing_fragments(self) -> None:
        root = self._fixture_root(body="[Missing](README.md#not-present)\n")
        entry = load_catalog(root)[0]
        with self.assertRaisesRegex(CatalogError, "unresolved local fragments"):
            render_readme_html(root, entry, {entry.readme_path: entry}, set())

        self._write_fixture_readme(
            root,
            "recipes/community/target",
            {
                "title": "Target Example",
                "description": "Provides a second observable fixture result.",
            },
            body="## Present\n",
        )
        self._write_fixture_readme(
            root,
            "recipes/community/sample",
            body="[Missing](../target/README.md#not-present)\n",
        )
        entries = load_catalog(root)
        template = (ROOT / "site" / "detail.template.html").read_text(encoding="utf-8")
        pages, _ = render_detail_pages(root, entries, template)

        with self.assertRaisesRegex(CatalogError, "unresolved README fragment"):
            validate_detail_pages(root, entries, pages)

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

    def test_build_output_rejects_symlinked_shared_asset(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        site = root / "site"
        assets = site / "assets"
        assets.mkdir(parents=True)
        (site / "styles.css").write_text("", encoding="utf-8")
        (site / "catalog.mjs").write_text("", encoding="utf-8")
        source = root / "source.txt"
        source.write_text("must not be published", encoding="utf-8")
        (assets / "unsafe.txt").symlink_to(source)

        with self.assertRaisesRegex(CatalogError, "must not use a symlink"):
            build_site(root, root / "_site", "", "")

    def test_build_writes_llms_index_with_the_static_site(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        assets = root / "site" / "assets"
        assets.mkdir(parents=True)
        (root / "site" / "styles.css").write_text("", encoding="utf-8")
        (root / "site" / "catalog.mjs").write_text("", encoding="utf-8")
        (assets / "logo.png").write_bytes(b"png")

        build_site(root, root / "_site", "<html></html>", "{}\n", "# Index\n")

        self.assertEqual(
            (root / "_site" / "llms.txt").read_text(encoding="utf-8"),
            "# Index\n",
        )


if __name__ == "__main__":
    unittest.main()
