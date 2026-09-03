# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: invariant detection and its idempotency, on synthetic pages."""

import re, shutil, sys, tempfile, unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import memory_check  # noqa: E402
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


class TestTheContractDoesNotContradictTheChecker(unittest.TestCase):
    """Three places where following the schema produced a finding.

    Each was reachable from a correct memory, which is what made them worth
    fixing before anything is built on this checker: a later phase that says
    "checks pass" is worth less when two of the findings are permanent and
    were caused by obeying the contract.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "memory"
        shutil.copytree(FIXTURES, self.root)

    # The fixture's `stale` finding comes from a seed deliberately dated
    # 1970-01-01, so it holds at any date — but the other pages carry real
    # dates and would start decaying as the calendar moves past them. Pinning
    # keeps this file measuring the change rather than the day it runs.
    TODAY = date(2026, 8, 20)

    def kinds(self, findings=None):
        return sorted(f.kind for f in
                      (findings or check_all(self.root, self.TODAY)))

    def test_the_fixture_memory_is_clean_apart_from_the_stale_seed(self):
        """The baseline this file measures against. `current_priorities.md`
        ships dated 1970-01-01 on purpose so the first repair run has work."""
        self.assertEqual(self.kinds(), ["stale"])

    def test_a_rotated_project_log_produces_no_finding(self):
        """`schema.md` requires log.md to rotate into log.archive.md at 1000
        entries. Before this, doing so left `unindexed` and
        `missing-frontmatter` reported for as long as the archive existed —
        two permanent findings caused by following the contract, on a file
        that is an append-only history and carries no frontmatter by design.
        """
        archive = self.root / "projects" / "billing_migration" / "log.archive.md"
        archive.write_text("- 2026-01-01 an older entry\n", encoding="utf-8")
        self.assertEqual(self.kinds(), ["stale"])

    def test_only_the_sidecars_the_schema_declares_are_exempt(self):
        """The exemption is a list, and it is the schema's list.

        Reading "anything not named after the folder" as a sidecar was the
        first attempt, and it deleted a real page from every check: a project
        page written as `overview.md` reported nothing — no missing field, no
        bad value, no broken link — where the code it replaced reported four.
        A file in a project folder that is neither the page nor a declared
        sidecar is far more likely to be a page under the wrong name than a
        sidecar nobody wrote down.
        """
        folder = self.root / "projects" / "billing_migration"
        (folder / "log.archive.md").write_text("- older\n", encoding="utf-8")
        self.assertEqual(self.kinds(), ["stale"])

        (folder / "notes.md").write_text(
            "scratch\n", encoding="utf-8")
        self.assertIn("unindexed", self.kinds(),
                      "an undeclared file in a project folder was swallowed")

    def test_a_reserved_name_at_the_wrong_depth_is_still_checked(self):
        """The exemption is positional, not just nominal.

        A file merely named `log.md`, outside the root and outside a
        project folder's own top level, shares a sidecar's name without
        being in the position the schema puts one there. `patterns/log.md`
        and a project sidecar nested one level deeper than the schema
        allows both used to disappear from every check by name alone.
        """
        (self.root / "patterns").mkdir()
        (self.root / "patterns" / "log.md").write_text(
            "scratch\n", encoding="utf-8")
        unindexed = {f.path for f in check_index(self.root)
                    if f.kind == "unindexed"}
        self.assertIn("patterns/log.md", unindexed,
                      "a file merely named log.md, not the memory root's own,"
                      " was swallowed")

        nested = self.root / "projects" / "billing_migration" / "nested"
        nested.mkdir()
        (nested / "log.archive.md").write_text("scratch\n", encoding="utf-8")
        unindexed = {f.path for f in check_index(self.root)
                    if f.kind == "unindexed"}
        self.assertIn("projects/billing_migration/nested/log.archive.md",
                      unindexed,
                      "a sidecar name nested deeper than the schema puts one"
                      " was swallowed")

    def test_a_page_linked_under_the_wrong_section_is_found(self):
        """A link merely present in the document is not the same as filed
        where it belongs.

        A concept page linked under `## People`, with an empty `## Concepts`
        heading added after `## Attention`, used to pass: heading presence
        and link presence were each checked without regard to where either
        one actually sat.
        """
        (self.root / "concepts").mkdir(exist_ok=True)
        (self.root / "concepts" / "cutover.md").write_text(
            "---\ntype: concept\nupdated: 2026-08-20\n---\n\n# Cutover\n",
            encoding="utf-8")
        index = self.root / "index.md"
        original = index.read_text(encoding="utf-8")

        misfiled = original.replace(
            "## People\n",
            "## People\n\n- [Cutover](concepts/cutover.md) — the window\n",
            1).rstrip() + "\n\n## Concepts\n"
        index.write_text(misfiled, encoding="utf-8")
        found = {f.kind for f in check_all(self.root, self.TODAY)}
        self.assertIn("index-misfiled", found)
        self.assertIn("index-out-of-order", found)

        # Filed under its own section, in schema order, both clear.
        fixed = original.replace(
            "## Attention",
            "## Concepts\n\n- [Cutover](concepts/cutover.md) — the window\n"
            "\n## Attention", 1)
        index.write_text(fixed, encoding="utf-8")
        after = {f.kind for f in check_all(self.root, self.TODAY)}
        self.assertNotIn("index-misfiled", after)
        self.assertNotIn("index-out-of-order", after)
        self.assertNotIn("index-section-missing", after)
        self.assertNotIn("unindexed", after)

    def test_a_fenced_or_commented_sample_index_entry_is_not_real_content(self):
        """A code fence or an HTML comment can quote what a heading or a
        link looks like without making it real index content — a reader
        showing an example is not the same as filing the entry.
        """
        (self.root / "concepts").mkdir(exist_ok=True)
        (self.root / "concepts" / "cutover.md").write_text(
            "---\ntype: concept\nupdated: 2026-08-20\n---\n\n# Cutover\n",
            encoding="utf-8")
        index = self.root / "index.md"
        original = index.read_text(encoding="utf-8")

        decorated = original.rstrip() + (
            "\n\n```markdown\n## Concepts\n```\n"
            "\n<!-- example: [Cutover](concepts/cutover.md) -->\n")
        index.write_text(decorated, encoding="utf-8")

        found = {f.kind for f in check_all(self.root, self.TODAY)}
        self.assertIn("index-section-missing", found,
                      "a heading quoted inside a code fence satisfied the check")
        self.assertIn("unindexed", found,
                      "a link quoted inside an HTML comment satisfied the check")

    def test_a_duplicate_misfiled_link_is_found_even_after_a_correct_one(self):
        """A target linked twice — once correctly, once from the wrong
        section — is still a misfiled entry. Checking only the first
        occurrence, in document order, missed exactly this duplicate: the
        correct one came first and hid the wrong one that followed it.
        """
        (self.root / "concepts").mkdir(exist_ok=True)
        (self.root / "concepts" / "cutover.md").write_text(
            "---\ntype: concept\nupdated: 2026-08-20\n---\n\n# Cutover\n",
            encoding="utf-8")
        index = self.root / "index.md"
        original = index.read_text(encoding="utf-8")

        # Correctly filed under a fresh ## Concepts section (which comes
        # before ## Attention in document order), then duplicated under
        # ## Attention — the first, correct occurrence would hide the
        # second if only the first were checked.
        doubled = original.replace(
            "## Attention",
            "## Concepts\n\n- [Cutover](concepts/cutover.md) — the window\n"
            "\n## Attention", 1)
        doubled = doubled.replace(
            "## Attention\n",
            "## Attention\n\n- [Cutover, again](concepts/cutover.md) —"
            " duplicate\n", 1)
        index.write_text(doubled, encoding="utf-8")

        found = {f.kind for f in check_all(self.root, self.TODAY)}
        self.assertIn("index-misfiled", found,
                      "a correct first occurrence hid a misfiled duplicate")

    def test_index_section_missing_and_misfiled_fire_together_for_the_same_type(self):
        """When a page's type has no section yet but the page is already
        linked somewhere else, both findings fire together — that pairing
        is what tells the repair job to move the existing entry rather than
        leave the new section empty.
        """
        (self.root / "concepts").mkdir(exist_ok=True)
        (self.root / "concepts" / "cutover.md").write_text(
            "---\ntype: concept\nupdated: 2026-08-20\n---\n\n# Cutover\n",
            encoding="utf-8")
        index = self.root / "index.md"
        index.write_text(
            index.read_text(encoding="utf-8").replace(
                "## People\n",
                "## People\n\n- [Cutover](concepts/cutover.md) — the"
                " window\n", 1),
            encoding="utf-8")

        found = {f.kind for f in check_all(self.root, self.TODAY)}
        self.assertIn("index-section-missing", found)
        self.assertIn("index-misfiled", found)

    def test_a_project_page_under_the_wrong_name_is_still_checked(self):
        """The shape that most needs reporting, and the one the first rule
        was silent about. `projects/` has no writer, so these pages come from
        a person — which is exactly where a name mismatch comes from."""
        folder = self.root / "projects" / "onboarding_revamp"
        folder.mkdir(parents=True)
        (folder / "overview.md").write_text(
            "---\nname: Onboarding revamp\npriority: URGENT\nrole: owner\n"
            "---\n\n# Onboarding revamp\n\n## Resources\n\n"
            "- [gone](../../people/nobody.md)\n", encoding="utf-8")
        found = self.kinds()
        for kind in ("unindexed", "missing-field", "bad-value", "broken-link"):
            with self.subTest(kind=kind):
                self.assertIn(kind, found)

    def test_the_declared_sidecars_are_the_ones_the_schema_lists(self):
        """Two statements of one rule, so they are compared rather than
        trusted to stay together."""
        recipe = HERE.parents[1]
        block = re.search(r"projects/<slug>/\n(.*?)```",
                          (recipe / "profile" / "schema.md").read_text(
                              encoding="utf-8"), re.S).group(1)
        listed = set(re.findall(r"([\w.]+\.md)", block)) - {"<slug>.md"}
        self.assertEqual(listed, set(memory_check.DECLARED_SIDECARS))

    def test_the_page_inside_a_folder_type_is_still_checked(self):
        """The exemption must not swallow the page it sits beside."""
        page = (self.root / "projects" / "billing_migration"
                / "billing_migration.md")
        page.write_text(re.sub(r"^name:.*\n", "", page.read_text(),
                               count=1, flags=re.M), encoding="utf-8")
        self.assertIn("missing-field", self.kinds())

    def test_a_page_nested_in_a_flat_type_is_still_checked(self):
        """The exemption is for folder-shaped types and nothing else.

        A first attempt read "nested and not named after its folder" as the
        definition of a sidecar. That skipped a page nested anywhere — and
        skipping is worse than the defect it replaced, because an unindexed
        page is reported while an unchecked one is silent. Measured: a
        `patterns/sub/x.md` missing every required field produced no finding
        at all.
        """
        nested = self.root / "patterns" / "sub"
        nested.mkdir(parents=True)
        (nested / "work_habits.md").write_text(
            "---\ntype: pattern\n---\n\n# No updated, no decay\n",
            encoding="utf-8")
        found = self.kinds()
        self.assertIn("missing-field", found)
        self.assertIn("unindexed", found)

    def test_only_the_types_the_schema_writes_as_folders_have_sidecars(self):
        """`FOLDER_SHAPED` is the whole exemption, and the schema names its
        members by spelling them `<type>/<slug>/` in their own headings."""
        recipe = HERE.parents[1]
        headings = re.findall(r"^### \w[\w ]*\(`([a-z_]+)/(<slug>/)?`\)",
                              (recipe / "profile" / "schema.md").read_text(
                                  encoding="utf-8"), re.M)
        foldered = {name for name, slug in headings if slug}
        self.assertEqual(foldered, set(memory_check.FOLDER_SHAPED))

    def test_a_concept_page_can_be_indexed(self):
        """`concepts/` is one of the six page types and had no section in the
        index order, so the first one written was `unindexed` on arrival with
        nowhere to put the entry that would clear it.

        Written against the index the recipe ships rather than one this test
        composes. Appending a section here would pass whatever the seed says,
        which is the shape of test that let the defect exist: `check_index`
        resolves links and never reads a heading, so only the shipped file
        can answer whether there is somewhere to put the entry.
        """
        recipe = HERE.parents[1]
        index = self.root / "index.md"
        index.write_text(
            (recipe / "profile" / "seed" / "index.md").read_text(
                encoding="utf-8"), encoding="utf-8")
        (self.root / "concepts").mkdir(exist_ok=True)
        (self.root / "concepts" / "cutover.md").write_text(
            "---\ntype: concept\nupdated: 2026-08-20\n---\n\n"
            "# Cutover\n\nThe window a migration runs in.\n",
            encoding="utf-8")

        # Every other page is now unindexed too, because the seed indexes
        # none of the fixture's pages. The concept page is the one under test.
        unindexed = {f.path for f in check_all(self.root, self.TODAY)
                     if f.kind == "unindexed"}
        self.assertIn("concepts/cutover.md", unindexed)

        section = re.search(r"^## Concepts\n", index.read_text(encoding="utf-8"),
                            re.M)
        self.assertIsNotNone(
            section, "the shipped index has no section to file a concept under")
        index.write_text(
            index.read_text(encoding="utf-8").replace(
                "## Concepts\n",
                "## Concepts\n\n- [Cutover](concepts/cutover.md) — the window\n",
                1), encoding="utf-8")
        self.assertNotIn("concepts/cutover.md",
                         {f.path for f in check_all(self.root, self.TODAY)
                          if f.kind == "unindexed"})

    def test_an_already_installed_memory_is_told_what_it_is_missing(self):
        """The half of a schema change a seed cannot deliver.

        `bootstrap` copies in what is missing and never overwrites, which is
        right — the index belongs to the user. It also means a memory created
        before a page type was added keeps the sections it was created with,
        so adding `## Concepts` to `profile/seed/index.md` reaches new
        installs and nobody else. The people most likely to have content are
        exactly the ones who would never receive it.

        Reported rather than rewritten: the repair job adds the heading,
        which is the path that already exists for a memory that has drifted
        from its contract. Added where `schema.md` orders it, not merely
        appended — `## Concepts` after `## Attention` clears
        `index-section-missing` and fails `index-out-of-order` instead, which
        is not a repair.
        """
        # The shipped fixture index is already the "before" state: it was
        # written when the order had no `## Concepts`, which is the same
        # position every installed memory is in. `## Attention` is the only
        # existing section that schema order puts after `## Concepts`, so
        # that is where the heading belongs.
        index = self.root / "index.md"
        self.assertNotIn("## Concepts", index.read_text(encoding="utf-8"))
        (self.root / "concepts").mkdir(exist_ok=True)
        (self.root / "concepts" / "cutover.md").write_text(
            "---\ntype: concept\nupdated: 2026-08-20\n---\n\n# Cutover\n",
            encoding="utf-8")

        found = {f.kind for f in check_all(self.root, self.TODAY)}
        self.assertIn("index-section-missing", found)

        index.write_text(
            index.read_text(encoding="utf-8").replace(
                "## Attention",
                "## Concepts\n\n- [Cutover](concepts/cutover.md) — the"
                " window\n\n## Attention", 1), encoding="utf-8")
        after = {f.kind for f in check_all(self.root, self.TODAY)}
        self.assertNotIn("index-section-missing", after)
        self.assertNotIn("unindexed", after)
        self.assertNotIn("index-out-of-order", after)
        self.assertNotIn("index-misfiled", after)

    def test_bootstrap_does_not_reach_an_existing_index(self):
        """Stated as a fact this file depends on rather than a wish.

        If bootstrap ever did overwrite, the check above would be redundant
        and this test would say so by failing.
        """
        import os
        import select_memory
        home = Path(tempfile.mkdtemp())
        previous = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(home)
        try:
            mem = select_memory.memory_root()
            mem.mkdir(parents=True, exist_ok=True)
            (mem / "index.md").write_text(
                "---\ntype: index\nupdated: 2026-08-01\n---\n\n"
                "# Memory\n\n## People\n", encoding="utf-8")
            (mem / "log.md").write_text("# Log\n", encoding="utf-8")
            select_memory.bootstrap(mem)
            self.assertNotIn("## Concepts",
                             (mem / "index.md").read_text(encoding="utf-8"))
        finally:
            if previous is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous

    def test_a_type_with_no_pages_yet_is_not_a_finding(self):
        """An empty section is not owed until there is something to file.

        Requiring one for every validated type reported three findings on the
        shipped fixture, which is noise a user cannot clear by doing anything
        right.
        """
        self.assertNotIn("index-section-missing", self.kinds())

    def test_the_index_order_and_the_shipped_seed_agree(self):
        """They are two statements of one rule, and the seed is what a fresh
        install actually gets."""
        recipe = HERE.parents[1]
        order = re.search(r"Sections, in this order: (.+?)\.",
                          (recipe / "profile" / "schema.md").read_text(
                              encoding="utf-8"), re.S).group(1)
        declared = re.findall(r"## (\w+)", order)
        shipped = re.findall(r"^## (\w+)",
                             (recipe / "profile" / "seed" / "index.md").read_text(
                                 encoding="utf-8"), re.M)
        self.assertEqual(declared, shipped)
        # Derived rather than named, so the next page type that gains a
        # required-fields entry and no index section fails here too.
        typed = {k.capitalize() for k in memory_check.REQUIRED_FIELDS}
        self.assertEqual(
            typed - set(declared), set(),
            "a validated page type has no section to be indexed under")


class TestNoInstructionAsksAnUnanswerableQuestion(unittest.TestCase):
    """The store holds inbound messages only.

    `memory-writing` told the agent to write a page when the user "has
    exchanged messages with them in both directions", and not to write one for
    "senders the user never replies to". Neither can be evaluated: the mail
    collector reads the inbox and the Slack one drops every message the user
    wrote, so the outbound half is not in the store. Both rules degraded
    silently — and the admission clause that was lost is the one that best
    separates a colleague from a system that only sends notifications.
    """

    SKILL = (HERE.parents[1] / "profile" / "skills" / "memory-writing"
             / "SKILL.md")

    # Anything that presumes the user's own traffic. Spellings, not concepts,
    # so this is a floor and not a proof — see the test below it, which is
    # the one that reads the evidence rather than the words.
    OUTBOUND = ("both directions", "never replies", "the user replied",
                "user's reply", "replied to", "user sent", "user wrote",
                "sent by the user", "responded to them")

    def rules_block(self):
        """The admission rules, which is where an unanswerable test does
        damage. Prose elsewhere may legitimately discuss what is missing."""
        text = self.SKILL.read_text(encoding="utf-8")
        start = text.index("Write a page when:")
        return text[start:text.index("\n## ", start)]

    def test_no_admission_rule_depends_on_what_the_user_sent(self):
        block = self.rules_block().lower()
        for phrase in self.OUTBOUND:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, block)

    def test_the_rules_only_name_values_the_store_can_hold(self):
        """The property the phrase list above only approximates.

        The defect was a rule about data that does not exist. A phrase list
        catches the two spellings that shipped; this catches the class, by
        checking that every `addressing` value the rules reason about is one
        the schema permits and the normalizer produces. A rule about
        `addressing: urgent` would be exactly as unanswerable as a rule about
        replies, and would read just as plausibly.
        """
        recipe = HERE.parents[1]
        allowed = set(re.findall(
            r"addressing\s+TEXT CHECK \(addressing IN \(([^)]+)\)",
            (recipe / "profile" / "scripts" / "schema.sql").read_text(
                encoding="utf-8"))[0].replace("'", "").split(","))
        allowed = {v.strip() for v in allowed}
        self.assertEqual(allowed, {"direct", "mentioned", "broadcast"})

        quoted = set(re.findall(r"`(\w+)`", self.rules_block()))
        # Only the ones that look like an addressing value are in scope; the
        # rules may quote other things.
        used = quoted & (allowed | {"urgent", "reply", "replied", "sent",
                                    "outbound", "answered"})
        self.assertTrue(used, "the rules stopped naming any addressing value")
        self.assertLessEqual(used, allowed,
                             f"rules reason about values the store cannot"
                             f" hold: {sorted(used - allowed)}")

    def test_the_rules_say_direct_is_not_sufficient_on_its_own(self):
        """Mail yields only `direct` or `broadcast` — `mentioned` is Slack's.

        So on the mail side the rewrite is a To-versus-not test, and a
        machine that addresses the user by name passes it exactly as a
        colleague does. The old rules excluded that traffic twice over; the
        new ones have to say so themselves rather than rely on a value mail
        never produces.
        """
        recipe = HERE.parents[1]
        graph = re.search(r"def graph_message_to_item.*?\n    return \{",
                          (recipe / "profile" / "scripts" / "normalize.py"
                           ).read_text(encoding="utf-8"), re.S).group(0)
        produced = set(re.findall(r'addressing = "(\w+)"', graph))
        self.assertEqual(produced, {"direct", "broadcast"},
                         "mail's addressing values changed; the caveat in the"
                         " skill was written against these")

        text = self.SKILL.read_text(encoding="utf-8")
        self.assertIn("never `mentioned`", text)
        self.assertIn("necessary condition", text)
        self.assertIn("Anything automated, whatever its `addressing`",
                      self.rules_block())

    def test_the_replacement_uses_a_field_the_selector_supplies(self):
        """`addressing` is on every interaction the selector hands over, so
        the agent can answer with it. A rule is only as good as the evidence
        the payload carries."""
        text = self.SKILL.read_text(encoding="utf-8")
        self.assertIn("addressing", text)
        selector = (HERE.parents[1] / "profile" / "scripts"
                    / "select_memory.py").read_text(encoding="utf-8")
        self.assertIn('"addressing": addressing', selector)

    def test_the_limitation_is_stated_rather_than_left_implicit(self):
        """An agent that does not know the outbound half is missing will
        reasonably try to infer it."""
        text = self.SKILL.read_text(encoding="utf-8")
        self.assertIn("inbound messages only", text)

    def test_the_third_rule_does_not_compare_against_an_unsupplied_identity(self):
        """"Names the user" asked the agent to check a message's text
        against the user's own name or address, and the selector supplies
        neither per interaction — there is nothing to compare the text
        against. The rule is bound to `addressing` and the message's own
        text only, the same discipline the other two rules already follow.
        """
        block = self.rules_block().lower()
        self.assertNotIn("interactions you were given names the user", block)
        self.assertIn("gives you no\n  name or address for the user to compare", block)


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

    def test_the_clash_does_not_say_which_page_to_delete(self):
        """The two situations that wear this clash want opposite repairs, and
        nothing on disk tells them apart.

        A merge that copied the content across and left the emptied page
        behind produces a page whose identities are all on another one. So
        does a page that wrongly claims somebody else's address — and there
        the "extra" page is the correct one. A subset test calls both a
        leftover and sends the repair job to delete a real page. The evidence
        that separates them is the confirmed link, which lives in the store
        and not here, so this reports and refuses to choose.
        """
        self._set_identities(self.person, "email:sam.ruiz@example.com",
                             "slack:U01SAM", "email:dana.okoro@example.com")
        findings = check_identity(self.root)
        self.assertEqual([f.kind for f in findings], ["duplicate-identity"])
        detail = findings[0].detail
        self.assertIn("somebody else", detail)
        self.assertIn("left the emptied page behind", detail)
        self.assertNotIn("delete", detail)

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
