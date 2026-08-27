# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: invariant detection and its idempotency, on synthetic pages."""

import re, shutil, sys, tempfile, unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from memory_check import check_all, check_ceilings, check_decay, check_frontmatter, check_identity, check_index, check_links, check_provenance  # noqa: E402

FIXTURES = HERE.parents[1] / "fixtures" / "memory"


class TestInvariants(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "memory"
        shutil.copytree(FIXTURES, self.root)
        # The shipped fixture is dated; pin "today" so decay is deterministic.
        self.today = date(2026, 8, 18)

    def kinds(self, findings):
        return sorted({f.kind for f in findings})

    def test_the_shipped_fixture_memory_is_clean(self):
        # If the example ships a memory that fails its own checks, every other
        # assertion in this file is measuring the wrong thing.
        self.assertEqual(check_all(self.root, self.today), [])

    def test_an_unindexed_page_is_found(self):
        (self.root / "people" / "orphan.md").write_text(
            "---\nname: Orphan\n---\n\n# Orphan\n", encoding="utf-8")
        self.assertIn("unindexed", self.kinds(check_index(self.root)))

    def test_a_broken_link_is_found(self):
        p = self.root / "people" / "dana_okoro.md"
        p.write_text(p.read_text("utf-8").replace(
            "../projects/billing_migration/billing_migration.md",
            "../projects/gone/gone.md"), encoding="utf-8")
        self.assertIn("broken-link", self.kinds(check_links(self.root)))

    def test_a_page_past_its_decay_window_is_reported_not_corrected(self):
        p = self.root / "attention" / "current_priorities.md"
        before = p.read_text("utf-8")
        findings = check_decay(self.root, date(2026, 9, 30))
        self.assertIn("stale", self.kinds(findings))
        self.assertEqual(p.read_text("utf-8"), before, "detection must not rewrite")

    def test_an_unparseable_date_is_a_finding_rather_than_a_crash(self):
        p = self.root / "attention" / "current_priorities.md"
        p.write_text(p.read_text("utf-8").replace("updated: 2026-08-18", "updated: soon"),
                     encoding="utf-8")
        self.assertIn("bad-date", self.kinds(check_decay(self.root, self.today)))

    def test_a_patterns_page_with_no_provenance_is_found(self):
        d = self.root / "patterns"; d.mkdir()
        (d / "work_habits.md").write_text(
            "---\ntype: patterns\nupdated: 2026-08-18\ndecay: monthly\n---\n\n"
            "# Work habits\n\nReviews pull requests first thing in the morning.\n",
            encoding="utf-8")
        self.assertIn("unsourced", self.kinds(check_provenance(self.root)))

    def test_an_inferred_marker_satisfies_provenance(self):
        d = self.root / "patterns"; d.mkdir()
        (d / "work_habits.md").write_text(
            "---\ntype: patterns\nupdated: 2026-08-18\ndecay: monthly\n---\n\n"
            "# Work habits\n\nProbably reviews in the morning. (inferred)\n",
            encoding="utf-8")
        self.assertEqual(check_provenance(self.root), [])

    def test_a_section_over_its_ceiling_is_reported_for_consolidation(self):
        p = self.root / "people" / "dana_okoro.md"
        bullets = "\n".join(f"- 2026-08-{d:02d} — note {d}" for d in range(1, 32))
        p.write_text(p.read_text("utf-8").replace(
            "- 2026-08-18 — asked for the cutover window to be confirmed by Thursday.",
            bullets), encoding="utf-8")
        findings = check_ceilings(self.root)
        self.assertIn("over-ceiling", self.kinds(findings))
        self.assertIn("31 items", str(findings[0]))

    def test_a_binary_sidecar_named_like_a_page_does_not_break_the_pass(self):
        # macOS archives carry AppleDouble files named `._thing.md`. They end
        # in .md, they are binary, and reading one as text used to kill the
        # whole check on a real runtime.
        (self.root / "people" / "._dana_okoro.md").write_bytes(b"\x00\xa3\xff binary")
        self.assertEqual(check_all(self.root, self.today), [])

    def test_an_unreadable_page_is_reported_rather_than_fatal(self):
        (self.root / "people" / "corrupt.md").write_bytes(b"\xa3\xa3 not utf-8")
        kinds = self.kinds(check_all(self.root, self.today))
        self.assertIn("unreadable", kinds)

    def test_a_dangling_index_entry_is_found(self):
        # The index naming a page that does not exist is the mirror image of an
        # unindexed page, and until now only one of the two had a test.
        idx = self.root / "index.md"
        idx.write_text(idx.read_text("utf-8")
                       + "\n- [Gone](people/gone.md) — removed page.\n", encoding="utf-8")
        self.assertIn("index-dangling", self.kinds(check_index(self.root)))

    def test_detection_leaves_the_tree_byte_identical(self):
        # Idempotent findings are not the same as a read-only pass. Snapshot
        # every file and compare after, so a check that quietly rewrote a page
        # could not hide behind stable output.
        before = {p: p.read_bytes() for p in sorted(self.root.rglob("*.md"))}
        check_all(self.root, self.today)
        after = {p: p.read_bytes() for p in sorted(self.root.rglob("*.md"))}
        self.assertEqual(before, after)

    def test_detection_is_idempotent(self):
        # Running the checks twice must produce the same findings and must not
        # have changed anything in between — repair reruns constantly.
        (self.root / "people" / "orphan.md").write_text(
            "---\nname: Orphan\n---\n\n# Orphan\n", encoding="utf-8")
        first = [str(f) for f in check_all(self.root, self.today)]
        second = [str(f) for f in check_all(self.root, self.today)]
        self.assertEqual(first, second)
        self.assertTrue(first, "the fixture was supposed to be dirty")


class TestPersonIdentityIsChecked(unittest.TestCase):
    """`identities` is what the memory job matches a person on.

    Until this existed, two valid-looking people pages with no identity at
    all — and two claiming the same one — both passed `check_all()`, so the
    field that decides who a person is was the one thing the deterministic
    checker did not look at.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "memory"
        shutil.copytree(FIXTURES, self.root)
        self.person = self.root / "people" / "sam_ruiz.md"
        self.other = self.root / "people" / "dana_okoro.md"

    def _drop_identities(self, page):
        page.write_text(re.sub(r"^identities:\n(?:\s*-\s*\S+\n)+", "",
                               page.read_text(), count=1, flags=re.M))

    def _set_identities(self, page, *values):
        block = "identities:\n" + "".join(f"  - {v}\n" for v in values)
        page.write_text(re.sub(r"^identities:\n(?:\s*-\s*\S+\n)+", block,
                               page.read_text(), count=1, flags=re.M))

    def test_the_shipped_fixture_pages_carry_identities(self):
        self.assertEqual(check_identity(self.root), [])

    def test_a_page_with_no_identity_is_reported(self):
        self._drop_identities(self.person)
        findings = check_identity(self.root)
        self.assertEqual([f.kind for f in findings], ["missing-identity"])
        self.assertEqual(findings[0].path, "people/sam_ruiz.md")

    def test_a_page_from_before_the_list_still_counts_as_carrying_one(self):
        """`source_key:` is what earlier pages have. Reporting them as
        missing would send the repair job to rewrite pages that are fine."""
        self._drop_identities(self.person)
        self.person.write_text(
            self.person.read_text().replace(
                "name: Sam Ruiz",
                "name: Sam Ruiz\nsource_key: email:sam.ruiz@example.com", 1))
        self.assertEqual(check_identity(self.root), [])

    def test_an_entry_with_no_source_is_reported_as_malformed(self):
        """`dana@example.com` matches nothing — the selector looks for
        `email:dana@example.com` — so the page is orphaned, silently."""
        self._set_identities(self.person, "sam.ruiz@example.com")
        findings = check_identity(self.root)
        self.assertEqual([f.kind for f in findings], ["malformed-identity"])

    def test_two_pages_claiming_one_identity_are_reported(self):
        self._set_identities(self.person, "email:dana.okoro@example.com")
        findings = check_identity(self.root)
        self.assertEqual([f.kind for f in findings], ["duplicate-identity"])
        # Both pages are named, because the finding is about the pair and
        # neither one is knowably the wrong one.
        self.assertIn("dana_okoro.md", findings[0].detail)
        self.assertEqual(findings[0].path, "people/sam_ruiz.md")

    def test_a_duplicate_among_several_entries_is_still_caught(self):
        """A page may claim many, and the clash can be on any of them."""
        self._set_identities(self.person, "email:sam.ruiz@example.com",
                             "slack:U01SAM", "email:dana.okoro@example.com")
        self.assertIn("duplicate-identity",
                      [f.kind for f in check_identity(self.root)])

    def test_two_pages_sharing_no_identity_are_not_a_duplicate(self):
        """Otherwise a person with several accounts would report themselves."""
        self._set_identities(self.person, "email:sam.ruiz@example.com",
                             "slack:U01SAM")
        self._set_identities(self.other, "email:dana.okoro@example.com",
                             "slack:U01DANA")
        self.assertEqual(check_identity(self.root), [])

    def test_the_duplicate_report_does_not_depend_on_directory_order(self):
        """`glob` order is filesystem order. A finding that appears only on
        some machines is worse than no finding."""
        self._set_identities(self.other, "email:sam.ruiz@example.com")
        self.assertEqual([f.kind for f in check_identity(self.root)],
                         ["duplicate-identity"])

    def test_check_all_runs_it(self):
        """A check that exists but is not wired in has never run."""
        self._drop_identities(self.person)
        self.assertIn("missing-identity",
                      [f.kind for f in check_all(self.root)])


class TestFrontmatter(unittest.TestCase):
    """Required keys and constrained values, per page type.

    The schema states what each page type must carry. Until these checks
    existed a person page could lose its `name` and still be reported clean,
    which made "the memory is verified" a weaker claim than it sounded.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "memory"
        shutil.copytree(FIXTURES, self.root)
        self.person = self.root / "people" / "sam_ruiz.md"

    def kinds(self, findings):
        return sorted({f.kind for f in findings})

    def _drop_line(self, page, key):
        page.write_text(re.sub(rf"^{key}:.*\n", "", page.read_text(), count=1, flags=re.M))

    def _set(self, page, key, value):
        page.write_text(re.sub(rf"^{key}:.*$", f"{key}: {value}",
                               page.read_text(), count=1, flags=re.M))

    def test_the_shipped_fixture_pages_are_complete(self):
        self.assertEqual(check_frontmatter(self.root), [])

    def test_a_person_page_missing_its_name_is_reported(self):
        self._drop_line(self.person, "name")
        findings = check_frontmatter(self.root)
        self.assertEqual(self.kinds(findings), ["missing-field"])
        self.assertIn("name", findings[0].detail)
        self.assertEqual(findings[0].path, "people/sam_ruiz.md")

    def test_every_required_person_field_is_checked(self):
        # Each field is dropped on its own so a check cannot pass by way of
        # another field's finding.
        for key in ("role", "relationship", "importance",
                    "last_interaction", "interaction_frequency"):
            with self.subTest(field=key):
                shutil.rmtree(self.root)
                shutil.copytree(FIXTURES, self.root)
                self._drop_line(self.root / "people" / "sam_ruiz.md", key)
                details = [f.detail for f in check_frontmatter(self.root)]
                self.assertTrue(any(key in d for d in details), details)

    def test_a_value_outside_the_schemas_range_is_reported(self):
        self._set(self.person, "importance", "URGENT!!")
        findings = check_frontmatter(self.root)
        self.assertEqual(self.kinds(findings), ["bad-value"])
        self.assertIn("URGENT!!", findings[0].detail)

    def test_a_page_with_no_frontmatter_at_all_is_reported(self):
        self.person.write_text("Just prose, no block.\n")
        self.assertEqual(self.kinds(check_frontmatter(self.root)), ["missing-frontmatter"])

    def test_a_project_page_is_checked_against_its_own_required_fields(self):
        project = next((self.root / "projects").rglob("*.md"))
        self._drop_line(project, "priority")
        details = [f.detail for f in check_frontmatter(self.root)]
        self.assertTrue(any("priority" in d for d in details), details)

    def test_the_incomplete_page_reaches_the_top_level_report(self):
        """check_all runs it, so the scheduled repair job sees it too."""
        self._drop_line(self.person, "name")
        self.assertIn("missing-field", self.kinds(check_all(self.root, date(2026, 8, 18))))


if __name__ == "__main__":
    unittest.main(verbosity=2)
