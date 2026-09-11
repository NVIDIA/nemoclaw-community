# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A user's customization to a shipped skill must survive an update, must
never affect a skill it was not written for, and must survive a crash at
any point this code can actually leave one in.

Every check here goes through the real functions against a real profile
tree in a temp directory, the same discipline `test_select_memory.py`
already uses — no mocking, and no fixture the underlying code cannot
actually produce. Where a crash is simulated, the database row and file
state constructed are exactly what the real two-phase write sequence
would have left at that exact point — not an arbitrary stand-in.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import skill_overrides as so  # noqa: E402


class OverridesCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        (self.home / "skills").mkdir(parents=True)
        self.distribution = Path(tempfile.mkdtemp())
        (self.distribution / "skills").mkdir()
        os.environ["HERMES_HOME"] = str(self.home)

    def tearDown(self):
        os.environ.pop("HERMES_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.distribution, ignore_errors=True)

    def ship(self, name: str, description: str = "A shipped skill.",
            extra: str = "", *, register: bool = True) -> Path:
        """Create a shipped skill, the way `hermes profile install` would
        have just laid one down."""
        skill_dir = self.home / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        text = (f"---\nname: {name}\ndescription: {description}\n---\n\n"
               f"# {name}\n\nDo the thing.\n{extra}")
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
        if register:
            source = self.distribution / "skills" / name / "SKILL.md"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(text, encoding="utf-8")
            so.record_distribution(self.home, self.distribution)
        return skill_dir / "SKILL.md"

    def override_path(self, name: str) -> Path:
        return self.home / "workspace" / "skill-overrides" / "overrides" / name / "SKILL.md"

    def write_override(self, name: str, text: str) -> None:
        path = self.override_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def db_path(self) -> Path:
        return self.home / "workspace" / "skill-overrides" / "state.db"

    def kinds(self, reports):
        return sorted(r.kind for r in reports)


class TestFork(OverridesCase):
    def test_fork_creates_an_override_based_on_the_shipped_version(self):
        shipped = self.ship("inbound-judging")
        report = so.fork_skill(self.home, "inbound-judging")
        self.assertEqual(report.kind, "forked")

        override = self.override_path("inbound-judging").read_text(encoding="utf-8")
        m = re.search(r"^based_on_sha256:\s*([0-9a-f]{64})\s*$", override, re.M)
        self.assertIsNotNone(m, override)
        self.assertEqual(m.group(1), so._sha256(shipped.read_text(encoding="utf-8")))

    def test_fork_of_an_unknown_skill_is_reported_not_created(self):
        report = so.fork_skill(self.home, "does-not-exist")
        self.assertEqual(report.kind, "skipped-unknown-skill")
        self.assertFalse(self.override_path("does-not-exist").exists())

    def test_forking_twice_does_not_overwrite_an_edited_override(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        self.write_override("inbound-judging",
                            self.override_path("inbound-judging")
                            .read_text(encoding="utf-8") + "\nEdited.\n")
        report = so.fork_skill(self.home, "inbound-judging")
        self.assertEqual(report.kind, "skipped-exists")
        self.assertIn("Edited.",
                      self.override_path("inbound-judging").read_text(encoding="utf-8"))

    def test_an_invalid_skill_name_is_refused_before_touching_a_path(self):
        with self.assertRaises(so.InvalidSkillName):
            so.fork_skill(self.home, "../../etc/passwd")

    def test_forking_never_trusts_a_based_on_sha256_the_shipped_text_already_had(self):
        """Shipped content should never legitimately carry this field, but
        if it does — copied from another skill, hand-edited, or simply
        stale — the fork must be based on what is actually live, not on
        what the shipped file claims."""
        self.ship("inbound-judging",
                 extra="\n<!-- based_on_sha256: " + ("0" * 64) + " -->\n")
        shipped_text = (self.home / "skills" / "inbound-judging" / "SKILL.md")
        # Put a foreign claim directly in the frontmatter, not a comment.
        shipped_text.write_text(
            "---\nname: inbound-judging\ndescription: x\n"
            f"based_on_sha256: {'1' * 64}\n---\n\nbody\n", encoding="utf-8")
        real_hash = so._sha256(shipped_text.read_text(encoding="utf-8"))
        (self.distribution / "skills" / "inbound-judging" / "SKILL.md").write_text(
            shipped_text.read_text(encoding="utf-8"), encoding="utf-8")
        so.record_distribution(self.home, self.distribution)

        so.fork_skill(self.home, "inbound-judging")
        override = self.override_path("inbound-judging").read_text(encoding="utf-8")
        m = re.search(r"^based_on_sha256:\s*([0-9a-f]{64})\s*$", override, re.M)
        self.assertEqual(m.group(1), real_hash)


class TestApply(OverridesCase):
    def test_a_valid_override_is_applied(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = (self.override_path("inbound-judging")
                         .read_text(encoding="utf-8") + "\nCustomized.\n")
        self.write_override("inbound-judging", override_text)

        reports = so.apply_overrides(self.home)
        self.assertEqual(self.kinds(reports), ["applied"])
        live = (self.home / "skills" / "inbound-judging" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(live, override_text)

    def test_a_repeated_apply_of_an_unchanged_override_never_reports_stale(self):
        """The regression this reproduces: comparing `based_on_sha256`
        against whatever is live, once live is already the override
        itself, made every override falsely report stale forever after
        its first successful apply."""
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)

        first = so.apply_overrides(self.home)
        second = so.apply_overrides(self.home)
        third = so.apply_overrides(self.home)
        self.assertEqual([r.kind for r in first], ["applied"])
        self.assertEqual([r.kind for r in second], ["applied"])
        self.assertEqual([r.kind for r in third], ["applied"])

    def test_an_invalid_override_is_skipped_and_shipped_content_stands(self):
        shipped_text = self.ship("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", "not even frontmatter\n")

        reports = so.apply_overrides(self.home)
        self.assertEqual(self.kinds(reports), ["skipped-invalid"])
        live = (self.home / "skills" / "inbound-judging" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(live, shipped_text)

    def test_a_name_mismatch_is_invalid(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        bad = self.override_path("inbound-judging").read_text(encoding="utf-8").replace(
            "name: inbound-judging", "name: some-other-skill")
        self.write_override("inbound-judging", bad)

        reports = so.apply_overrides(self.home)
        self.assertEqual(reports[0].kind, "skipped-invalid")
        self.assertIn("name", reports[0].detail)

    def test_a_malformed_hash_is_invalid(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        bad = re.sub(r"based_on_sha256:.*",
                     "based_on_sha256: banana", self.override_path("inbound-judging")
                     .read_text(encoding="utf-8"))
        self.write_override("inbound-judging", bad)

        reports = so.apply_overrides(self.home)
        self.assertEqual(reports[0].kind, "skipped-invalid")
        self.assertIn("sha256", reports[0].detail)

    def test_a_well_formed_but_never_observed_base_is_invalid(self):
        self.ship("inbound-judging")
        fake_hash = "0" * 64
        self.write_override("inbound-judging",
                            "---\nname: inbound-judging\ndescription: x\n"
                            f"based_on_sha256: {fake_hash}\n---\n\nbody\n")
        reports = so.apply_overrides(self.home)
        self.assertEqual(reports[0].kind, "skipped-invalid")
        self.assertIn("never observed", reports[0].detail)

    def test_a_based_on_hash_observed_only_for_another_skill_is_rejected(self):
        self.ship("inbound-judging")
        self.ship("memory-writing")
        so.fork_skill(self.home, "inbound-judging")
        foreign_hash = so._sha256(
            (self.home / "skills" / "inbound-judging" / "SKILL.md")
            .read_text(encoding="utf-8"))

        self.write_override(
            "memory-writing",
            "---\nname: memory-writing\ndescription: x\n"
            f"based_on_sha256: {foreign_hash}\n---\n\nbody\n")

        reports = so.apply_overrides(self.home)
        by_skill = {r.skill: r for r in reports}
        self.assertEqual(by_skill["memory-writing"].kind, "skipped-invalid")
        self.assertIn("never observed for this skill",
                      by_skill["memory-writing"].detail)
        live = (self.home / "skills" / "memory-writing" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("based_on_sha256: " + foreign_hash, live)

    def test_a_stale_override_is_refused_not_silently_applied(self):
        """The regression this reproduces: a `based_on_sha256` mismatch
        used to be reported as 'applied-stale' while still overwriting
        live content with the stale override — meaning a newer shipped
        safety or correctness fix could be silently reverted by content
        nobody had reviewed against it. Apply must refuse instead,
        leaving whatever is currently live untouched."""
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)

        # Shipped content changes — simulating a real `hermes profile
        # update`, not going through this module at all.
        newer_live_path = self.ship("inbound-judging", description="A newer shipped skill.")
        newer_shipped_text = newer_live_path.read_text(encoding="utf-8")

        reports = so.apply_overrides(self.home)
        self.assertEqual(reports[0].kind, "skipped-stale")
        live = newer_live_path.read_text(encoding="utf-8")
        self.assertEqual(
            live, newer_shipped_text,
            "a stale override must never overwrite content nobody has "
            "reviewed it against")
        self.assertNotEqual(live, override_text)

    def test_check_reports_without_writing_anything(self):
        shipped_text = self.ship("inbound-judging").read_text(encoding="utf-8")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("inbound-judging", override_text)

        # A change lands after the fork that a real --check run would be
        # asked to look at — if check observed it as a new base, that
        # would be a filesystem write hiding behind a rolled-back
        # transaction.
        self.ship("inbound-judging", description="Changed after the fork.")

        with sqlite3.connect(self.db_path()) as conn:
            before = conn.execute("SELECT COUNT(*) FROM base_observations").fetchone()[0]
        bases_dir = self.home / "workspace" / "skill-overrides" / "bases"
        blobs_before = sorted(p.name for p in bases_dir.iterdir()) if bases_dir.exists() else []

        reports = so.check_overrides(self.home)
        self.assertEqual(self.kinds(reports), ["skipped-stale"])

        live = (self.home / "skills" / "inbound-judging" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotEqual(live, override_text, "check must never touch the live skill")

        with sqlite3.connect(self.db_path()) as conn:
            after = conn.execute("SELECT COUNT(*) FROM base_observations").fetchone()[0]
        self.assertEqual(before, after, "check must never record a new base observation")
        blobs_after = sorted(p.name for p in bases_dir.iterdir()) if bases_dir.exists() else []
        self.assertEqual(blobs_before, blobs_after, "check must never write a base blob to disk")

    def test_check_does_not_trigger_reconciliation(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)  # leaves a 'complete' row

        with sqlite3.connect(self.db_path()) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('inbound-judging', 'apply', 'pending', 'x', 'y')")

        reports = so.check_overrides(self.home)

        self.assertEqual([r.kind for r in reports], ["blocked"])

        with sqlite3.connect(self.db_path()) as conn:
            status = conn.execute(
                "SELECT status FROM override_operations WHERE expected_before_hash='x'"
            ).fetchone()[0]
        self.assertEqual(status, "pending", "--check must never run reconcile")

    def test_check_blocks_on_a_pending_remove_that_apply_would_refuse(self):
        live_path = self.ship("inbound-judging")
        shipped_text = live_path.read_text(encoding="utf-8")
        so.fork_skill(self.home, "inbound-judging")
        override_text = (self.override_path("inbound-judging")
                         .read_text(encoding="utf-8") + "\nCustomized.\n")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)

        with sqlite3.connect(self.db_path()) as conn:
            latest = conn.execute(
                "SELECT content_hash FROM base_observations"
                " WHERE skill_name = ? ORDER BY observation_id DESC LIMIT 1",
                ("inbound-judging",)).fetchone()[0]
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash,"
                " expected_after_hash) VALUES (?, 'remove', 'pending', ?, ?)",
                ("inbound-judging", so._sha256(override_text), latest))

        reports = so.check_overrides(self.home)

        self.assertEqual([r.kind for r in reports], ["blocked"])
        self.assertIn("previous remove operation", reports[0].detail)
        self.write_override("inbound-judging", "invalid override\n")
        self.assertEqual(
            [r.kind for r in so.check_overrides(self.home)], ["blocked"],
            "a malformed override must not hide the operation that must be "
            "reconciled before it")
        self.write_override("inbound-judging", override_text)
        self.assertEqual(so.main(["--check"]), 1)
        self.assertEqual(live_path.read_text(encoding="utf-8"), override_text)

        # The other recoverable crash point: the remove's file write landed,
        # but its database completion and override-file deletion did not.
        live_path.write_text(shipped_text, encoding="utf-8")
        landed_reports = so.check_overrides(self.home)
        self.assertEqual([r.kind for r in landed_reports], ["blocked"])
        self.assertIn("bookkeeping is incomplete", landed_reports[0].detail)
        self.assertEqual(live_path.read_text(encoding="utf-8"), shipped_text)

        # Remove both filesystem entries that could otherwise enumerate this
        # skill. The pending-operation table must be a check source in its own
        # right, just as it is for reset recovery.
        self.override_path("inbound-judging").unlink()
        self.override_path("inbound-judging").parent.rmdir()
        real_list_skill_names = so._list_skill_names
        so._list_skill_names = lambda root: []
        try:
            pending_only_reports = so.check_overrides(self.home)
        finally:
            so._list_skill_names = real_list_skill_names
        self.assertEqual(
            [r.kind for r in pending_only_reports], ["blocked"])
        with sqlite3.connect(self.db_path()) as conn:
            self.assertEqual(conn.execute(
                "SELECT status FROM override_operations"
                " WHERE op_type = 'remove' ORDER BY id DESC LIMIT 1"
            ).fetchone()[0], "pending")

    def test_skills_with_no_override_are_left_alone(self):
        self.ship("inbound-judging")
        self.ship("memory-writing")
        so.fork_skill(self.home, "inbound-judging")
        self.write_override(
            "inbound-judging",
            self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n")

        reports = so.apply_overrides(self.home)
        self.assertEqual(self.kinds(reports), ["applied"])
        self.assertEqual([r.skill for r in reports], ["inbound-judging"])

    def test_ticking_repeatedly_over_an_unoverridden_skill_does_not_grow_its_history(self):
        self.ship("inbound-judging")
        so.apply_overrides(self.home)
        with sqlite3.connect(self.db_path()) as conn:
            after_first = conn.execute(
                "SELECT COUNT(*) FROM base_observations WHERE skill_name=?",
                ("inbound-judging",)).fetchone()[0]
        self.assertEqual(after_first, 1)

        for _ in range(5):
            so.apply_overrides(self.home)

        with sqlite3.connect(self.db_path()) as conn:
            after_many = conn.execute(
                "SELECT COUNT(*) FROM base_observations WHERE skill_name=?",
                ("inbound-judging",)).fetchone()[0]
        self.assertEqual(after_many, 1,
                         "unchanged content on an unoverridden skill must not "
                         "grow the observation log")


class TestIsolationBetweenSkills(OverridesCase):
    """One skill's problem must never touch another's outcome or state."""

    def test_an_invalid_override_on_one_skill_does_not_block_another(self):
        self.ship("inbound-judging")
        self.ship("memory-writing")
        so.fork_skill(self.home, "inbound-judging")
        so.fork_skill(self.home, "memory-writing")

        self.write_override("inbound-judging", "garbage, no frontmatter\n")
        valid = self.override_path("memory-writing").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("memory-writing", valid)

        reports = so.apply_overrides(self.home)
        by_skill = {r.skill: r.kind for r in reports}
        self.assertEqual(by_skill["inbound-judging"], "skipped-invalid")
        self.assertEqual(by_skill["memory-writing"], "applied")
        live = (self.home / "skills" / "memory-writing" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(live, valid)

    def test_a_genuine_exception_reading_one_skill_does_not_abort_another(self):
        """Not a validation failure — a real exception (invalid UTF-8)
        raised while this module is in the middle of processing one
        skill. Proves the isolation holds even when a skill's processing
        does not return normally at all, not just when it returns a
        `skipped-*` report."""
        self.ship("inbound-judging")
        self.ship("memory-writing")
        so.fork_skill(self.home, "memory-writing")
        valid = self.override_path("memory-writing").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("memory-writing", valid)

        (self.home / "skills" / "inbound-judging" / "SKILL.md").write_bytes(
            b"\xff\xfe not valid utf-8")

        reports = so.apply_overrides(self.home)
        by_skill = {r.skill: r.kind for r in reports}
        self.assertEqual(by_skill["inbound-judging"], "error")
        self.assertEqual(by_skill["memory-writing"], "applied")
        live = (self.home / "skills" / "memory-writing" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(live, valid)

        with sqlite3.connect(self.db_path()) as conn:
            applied = dict(conn.execute(
                "SELECT skill_name, applied_hash FROM applied_overrides").fetchall())
        self.assertIn("memory-writing", applied)
        self.assertNotIn("inbound-judging", applied,
                         "a skill that errored must leave no committed row behind")

    def test_removing_one_skills_override_does_not_touch_another(self):
        self.ship("inbound-judging")
        self.ship("memory-writing")
        so.fork_skill(self.home, "inbound-judging")
        so.fork_skill(self.home, "memory-writing")
        override_a = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nA\n"
        override_b = self.override_path("memory-writing").read_text(encoding="utf-8") + "\nB\n"
        self.write_override("inbound-judging", override_a)
        self.write_override("memory-writing", override_b)
        so.apply_overrides(self.home)

        so.remove_override(self.home, "inbound-judging")

        # memory-writing's override must still be there and still applied.
        self.assertTrue(self.override_path("memory-writing").exists())
        live_b = (self.home / "skills" / "memory-writing" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(live_b, override_b)


class TestRemove(OverridesCase):
    def test_remove_with_no_override_present_touches_nothing(self):
        """Cron observes every skill's shipped content whether or not it
        has an override, so a base exists even for a skill nobody ever
        customized. --remove on it must refuse, not roll it back."""
        shipped_text = self.ship("inbound-judging").read_text(encoding="utf-8")
        so.apply_overrides(self.home)  # observes the skill; no override exists

        report = so.remove_override(self.home, "inbound-judging")
        self.assertEqual(report.kind, "skipped-no-override")
        live = (self.home / "skills" / "inbound-judging" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(live, shipped_text)

    def test_remove_observes_a_newer_shipped_version_itself_before_restoring(self):
        """The regression this reproduces: remove used to ask only what
        the last apply/check tick had already observed, so a real Hermes
        update landing after that tick but before --remove ran got
        silently discarded — restored straight over with an older,
        already-known base nothing had a chance to update. Reproduced
        here with NO apply/check call in between shipping B and calling
        remove, so only remove's own observation step can be what saves
        it."""
        self.ship("inbound-judging", description="Version A.")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)  # live is now the override, based on A

        # A real `hermes profile update` lands — nothing has looked at the
        # shipped tree since, so nothing has observed B yet.
        self.ship("inbound-judging", description="Version B.")

        report = so.remove_override(self.home, "inbound-judging")
        self.assertEqual(report.kind, "removed")
        live = (self.home / "skills" / "inbound-judging" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Version B.", live,
                      "remove must observe and restore the version actually "
                      "shipped, not an older one nothing had captured yet")
        self.assertNotIn("Version A.", live)

    def test_remove_restores_the_latest_observed_shipped_version_not_the_fork_point(self):
        self.ship("inbound-judging", description="Version A.")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)

        # A newer shipped version lands (a real update), observed the next
        # time apply runs even though this override is still forked from A.
        self.ship("inbound-judging", description="Version B.")
        so.apply_overrides(self.home)  # observes B, re-applies the override (stale)

        report = so.remove_override(self.home, "inbound-judging")
        self.assertEqual(report.kind, "removed")
        live = (self.home / "skills" / "inbound-judging" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Version B.", live)
        self.assertNotIn("Version A.", live)

    def test_remove_with_no_observation_at_all_leaves_the_override_in_place(self):
        """`remove` now observes live content itself before restoring
        anything, so as long as the skill still exists there is always
        something to observe and restore to — this case only remains
        reachable when the skill is gone too, with truly nothing on
        either side for remove's own observation step to find."""
        self.ship("inbound-judging", register=False)
        import shutil
        shutil.rmtree(self.home / "skills" / "inbound-judging")
        # A hand-placed override with no prior --fork/--apply ever having
        # observed this skill: `base_observations` has no row for it.
        self.write_override(
            "inbound-judging",
            f"---\nname: inbound-judging\ndescription: x\n"
            f"based_on_sha256: {'0' * 64}\n---\n\nbody\n")

        report = so.remove_override(self.home, "inbound-judging")
        self.assertEqual(report.kind, "skipped-no-base")
        self.assertTrue(self.override_path("inbound-judging").exists())

    def test_remove_with_a_retained_row_but_missing_blob_leaves_the_override_in_place(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        # Corrupt the retained blob without going through this module —
        # the database still remembers it was observed, but the content
        # itself is gone.
        import shutil
        shutil.rmtree(self.home / "workspace" / "skill-overrides" / "bases")

        report = so.remove_override(self.home, "inbound-judging")
        self.assertEqual(report.kind, "skipped-missing-base")
        self.assertTrue(self.override_path("inbound-judging").exists())

    def test_remove_on_a_skill_upstream_deleted_still_restores_it(self):
        """A deliberate contract, not an oversight: an override existing at
        all is why this restores at all, regardless of whether Hermes
        currently ships that skill. See the comment in remove_override."""
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)

        import shutil
        shutil.rmtree(self.home / "skills" / "inbound-judging")

        report = so.remove_override(self.home, "inbound-judging")
        self.assertEqual(report.kind, "removed")
        self.assertTrue((self.home / "skills" / "inbound-judging" / "SKILL.md").is_file())
        self.assertFalse(self.override_path("inbound-judging").exists())


class TestCrashRecovery(OverridesCase):
    """Every state constructed here is exactly what the real two-phase
    write sequence in `_apply_one_skill`/`remove_override` would have left
    on disk and in the database at that precise point — not an arbitrary
    stand-in a real crash could never actually produce."""

    def _pending_apply_row(self, skill_name: str, before_hash: str, after_hash: str) -> None:
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES (?, 'apply', 'pending', ?, ?)",
                (skill_name, before_hash, after_hash))

    def test_a_crash_before_the_file_write_is_retried_not_skipped(self):
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("inbound-judging", override_text)

        # The exact state phase 1 leaves durable: the pending row committed,
        # the file untouched (still the shipped content).
        before_hash = so._sha256(live_path.read_text(encoding="utf-8"))
        after_hash = so._sha256(override_text)
        self._pending_apply_row("inbound-judging", before_hash, after_hash)

        reports = so.reconcile(self.home)
        self.assertEqual([r.kind for r in reports], ["reconciled-retry"])

        # And the next real apply run redoes the write correctly.
        so.apply_overrides(self.home)
        live = live_path.read_text(encoding="utf-8")
        self.assertEqual(live, override_text)

    def test_a_crash_after_the_file_write_is_completed_not_repeated(self):
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("inbound-judging", override_text)

        before_hash = so._sha256(live_path.read_text(encoding="utf-8"))
        after_hash = so._sha256(override_text)
        self._pending_apply_row("inbound-judging", before_hash, after_hash)
        # The exact state phase 2 would find: the write already landed.
        live_path.write_text(override_text, encoding="utf-8")

        reports = so.reconcile(self.home)
        self.assertEqual([r.kind for r in reports], ["reconciled-complete"])

        with sqlite3.connect(self.db_path()) as conn:
            status = conn.execute(
                "SELECT status FROM override_operations WHERE skill_name=?",
                ("inbound-judging",)).fetchone()[0]
            applied_hash = conn.execute(
                "SELECT applied_hash FROM applied_overrides WHERE skill_name=?",
                ("inbound-judging",)).fetchone()[0]
        self.assertEqual(status, "complete")
        self.assertEqual(applied_hash, after_hash,
                         "reconcile must finish the manifest update a crash skipped")

    def test_a_crash_after_a_remove_write_finishes_the_orphaned_override_cleanup(self):
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)

        with sqlite3.connect(self.db_path()) as conn:
            latest = conn.execute(
                "SELECT content_hash FROM base_observations WHERE skill_name=?"
                " ORDER BY observation_id DESC LIMIT 1", ("inbound-judging",)
            ).fetchone()[0]
        base_text = (self.home / "workspace" / "skill-overrides" / "bases"
                    / latest / "SKILL.md").read_text(encoding="utf-8")

        before_hash = so._sha256(live_path.read_text(encoding="utf-8"))
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('inbound-judging', 'remove', 'pending', ?, ?)",
                (before_hash, latest))
        # The exact state a crash between the two remove writes leaves: the
        # base restored, the override file not yet unlinked.
        live_path.write_text(base_text, encoding="utf-8")
        self.assertTrue(self.override_path("inbound-judging").exists())

        reports = so.reconcile(self.home)
        self.assertEqual([r.kind for r in reports], ["reconciled-complete"])
        self.assertFalse(self.override_path("inbound-judging").exists(),
                         "reconcile must finish deleting the orphaned override")
        with sqlite3.connect(self.db_path()) as conn:
            row = conn.execute(
                "SELECT 1 FROM applied_overrides WHERE skill_name=?",
                ("inbound-judging",)).fetchone()
        self.assertIsNone(row)

        # A later cron apply must not resurrect the override that was
        # already correctly removed.
        so.apply_overrides(self.home)
        self.assertEqual(live_path.read_text(encoding="utf-8"), base_text)

    def test_diverged_content_is_left_untouched_and_blocks_further_automation(self):
        """The regression this also has to catch, not just 'the final
        report says blocked': `_apply_one_skill` used to call
        `_observe_if_new` on live content before ever reaching the claim
        check that discovers this skill is blocked — so the diverged,
        unrecognized content got durably recorded as a trusted new
        shipped base anyway, directly contradicting reconciliation's own
        'left untouched' report. Checking the observation count, not just
        the final live file content, is what actually proves that
        doesn't happen."""
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("inbound-judging", override_text)

        before_hash = so._sha256(live_path.read_text(encoding="utf-8"))
        after_hash = so._sha256(override_text)
        self._pending_apply_row("inbound-judging", before_hash, after_hash)
        # Something outside this module's cooperating writers changed the
        # file to a third value — neither the expected before nor after.
        live_path.write_text("something else entirely\n", encoding="utf-8")

        reports = so.reconcile(self.home)
        self.assertEqual([r.kind for r in reports], ["reconciled-diverged"])
        self.assertEqual(live_path.read_text(encoding="utf-8"), "something else entirely\n")

        with sqlite3.connect(self.db_path()) as conn:
            observations_before = conn.execute(
                "SELECT COUNT(*) FROM base_observations"
                " WHERE skill_name='inbound-judging'").fetchone()[0]

        blocked = so.apply_overrides(self.home)
        self.assertEqual([r.kind for r in blocked], ["blocked"])
        self.assertEqual(live_path.read_text(encoding="utf-8"), "something else entirely\n")

        with sqlite3.connect(self.db_path()) as conn:
            observations_after = conn.execute(
                "SELECT COUNT(*) FROM base_observations"
                " WHERE skill_name='inbound-judging'").fetchone()[0]
        self.assertEqual(
            observations_after, observations_before,
            "a blocked, diverged skill must not gain a new retained-base "
            "observation for the very content that made it diverged — "
            "that would canonize unrecognized content as a trusted "
            "shipped base despite being 'left untouched'")

    def test_a_directory_where_the_skill_file_should_be_is_diverged_not_abandoned(self):
        """A confirmed absence and 'something unreadable sits here now' are
        different situations — only the first is safe to clear a pending
        record over. A directory is neither the expected before content,
        the expected after content, nor a genuine absence."""
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("inbound-judging", override_text)

        before_hash = so._sha256(live_path.read_text(encoding="utf-8"))
        after_hash = so._sha256(override_text)
        self._pending_apply_row("inbound-judging", before_hash, after_hash)
        live_path.unlink()
        live_path.mkdir()

        reports = so.reconcile(self.home)
        self.assertEqual([r.kind for r in reports], ["reconciled-diverged"])
        with sqlite3.connect(self.db_path()) as conn:
            status = conn.execute(
                "SELECT status FROM override_operations"
                " WHERE skill_name='inbound-judging'").fetchone()[0]
        self.assertEqual(status, "pending",
                         "a directory sitting where the skill file should "
                         "be must never be treated as a confirmed absence "
                         "safe to abandon")

    def test_a_reconcile_error_on_one_skill_does_not_block_reconciling_another(self):
        live_a = self.ship("inbound-judging")
        live_b = self.ship("memory-writing")
        so.fork_skill(self.home, "inbound-judging")
        so.fork_skill(self.home, "memory-writing")
        override_a = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nA\n"
        override_b = self.override_path("memory-writing").read_text(encoding="utf-8") + "\nB\n"
        self.write_override("inbound-judging", override_a)
        self.write_override("memory-writing", override_b)

        self._pending_apply_row("inbound-judging",
                               so._sha256(live_a.read_text(encoding="utf-8")),
                               so._sha256(override_a))
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('memory-writing', 'apply', 'pending', ?, ?)",
                (so._sha256(live_b.read_text(encoding="utf-8")), so._sha256(override_b)))

        # A lands its write (phase-2 not yet committed); B's directory gets
        # replaced by a symlink out of the profile, so reading it is unsafe.
        live_a.write_text(override_a, encoding="utf-8")
        import shutil
        shutil.rmtree(self.home / "skills" / "memory-writing")
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (self.home / "skills" / "memory-writing").symlink_to(outside)

        reports = so.reconcile(self.home)
        by_skill = {r.skill: r.kind for r in reports}
        self.assertEqual(by_skill["inbound-judging"], "reconciled-complete")
        self.assertEqual(by_skill["memory-writing"], "reconciled-error")

    def test_remove_undoes_a_hand_deleted_override_backed_by_a_pending_apply(self):
        """The regression this reproduces: `_remove_override_core`'s gate
        was extended to recognize a still-pending apply as active state
        to restore, but `remove_override()` called directly (as opposed
        to through `main()`, which already reconciles first) used to
        report 'skipped-no-override' for exactly this crash state —
        'success' while leaving the customization live and undoing
        nothing, because `_claim_operation` would find the pending row's
        `expected_before_hash` no longer matched live content and refuse
        to proceed even once the gate itself was fixed to recognize the
        state existed."""
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n"
        shipped_text = live_path.read_text(encoding="utf-8")

        before_hash = so._sha256(shipped_text)
        after_hash = so._sha256(override_text)
        self._pending_apply_row("inbound-judging", before_hash, after_hash)
        # The exact state a crash between apply's file write and its
        # completion commit leaves — live already holds the override, a
        # pending row expects exactly this write's result, no
        # applied_overrides row yet — with the override file itself also
        # gone, hand-deleted after the crash.
        live_path.write_text(override_text, encoding="utf-8")
        self.override_path("inbound-judging").unlink()

        report = so.remove_override(self.home, "inbound-judging")
        self.assertEqual(report.kind, "removed")
        self.assertEqual(live_path.read_text(encoding="utf-8"), shipped_text)
        with sqlite3.connect(self.db_path()) as conn:
            applied = conn.execute(
                "SELECT 1 FROM applied_overrides WHERE skill_name=?",
                ("inbound-judging",)).fetchone()
            pending = conn.execute(
                "SELECT 1 FROM override_operations"
                " WHERE skill_name=? AND status != 'complete'",
                ("inbound-judging",)).fetchone()
        self.assertIsNone(applied, "the applied row must be cleared, not "
                          "left describing content that no longer exists "
                          "anywhere")
        self.assertIsNone(pending, "the crashed apply's own pending row "
                          "must end up resolved, not left dangling")

    def test_forking_a_hand_deleted_applied_override_produces_one_the_next_apply_accepts(self):
        """The regression this reproduces: when live content is
        recognized as this feature's own previously applied override
        (its file hand-deleted, the applied row still present),
        `fork_skill` used to fork 'from' that live content anyway,
        embedding its own hash as `based_on_sha256` — a hash never
        recorded in `base_observations` for this skill, so the very next
        `--apply` refused the freshly re-forked override as based on
        something never observed, even though `--fork` itself reported
        success."""
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        shipped_text = live_path.read_text(encoding="utf-8")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)
        self.assertEqual(live_path.read_text(encoding="utf-8"), override_text)

        # Hand-deleted, applied row left behind — live content is still
        # recognized as this feature's own write, just with no file to
        # show for it.
        self.override_path("inbound-judging").unlink()

        report = so.fork_skill(self.home, "inbound-judging")
        self.assertEqual(report.kind, "forked")
        refork_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.assertNotEqual(
            so._frontmatter(refork_text)["based_on_sha256"],
            so._sha256(override_text),
            "the re-forked override must not claim to be based on the "
            "very content it was forked from — that hash was never "
            "observed as a shipped base for this skill")

        # And the point of the whole thing: the next real apply must
        # actually succeed against it, not refuse it as never-observed.
        reports = so.apply_overrides(self.home)
        self.assertEqual([r.kind for r in reports], ["applied"])
        self.assertEqual(live_path.read_text(encoding="utf-8"), refork_text)

    def test_fork_refuses_while_a_landed_remove_is_still_pending(self):
        """The regression this reproduces: a pending `remove` whose
        write already landed (live restored to base, override file
        already unlinked) but not yet marked complete used to let
        `fork_skill()` create a brand new override anyway. The next
        reconciliation, seeing that remove as landed, unconditionally
        unlinks whatever override file exists at that exact path —
        destroying the one `--fork` had just created for a completely
        unrelated purpose. `--fork` must refuse instead."""
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)

        with sqlite3.connect(self.db_path()) as conn:
            latest = conn.execute(
                "SELECT content_hash FROM base_observations WHERE skill_name=?"
                " ORDER BY observation_id DESC LIMIT 1", ("inbound-judging",)
            ).fetchone()[0]
        base_text = (self.home / "workspace" / "skill-overrides" / "bases"
                    / latest / "SKILL.md").read_text(encoding="utf-8")

        before_hash = so._sha256(live_path.read_text(encoding="utf-8"))
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('inbound-judging', 'remove', 'pending', ?, ?)",
                (before_hash, latest))
        # The exact state a crash between remove's two writes leaves,
        # once both have actually landed: base restored, override file
        # already unlinked, only the completion commit still missing.
        live_path.write_text(base_text, encoding="utf-8")
        self.override_path("inbound-judging").unlink()

        report = so.fork_skill(self.home, "inbound-judging")
        self.assertEqual(report.kind, "blocked")
        self.assertFalse(
            self.override_path("inbound-judging").exists(),
            "a refused fork must not create an override that a later "
            "reconciliation would then silently delete")

    def test_fork_refuses_even_when_the_old_override_file_still_exists(self):
        """The regression this reproduces: the pending-remove checks
        used to run *after* the "an override already exists here"
        check. The natural crash point between remove's two writes —
        `_atomic_write(live_file, base_text)` landing first,
        `override_path.unlink()` not yet run — leaves live content
        already matching the pending remove's `after` hash while the
        *old* override file is still physically present. Checking
        existence first would have hit `skipped-exists` — "edit it
        directly" — without this function ever seeing the pending
        remove hanging over that exact file. A user editing it on that
        advice would have their edits silently deleted the moment
        reconciliation finishes the remove."""
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)

        with sqlite3.connect(self.db_path()) as conn:
            latest = conn.execute(
                "SELECT content_hash FROM base_observations WHERE skill_name=?"
                " ORDER BY observation_id DESC LIMIT 1", ("inbound-judging",)
            ).fetchone()[0]
        base_text = (self.home / "workspace" / "skill-overrides" / "bases"
                    / latest / "SKILL.md").read_text(encoding="utf-8")

        before_hash = so._sha256(live_path.read_text(encoding="utf-8"))
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('inbound-judging', 'remove', 'pending', ?, ?)",
                (before_hash, latest))
        # The exact state the natural crash point between remove's two
        # writes leaves: base already restored, but the override file
        # has NOT been unlinked yet — unlike the sibling test below,
        # which represents the state after both writes landed.
        live_path.write_text(base_text, encoding="utf-8")
        self.assertTrue(self.override_path("inbound-judging").exists())

        report = so.fork_skill(self.home, "inbound-judging")
        self.assertEqual(
            report.kind, "blocked",
            "must not fall through to 'skipped-exists' just because "
            "the old override file is still physically present")
        self.assertEqual(
            self.override_path("inbound-judging").read_text(encoding="utf-8"),
            override_text,
            "the old override file must be left exactly as found")

    def test_fork_refuses_while_a_not_yet_landed_remove_is_still_pending(self):
        """The companion case: a pending `remove` whose write has not
        landed at all (live still holds the old override content, that
        override file already deleted by hand) must also refuse a fresh
        fork — the new override could never be applied while the old
        remove sits unresolved, so reporting `forked` here would promise
        something already unusable."""
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)
        self.assertEqual(live_path.read_text(encoding="utf-8"), override_text)

        with sqlite3.connect(self.db_path()) as conn:
            latest = conn.execute(
                "SELECT content_hash FROM base_observations WHERE skill_name=?"
                " ORDER BY observation_id DESC LIMIT 1", ("inbound-judging",)
            ).fetchone()[0]

        with sqlite3.connect(self.db_path()) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('inbound-judging', 'remove', 'pending', ?, ?)",
                (so._sha256(override_text), latest))
        # Not landed: live is untouched, still the override's own
        # content — but the override file itself is already gone.
        self.override_path("inbound-judging").unlink()

        report = so.fork_skill(self.home, "inbound-judging")
        self.assertEqual(report.kind, "blocked")
        self.assertFalse(self.override_path("inbound-judging").exists())


