# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for structured catalog metadata and generation."""

from __future__ import annotations

import html
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts.build_catalog import (
    _maintenance_status_for_entry,
    CATEGORY_DEFINITIONS,
    CATALOG_METADATA_HEADING,
    COLLECTION_DEFINITIONS,
    CatalogError,
    INDUSTRY_EMOJIS,
    MERMAID_SHA256,
    MERMAID_VERSION,
    MaintenanceStatus,
    PAGES_BASE_URL,
    build_site,
    expected_outputs,
    extract_mermaid_sources,
    last_content_change_on,
    load_catalog,
    load_discovery_groups,
    load_maintenance_policy,
    load_maintenance_snapshot,
    public_catalog,
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
from scripts.example_dependencies import resolve_dependency_contract


ROOT = Path(__file__).resolve().parents[2]


class CatalogBuildTests(unittest.TestCase):
    _DISCOVERY_TITLES = {
        "nvidia-recipes": "NVIDIA Recipes",
        "partner-recipes": "Partner Recipes",
        "community-recipes": "Community Recipes",
        "nvidia-field-demos": "NVIDIA Field Demos",
        "developer-tools": "Developer Tools",
        "hackathon": "Hackathon Recipes",
        "build-a-claw": "Build-a-Claw Recipes",
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
        ]
        if values.get("lifecycle"):
            rows.append(f"| Lifecycle | {values['lifecycle']} |")
        for field in ("Reviewed", "Upstream", "Contributor", "Collection"):
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
        scripts = root / "scripts"
        scripts.mkdir()
        for name in (
            "catalog-maintenance.json",
            "catalog-maintenance-releases.json",
        ):
            (scripts / name).write_text(
                (ROOT / "scripts" / name).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
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

    def _enrich_fixture_entries(
        self,
        root: Path,
        categories=None,
        collections=None,
    ):
        policy = load_maintenance_policy(root)
        snapshot = load_maintenance_snapshot(root, policy)
        entries = load_catalog(root, categories, collections)
        activity = date(2026, 8, 30)
        enriched = [
            replace(
                entry,
                last_content_change_on=activity,
                maintenance=MaintenanceStatus(
                    id="current",
                    label="Current",
                    explanation="Fixture maintenance is current.",
                    effective_on=activity,
                    activity_source="committed example change",
                    as_of=date(2026, 8, 31),
                    checked_on=snapshot.checked_on,
                ),
            )
            for entry in entries
        ]
        return enriched, policy, snapshot

    def _write_fixture_dependencies(
        self,
        root: Path,
        stack: str,
        path: str = "recipes/community/sample",
    ) -> None:
        example = root / "examples" / path
        (example / "dependencies.toml").write_text(
            "schema_version = 1\n\n" + stack.strip() + "\n",
            encoding="utf-8",
        )
        scripts = example / "scripts"
        scripts.mkdir(exist_ok=True)
        (scripts / "setup.sh").write_text(
            '#!/bin/sh\n. "$REPO_ROOT/scripts/example_dependencies.sh"\n'
            'load_example_dependencies "$EXAMPLE_ROOT"\n',
            encoding="utf-8",
        )

    def test_mermaid_fetch_and_build_pins_match(self) -> None:
        self.assertEqual(MERMAID_VERSION, FETCHED_MERMAID_VERSION)
        self.assertEqual(MERMAID_SHA256, FETCHED_MERMAID_SHA256)

    def test_current_catalog_and_generated_markdown_are_valid(self) -> None:
        outputs = expected_outputs(ROOT)
        entries = outputs.entries
        categories, collections = outputs.categories, outputs.collections

        self.assertGreater(len(entries), 0)
        index = public_catalog(
            entries,
            categories,
            collections,
            outputs.maintenance_policy,
            outputs.maintenance_snapshot,
            outputs.as_of,
        )
        self.assertEqual(
            sum(category["count"] for category in index["categories"]),
            len(entries),
        )
        for entry in entries:
            self.assertNotIn(
                "\n| Dependencies |",
                (ROOT / entry.readme_path).read_text(encoding="utf-8"),
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
        entries, policy, snapshot = self._enrich_fixture_entries(
            root, categories, collections
        )

        navigation = render_category_nav(entries, categories, collections)
        self.assertIn("A distinctive community description", navigation)
        self.assertIn("Build-a-Claw Recipes", navigation)
        self.assertIn('data-empty="true"', navigation)
        index = public_catalog(
            entries, categories, collections, policy, snapshot, date(2026, 8, 31)
        )
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

    def test_path_derives_kind_and_recipe_provenance(self) -> None:
        entry = load_catalog(self._fixture_root())[0]

        self.assertEqual(entry.category.kind, "recipe")
        self.assertEqual(entry.category.provenance, "community")
        self.assertEqual(entry.industry, "Other")

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

    def test_maintenance_metadata_is_controlled(self) -> None:
        root = self._fixture_root()
        self.assertEqual(load_catalog(root)[0].lifecycle, "Active")

        invalid = (
            ({"lifecycle": "Maintained"}, "Lifecycle must be one of"),
            ({"reviewed": "August 31, 2026"}, "must use YYYY-MM-DD"),
        )
        for record, message in invalid:
            with self.subTest(record=record):
                with self.assertRaisesRegex(CatalogError, message):
                    load_catalog(self._fixture_root(record))

        entry = load_catalog(
            self._fixture_root(
                {
                    "reviewed": "2026-08-30",
                }
            )
        )[0]
        self.assertEqual(entry.reviewed_on, date(2026, 8, 30))

        root = self._fixture_root()
        readme = root / "examples/recipes/community/sample/README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace(
                "| Requirements | Python 3 · local/static |",
                "| Requirements | Python 3 · local/static |\n| Dependencies | NemoClaw |",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CatalogError, "Unknown catalog metadata field"):
            load_catalog(root)

    def test_dependency_contract_resolves_the_runtime_and_catalog_stack(self) -> None:
        root = self._fixture_root()
        self._write_fixture_dependencies(
            root,
            '''[stack]
distribution = "direct"
harness = "hermes"
harness_version = "0.20.0"
openshell_version = "0.0.85"''',
        )
        entry = load_catalog(root)[0]
        self.assertIsNotNone(entry.dependency_contract)
        assert entry.dependency_contract is not None
        snapshot = load_maintenance_snapshot(
            root, load_maintenance_policy(root)
        )
        stack = resolve_dependency_contract(
            entry.dependency_contract,
            {"nemoclaw_stacks": snapshot.nemoclaw_stacks},
        )

        self.assertEqual(stack.harness_label, "Hermes Agent")
        self.assertEqual(stack.harness_version, "0.20.0")
        self.assertEqual(stack.openshell_version, "0.0.85")

    def test_dependency_contract_must_control_implementation_code(self) -> None:
        root = self._fixture_root()
        example = root / "examples/recipes/community/sample"
        (example / "dependencies.toml").write_text(
            '''schema_version = 1

[stack]
distribution = "direct"
harness = "openclaw"
harness_version = "2026.7.1"
''',
            encoding="utf-8",
        )
        scripts = example / "scripts"
        scripts.mkdir()
        (scripts / "note.sh").write_text(
            "#!/bin/sh\n"
            "# example_dependencies.sh\n"
            "# load_example_dependencies is intentionally only mentioned here.\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(CatalogError, "catalog-only"):
            load_catalog(root)

    def test_latest_example_commit_sets_activity(self) -> None:
        root = self._fixture_root()
        entry = load_catalog(root)[0]
        with patch(
            "scripts.build_catalog._run_git",
            side_effect=("true\n", "false\n", "2026-08-15T12:00:00+00:00\n"),
        ) as run_git:
            changed_on = last_content_change_on(root, entry, date(2026, 8, 31))

        self.assertEqual(changed_on, date(2026, 8, 15))
        self.assertEqual(run_git.call_count, 3)
        self.assertEqual(
            run_git.call_args_list[-1].args[1],
            ["log", "-1", "--format=%cI", "--", f"examples/{entry.path}"],
        )

    def test_maintenance_age_boundaries_escalate_and_auto_deprecate(self) -> None:
        root = self._fixture_root()
        policy = load_maintenance_policy(root)
        snapshot = load_maintenance_snapshot(root, policy)
        entry = load_catalog(root)[0]
        as_of = date(2026, 8, 31)

        cases = (
            (119, "current"),
            (120, "review-overdue"),
            (239, "review-overdue"),
            (240, "deprecated"),
        )
        for age_days, expected in cases:
            with self.subTest(age_days=age_days):
                status = _maintenance_status_for_entry(
                    replace(
                        entry,
                        last_content_change_on=as_of - timedelta(days=age_days),
                    ),
                    policy,
                    snapshot,
                    as_of,
                )
                self.assertEqual(status.id, expected)

        stable = _maintenance_status_for_entry(
            replace(
                entry,
                lifecycle="Stable",
                last_content_change_on=as_of - timedelta(days=120),
            ),
            policy,
            snapshot,
            as_of,
        )
        self.assertEqual(stable.id, "review-overdue")

        reviewed = _maintenance_status_for_entry(
            replace(
                entry,
                last_content_change_on=as_of - timedelta(days=240),
                reviewed_on=as_of - timedelta(days=1),
            ),
            policy,
            snapshot,
            as_of,
        )
        self.assertEqual(reviewed.id, "current")
        self.assertEqual(reviewed.activity_source, "maintenance review")

        explicitly_deprecated = _maintenance_status_for_entry(
            replace(
                entry,
                lifecycle="Deprecated",
                last_content_change_on=as_of,
            ),
            policy,
            snapshot,
            as_of,
        )
        self.assertEqual(explicitly_deprecated.id, "deprecated")

    def test_dependency_release_age_moves_through_review_states(self) -> None:
        root = self._fixture_root()
        self._write_fixture_dependencies(
            root,
            '''[stack]
distribution = "direct"
harness = "hermes"
harness_version = "0.20.0"''',
        )
        policy = load_maintenance_policy(root)
        snapshot = load_maintenance_snapshot(root, policy)
        entry = load_catalog(root)[0]
        assert entry.dependency_contract is not None
        entry = replace(
            entry,
            stack=resolve_dependency_contract(entry.dependency_contract, {}),
        )
        as_of = date(2026, 8, 31)

        cases = (
            (0, "review-soon"),
            (29, "review-soon"),
            (30, "review-due"),
            (59, "review-due"),
            (60, "review-overdue"),
        )
        for release_age_days, expected in cases:
            with self.subTest(release_age_days=release_age_days):
                release_day = as_of - timedelta(days=release_age_days)
                case_snapshot = replace(
                    snapshot,
                    releases={
                        **snapshot.releases,
                        "hermes-agent": replace(
                            snapshot.releases["hermes-agent"],
                            component_version="0.21.0",
                            published_on=release_day,
                        ),
                    },
                )
                status = _maintenance_status_for_entry(
                    replace(
                        entry,
                        last_content_change_on=release_day - timedelta(days=1),
                    ),
                    policy,
                    case_snapshot,
                    as_of,
                )

                self.assertEqual(status.id, expected)

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
        entries, policy, snapshot = self._enrich_fixture_entries(
            root, categories, collections
        )
        index = public_catalog(
            entries, categories, collections, policy, snapshot, date(2026, 8, 31)
        )
        example = index["examples"][0]

        self.assertEqual(index["schema_version"], 6)
        self.assertEqual(example["kind"], "recipe")
        self.assertEqual(example["provenance"], "community")
        self.assertEqual(example["industry"]["id"], "other")
        self.assertEqual(example["industry"]["emoji"], "✨")
        self.assertEqual(example["collections"], [])
        self.assertIsNone(example["upstream_url"])
        self.assertEqual(example["stack"], {"status": "not-declared"})
        self.assertNotIn("environment", example)
        self.assertEqual(
            example["description"],
            "Produces a small observable fixture result.",
        )
        self.assertEqual(example["requirements"], "Python 3 · local/static")
        self.assertEqual(example["maintenance"]["status"], "current")
        self.assertEqual(example["maintenance"]["lifecycle"], "Active")
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
            self.assertIsNotNone(entry.maintenance)
            assert entry.maintenance is not None
            self.assertEqual(page.count("<h1"), 1)
            self.assertIn(
                f'<p class="detail-summary">{html.escape(entry.description)}</p>',
                page,
            )
            self.assertIn("Requirements &amp; limits", page)
            self.assertNotIn("Catalog field", page)
            self.assertIn('id="readme" tabindex="-1"', page)
            self.assertNotRegex(page, r'<(?:iframe|object|embed)\b')
            self.assertNotRegex(page, r'<img[^>]+src="https?://')
            self.assertNotIn("maintenance-banner", page)
            facts = page.split('<aside class="detail-facts"', 1)[1].split(
                "</aside>", 1
            )[0]
            self.assertIn("<dt>Harness</dt>", facts)
            self.assertIn("<dt>OpenShell</dt>", facts)
            if entry.stack is None:
                value = "N/A" if entry.category.kind == "tool" else "Not declared"
                self.assertEqual(facts.count(f"<dd>{value}</dd>"), 2)
            else:
                self.assertIn(html.escape(entry.stack.harness_label), facts)
                self.assertIn(html.escape(entry.stack.harness_version), facts)
                self.assertIn(
                    html.escape(entry.stack.openshell_version or "N/A"),
                    facts,
                )
            self.assertIn(
                f'<div class="maintenance-fact" '
                f'data-maintenance="{entry.maintenance.id}">',
                facts,
            )
            self.assertIn('<details class="maintenance-info">', facts)
            self.assertIn('role="region" aria-label="Maintenance activity"', facts)
            self.assertIn(html.escape(entry.maintenance.explanation), facts)
            self.assertIn(entry.maintenance.effective_on.isoformat(), facts)
            self.assertIn(html.escape(entry.maintenance.activity_source), facts)
            self.assertIn(entry.maintenance.as_of.isoformat(), facts)
            self.assertIn(entry.maintenance.checked_on.isoformat(), facts)
            self.assertRegex(
                page,
                r'<link rel="icon" type="image/png" sizes="64x64" '
                r'href="[^"]*assets/nvidia-favicon\.png">',
            )
            diagram_count = page.count('class="language-mermaid"')
            source = (ROOT / entry.readme_path).read_text(encoding="utf-8")
            expected_diagram_count = len(
                extract_mermaid_sources(source, entry.readme_path)
            )
            self.assertEqual(diagram_count, expected_diagram_count)
            mermaid_diagrams += diagram_count
            if diagram_count:
                mermaid_pages += 1
                self.assertIn("mermaid.tiny.js", page)
                self.assertIn('type="module"', page)
                self.assertIn("diagrams.mjs", page)
            else:
                self.assertNotIn("<script", page)
        self.assertGreater(mermaid_pages, 0)
        self.assertGreater(mermaid_diagrams, 0)

    def test_upstream_reaches_json_detail_page_and_llms_index(self) -> None:
        upstream_url = "https://example.com/upstream/project_(one)"
        root = self._fixture_root(
            {"upstream": upstream_url}
        )
        categories, collections = load_discovery_groups(root)
        entries, policy, snapshot = self._enrich_fixture_entries(
            root, categories, collections
        )
        index = public_catalog(
            entries, categories, collections, policy, snapshot, date(2026, 8, 31)
        )
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

    def test_detail_page_shows_na_when_harness_does_not_use_openshell(self) -> None:
        root = self._fixture_root()
        self._write_fixture_dependencies(
            root,
            '''[stack]
distribution = "direct"
harness = "hermes"
harness_version = "0.21.0"''',
        )
        entries, _policy, _snapshot = self._enrich_fixture_entries(root)
        contract = entries[0].dependency_contract
        assert contract is not None
        entry = replace(entries[0], stack=resolve_dependency_contract(contract, {}))
        template = (ROOT / "site" / "detail.template.html").read_text(
            encoding="utf-8"
        )

        pages, _ = render_detail_pages(root, [entry], template)
        facts = pages[entry.detail_path].split(
            '<aside class="detail-facts"', 1
        )[1].split("</aside>", 1)[0]

        self.assertIn("Hermes Agent", facts)
        self.assertIn("0.21.0", facts)
        self.assertIn("<dt>OpenShell</dt><dd>N/A</dd>", facts)

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
        entries, _policy, _snapshot = self._enrich_fixture_entries(root)
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
