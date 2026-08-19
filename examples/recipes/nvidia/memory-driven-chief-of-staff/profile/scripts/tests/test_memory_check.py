# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: invariant detection and its idempotency, on synthetic pages."""

import shutil, sys, tempfile, unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from memory_check import check_all, check_ceilings, check_decay, check_index, check_links, check_provenance  # noqa: E402

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