class TestReconciliation(OverridesCase):
    def test_a_completed_operation_reconciles_to_nothing_left_to_do(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)

        reports = so.reconcile(self.home)
        self.assertEqual(reports, [], "a clean run has nothing to reconcile")

    def test_a_pending_operation_for_a_skill_that_no_longer_exists_is_abandoned(self):
        """Not left pending forever, and not treated as diverged — there
        is nothing left here for either state to protect, and staying
        pending would permanently block a later --remove from restoring
        this skill into a fresh directory."""
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("inbound-judging", override_text)

        before_hash = so._sha256(live_path.read_text(encoding="utf-8"))
        after_hash = so._sha256(override_text)
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('inbound-judging', 'apply', 'pending', ?, ?)",
                (before_hash, after_hash))

        import shutil
        shutil.rmtree(self.home / "skills" / "inbound-judging")

        reports = so.reconcile(self.home)
        self.assertEqual([r.kind for r in reports], ["reconciled-abandoned"])

        with sqlite3.connect(self.db_path()) as conn:
            status = conn.execute(
                "SELECT status FROM override_operations"
                " WHERE skill_name='inbound-judging'").fetchone()[0]
        self.assertEqual(status, "complete")

        # The abandoned record must not block --remove from restoring the
        # skill's override into a fresh directory, per the documented
        # deliberate contract that an existing override always wins.
        report = so.remove_override(self.home, "inbound-judging")
        self.assertEqual(report.kind, "removed")
        self.assertTrue((self.home / "skills" / "inbound-judging" / "SKILL.md").is_file())


class TestVirginProfileCheck(OverridesCase):
    """The common case, every single tick, for every skill nobody has ever
    customized: --check must touch nothing at all, not even to bootstrap
    its own bookkeeping."""

    def test_check_with_no_override_anywhere_creates_no_state(self):
        self.ship("inbound-judging", register=False)
        state_dir = self.home / "workspace" / "skill-overrides"

        reports = so.check_overrides(self.home)

        self.assertEqual(reports, [])
        self.assertFalse(state_dir.exists(),
                         "a virgin profile with nothing to check must gain "
                         "no state tree at all from --check")

    def test_check_with_a_hand_placed_override_but_no_history_reports_without_creating_state(self):
        self.ship("inbound-judging", register=False)
        self.write_override(
            "inbound-judging",
            f"---\nname: inbound-judging\ndescription: x\n"
            f"based_on_sha256: {'0' * 64}\n---\n\nbody\n")
        state_dir = self.home / "workspace" / "skill-overrides"
        db_path = state_dir / "state.db"

        reports = so.check_overrides(self.home)

        self.assertEqual([r.kind for r in reports], ["skipped-invalid"])
        self.assertFalse(db_path.exists(),
                         "checking an override against a history that was "
                         "never created must not create that history")


class TestOrphanedOverrides(OverridesCase):
    """A skill upstream removes must not make its override simply vanish
    from view — the user still has a customization for something that no
    longer exists to apply it to."""

    def test_check_reports_an_override_for_a_skill_no_longer_shipped(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)

        import shutil
        shutil.rmtree(self.home / "skills" / "inbound-judging")

        reports = so.check_overrides(self.home)
        self.assertEqual([r.kind for r in reports], ["orphaned-override"])

    def test_apply_reports_an_override_for_a_skill_no_longer_shipped(self):
        self.ship("inbound-judging")
        self.ship("memory-writing")
        so.fork_skill(self.home, "inbound-judging")
        so.fork_skill(self.home, "memory-writing")
        override_a = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nA\n"
        override_b = self.override_path("memory-writing").read_text(encoding="utf-8") + "\nB\n"
        self.write_override("inbound-judging", override_a)
        self.write_override("memory-writing", override_b)

        import shutil
        shutil.rmtree(self.home / "skills" / "inbound-judging")

        reports = so.apply_overrides(self.home)
        by_skill = {r.skill: r.kind for r in reports}
        self.assertEqual(by_skill["inbound-judging"], "orphaned-override")
        self.assertEqual(by_skill["memory-writing"], "applied")
        live_b = (self.home / "skills" / "memory-writing" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(live_b, override_b)


class TestConcurrencyGuards(OverridesCase):
    """Two processes claiming the same skill's operation record close
    together in time — the claim itself is lock-protected, but the
    filesystem write between claim and completion is not. Completion must
    detect being overtaken rather than silently recording the wrong
    result."""

    def test_a_stale_completion_record_is_refused_rather_than_trusted(self):
        """This is not a live race a second process can actually cause —
        `_apply_one_skill` holds this skill's own lock for its entire
        duration, so nothing else can touch its row in between. It is
        insurance: if the record it is about to complete somehow does not
        say what this call itself just wrote, refuse rather than record a
        result that never happened. Forced directly, since there is no
        real way to reach it through the public API while the lock holds.
        """
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8") + "\nX\n"
        self.write_override("inbound-judging", override_text)

        real_atomic_write = so._atomic_write

        def tampering_atomic_write(path, text):
            # Simulates the record having been corrupted or hand-edited
            # underneath this call — not a second process, which cannot
            # reach this row while this skill's lock is held.
            with sqlite3.connect(self.db_path()) as conn:
                conn.execute(
                    "UPDATE override_operations SET expected_after_hash = ?"
                    " WHERE skill_name = 'inbound-judging' AND status != 'complete'",
                    (so._sha256(text + "\nTampered.\n"),))
            real_atomic_write(path, text)

        so._atomic_write = tampering_atomic_write
        try:
            reports = so.apply_overrides(self.home)
        finally:
            so._atomic_write = real_atomic_write

        self.assertEqual([r.kind for r in reports], ["error"])
        # This process's own write really did land — only the database
        # record was tampered with, not the file.
        self.assertEqual(live_path.read_text(encoding="utf-8"), override_text)

        with sqlite3.connect(self.db_path()) as conn:
            applied = conn.execute(
                "SELECT applied_hash FROM applied_overrides"
                " WHERE skill_name='inbound-judging'").fetchone()
        self.assertIsNone(applied,
                         "a completion that finds an unexpected record must "
                         "never record the wrong hash as applied anyway")


class TestSkillLock(OverridesCase):
    """The actual mutual exclusion `_claim_operation`'s hash comparisons
    alone could not provide — real, OS-level, and verified with real
    threads, not just by reading the code and trusting it."""

    def test_a_second_acquisition_of_the_same_skill_waits(self):
        order = []
        order_lock = threading.Lock()

        def record(event):
            with order_lock:
                order.append(event)

        first_has_lock = threading.Event()
        release_first = threading.Event()
        second_has_lock = threading.Event()
        errors = []

        def hold_then_release():
            try:
                with so._skill_lock(self.home, "inbound-judging"):
                    record("first-acquired")
                    first_has_lock.set()
                    release_first.wait(timeout=5)
                    record("first-released")
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        def acquire_second():
            try:
                with so._skill_lock(self.home, "inbound-judging"):
                    record("second-acquired")
                    second_has_lock.set()
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        holder = threading.Thread(target=hold_then_release)
        holder.start()
        self.assertTrue(first_has_lock.wait(timeout=5), "first thread never acquired the lock")

        # Signals from inside the actual blocking primitive, not from
        # application code merely on its way there — a `threading.Event`
        # set right before calling `_skill_lock` proves only that the
        # thread started running Python, not that it reached `flock()`
        # itself; the OS could still deschedule it before the call. This
        # wraps `fcntl.flock` itself so the handshake fires from exactly
        # the call whose blocking behavior is under test. By this point
        # the holder thread is parked in `release_first.wait()`, not
        # calling `flock` again until it releases, so the only thread
        # that can reach this wrapper before the negative assertion below
        # is the second one — but `_skill_lock` itself makes two flock
        # calls, the global lock in shared mode first (uncontended: two
        # shared acquisitions never conflict) and this skill's own lock
        # in exclusive mode second (the one that actually blocks here).
        # Firing on the first, uncontended call would still let the
        # thread be descheduled before it ever reaches the second, so
        # this filters specifically for the `LOCK_EX` call — the one
        # this test is actually about.
        import fcntl
        second_attempting = threading.Event()
        real_flock = fcntl.flock

        def instrumented_flock(fd, operation):
            if operation == fcntl.LOCK_EX:
                second_attempting.set()
            return real_flock(fd, operation)

        fcntl.flock = instrumented_flock
        try:
            second = threading.Thread(target=acquire_second)
            second.start()
            self.assertTrue(second_attempting.wait(timeout=5),
                            "second thread never reached its flock() call")

            # A negative assertion, not a timing dependency: a no-op or
            # broken lock would let this succeed essentially instantly, so
            # any bounded wait here reliably catches that; a correct lock
            # simply blocks past it every time, which is the point.
            self.assertFalse(second_has_lock.wait(timeout=0.3),
                             "a second acquisition of the same skill's lock "
                             "succeeded while the first was still held")
        finally:
            fcntl.flock = real_flock

        release_first.set()
        self.assertTrue(second_has_lock.wait(timeout=5),
                        "the second acquisition never completed after the "
                        "first released its lock")
        holder.join(timeout=5)
        second.join(timeout=5)
        self.assertFalse(holder.is_alive(), "holder thread never terminated")
        self.assertFalse(second.is_alive(), "second thread never terminated")
        self.assertEqual(errors, [])
        self.assertEqual(order, ["first-acquired", "first-released", "second-acquired"])

    def test_two_different_skills_do_not_block_each_other(self):
        self.ship("inbound-judging")
        self.ship("memory-writing")
        started_a = threading.Event()
        release_a = threading.Event()
        errors = []

        def hold_a():
            try:
                with so._skill_lock(self.home, "inbound-judging"):
                    started_a.set()
                    release_a.wait(timeout=5)
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        holder = threading.Thread(target=hold_a)
        holder.start()
        self.assertTrue(started_a.wait(timeout=5))

        acquired_b = threading.Event()

        def try_b():
            try:
                with so._skill_lock(self.home, "memory-writing"):
                    acquired_b.set()
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        second = threading.Thread(target=try_b)
        second.start()
        self.assertTrue(acquired_b.wait(timeout=2),
                        "a different skill's lock must not be blocked by "
                        "this one being held")

        release_a.set()
        holder.join(timeout=5)
        second.join(timeout=5)
        self.assertFalse(holder.is_alive(), "holder thread never terminated")
        self.assertFalse(second.is_alive(), "second thread never terminated")
        self.assertEqual(errors, [])

    def test_apply_and_remove_on_the_same_skill_never_interleave(self):
        """A real end-to-end race through the public functions, not just
        the lock primitive: two full operations on the same skill,
        started close together, must still run one at a time."""
        live_path = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)
        so.apply_overrides(self.home)  # live is now the override

        real_atomic_write = so._atomic_write
        entered = threading.Event()
        proceed = threading.Event()

        def slow_atomic_write(path, text):
            entered.set()
            proceed.wait(timeout=5)
            real_atomic_write(path, text)

        so._atomic_write = slow_atomic_write
        results = {}

        def do_remove():
            results["remove"] = so.remove_override(self.home, "inbound-judging")

        remover = threading.Thread(target=do_remove)
        remover.start()
        self.assertTrue(entered.wait(timeout=5), "remove never reached its write")

        # A concurrent apply attempt must not be able to touch this skill
        # while remove's write is in flight and its lock is held.
        applied_while_blocked = threading.Event()

        def do_apply():
            results["apply"] = so.apply_overrides(self.home)
            applied_while_blocked.set()

        # By this point the remover thread already holds the skill's lock
        # and is parked inside `slow_atomic_write`'s `proceed.wait()`, not
        # calling `flock` again — so the only thread that can reach this
        # wrapper before the negative assertion below is the applier.
        # See the matching comment in
        # test_a_second_acquisition_of_the_same_skill_waits for why this
        # has to instrument the real `flock` call rather than a
        # `threading.Event` set merely before entering application code,
        # and for why it filters on `LOCK_EX` specifically — the
        # applier's own global-shared acquisition is uncontended and
        # would fire this too early otherwise.
        import fcntl
        applier_attempting = threading.Event()
        real_flock = fcntl.flock

        def instrumented_flock(fd, operation):
            if operation == fcntl.LOCK_EX:
                applier_attempting.set()
            return real_flock(fd, operation)

        fcntl.flock = instrumented_flock
        try:
            applier = threading.Thread(target=do_apply)
            applier.start()
            self.assertTrue(applier_attempting.wait(timeout=5),
                            "applier thread never reached its flock() call")
            # Negative assertion, not a timing dependency — see the
            # matching comment in
            # test_a_second_acquisition_of_the_same_skill_waits.
            self.assertFalse(applied_while_blocked.wait(timeout=0.3),
                             "a concurrent apply proceeded while remove's "
                             "lock on this skill was held")
        finally:
            fcntl.flock = real_flock

        proceed.set()
        remover.join(timeout=5)
        applier.join(timeout=5)
        so._atomic_write = real_atomic_write
        self.assertFalse(remover.is_alive(), "remove thread never terminated")
        self.assertFalse(applier.is_alive(), "apply thread never terminated")

        self.assertEqual(results["remove"].kind, "removed")
        # By the time apply's own lock acquisition unblocked, remove had
        # already deleted the override — apply must see nothing left to
        # do for this skill, not resurrect what remove just removed.
        self.assertEqual(results["apply"], [])
        self.assertFalse(self.override_path("inbound-judging").exists())
        live = live_path.read_text(encoding="utf-8")
        self.assertNotEqual(live, override_text,
                            "the override must not still be live after a "
                            "successful remove")


class TestPathSafety(OverridesCase):
    def test_apply_and_remove_reject_a_path_traversal_name(self):
        with self.assertRaises(so.InvalidSkillName):
            so.remove_override(self.home, "../../etc")

    def test_a_symlinked_skill_directory_is_refused(self):
        real = self.home / "elsewhere"
        real.mkdir()
        (self.home / "skills" / "inbound-judging").symlink_to(real)
        with self.assertRaises(so.UnsafePath):
            so._safe_child(so._skills_dir(self.home), "inbound-judging", "SKILL.md")

    def test_a_symlinked_skill_directory_is_skipped_by_listing_not_processed(self):
        real = self.home / "elsewhere"
        real.mkdir()
        (real / "SKILL.md").write_text(
            "---\nname: inbound-judging\ndescription: x\n---\n\nbody\n",
            encoding="utf-8")
        (self.home / "skills" / "inbound-judging").symlink_to(real)

        reports = so.apply_overrides(self.home)
        self.assertEqual(reports, [])

    def test_a_symlinked_overrides_parent_is_refused(self):
        state_dir = self.home / "workspace" / "skill-overrides"
        state_dir.mkdir(parents=True)
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (state_dir / "overrides").symlink_to(outside)
        with self.assertRaises(so.UnsafePath):
            so._safe_child(so._overrides_dir(self.home), "inbound-judging", "SKILL.md")

    def test_atomic_write_leaves_no_temp_file_behind_on_success(self):
        target_dir = self.home / "skills" / "inbound-judging"
        target_dir.mkdir(parents=True)
        target = target_dir / "SKILL.md"
        target.write_text("original\n", encoding="utf-8")

        so._atomic_write(target, "new content\n")

        self.assertEqual(target.read_text(encoding="utf-8"), "new content\n")
        leftovers = [p for p in target_dir.iterdir() if p.name != "SKILL.md"]
        self.assertEqual(leftovers, [], f"temp file(s) left behind: {leftovers}")


class TestCLI(OverridesCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(HERE / "skill_overrides.py"), *args],
            capture_output=True, text=True,
            env={**os.environ, "HERMES_HOME": str(self.home)})

    def test_bare_invocation_defaults_to_apply(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        override_text = self.override_path("inbound-judging").read_text(encoding="utf-8")
        self.write_override("inbound-judging", override_text)

        proc = self.run_cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"applied"', proc.stdout)
        live = (self.home / "skills" / "inbound-judging" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(live, override_text)

    def test_an_invalid_override_makes_apply_exit_nonzero(self):
        self.ship("inbound-judging")
        self.write_override("inbound-judging", "garbage\n")

        proc = self.run_cli("--apply")
        self.assertEqual(proc.returncode, 1)
        self.assertIn('"skipped-invalid"', proc.stdout)

    def test_check_exits_zero_and_prints_the_wake_gate(self):
        self.ship("inbound-judging")
        proc = self.run_cli("--check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"wakeAgent": false', proc.stdout)

    def test_an_abbreviated_flag_is_refused_not_silently_resolved(self):
        self.ship("inbound-judging")
        proc = self.run_cli("--a")
        self.assertNotEqual(proc.returncode, 0)

    def test_an_invalid_remove_name_reports_rather_than_tracebacks(self):
        """A scheduler or a script parsing this command's output cannot
        tell a silent crash apart from a process that never ran — the
        findings JSON and the wake gate have to print regardless."""
        proc = self.run_cli("--remove", "../../etc")
        self.assertEqual(proc.returncode, 1)
        self.assertIn('"findings"', proc.stdout)
        self.assertIn('"wakeAgent": false', proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_an_invalid_fork_name_reports_rather_than_tracebacks(self):
        proc = self.run_cli("--fork", "../../etc")
        self.assertEqual(proc.returncode, 1)
        self.assertIn('"findings"', proc.stdout)
        self.assertIn('"wakeAgent": false', proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_fork_of_one_skill_does_not_reconcile_an_unrelated_pending_row(self):
        """--fork <skill> only needs that skill's own bookkeeping settled
        first — reconciling every other skill's rows too would let an
        unrelated one's held lock delay a request that was never about
        it."""
        self.ship("inbound-judging")
        self.ship("memory-writing")
        so.fork_skill(self.home, "memory-writing")
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute(
                "INSERT INTO override_operations"
                "(skill_name, op_type, status, expected_before_hash, expected_after_hash)"
                " VALUES ('memory-writing', 'apply', 'pending', 'x', 'y')")

        proc = self.run_cli("--fork", "inbound-judging")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"forked"', proc.stdout)

        with sqlite3.connect(self.db_path()) as conn:
            status = conn.execute(
                "SELECT status FROM override_operations"
                " WHERE skill_name='memory-writing'").fetchone()[0]
        self.assertEqual(status, "pending",
                         "an unrelated skill's row must not be touched by "
                         "--fork on a different skill")


if __name__ == "__main__":
    unittest.main(verbosity=2)
