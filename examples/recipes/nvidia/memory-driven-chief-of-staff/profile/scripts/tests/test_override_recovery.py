# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Distribution provenance and complete recovery through the public commands."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import skill_overrides as so  # noqa: E402
import skill_override_bundle as bundle  # noqa: E402
from test_skill_overrides import OverridesCase  # noqa: E402


class TestDistributionAuthority(OverridesCase):
    def test_valid_frontmatter_does_not_make_an_unknown_live_edit_a_base(self):
        live = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        so.apply_overrides(self.home)
        original_db = self.db_path().read_bytes()
        unknown = "---\nname: inbound-judging\ndescription: valid but unregistered\n---\nChanged instructions.\n"
        live.write_text(unknown)
        self.assertEqual(so.check_overrides(self.home)[0].kind, "blocked")
        self.assertEqual(so.apply_overrides(self.home)[0].kind, "blocked")
        with self.assertRaises(so.UnverifiedBase):
            so.remove_override(self.home, "inbound-judging")
        self.assertEqual(live.read_text(), unknown)
        self.assertEqual(self.db_path().read_bytes(), original_db)
        with so.exclusive_lock_for_reset(self.home):
            reports = so.restore_all_for_reset_locked(self.home)
        self.assertEqual([r.kind for r in reports], ["preserved-live"])
        self.assertEqual(live.read_text(), unknown)
        self.assertEqual(
            self.db_path().read_bytes(), original_db,
            "reset preparation must not promote preserved live bytes into "
            "accepted history")

    def test_bare_update_requires_registration_then_refuses_the_stale_override(self):
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        so.apply_overrides(self.home)
        updated = self.ship("inbound-judging", description="new", register=False)
        self.assertEqual(so.apply_overrides(self.home)[0].kind, "blocked")
        source = self.distribution / "skills/inbound-judging/SKILL.md"
        source.write_bytes(updated.read_bytes())
        so.record_distribution(self.home, self.distribution)
        self.assertEqual(so.apply_overrides(self.home)[0].kind, "skipped-stale")
        self.assertEqual(updated.read_bytes(), source.read_bytes())

    def test_install_directory_cannot_register_itself_as_a_distribution(self):
        self.ship("inbound-judging", register=False)
        with self.assertRaises(so.UnverifiedBase):
            so.record_distribution(self.home, self.home)
        self.assertFalse(self.db_path().exists())

    def test_unknown_first_install_is_not_automatically_trusted(self):
        self.ship("inbound-judging", register=False)
        self.assertEqual(so.apply_overrides(self.home)[0].kind, "blocked")
        with self.assertRaises(so.UnverifiedBase):
            so.fork_skill(self.home, "inbound-judging")
        with sqlite3.connect(self.db_path()) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM base_observations").fetchone()[0], 0)

    def test_legacy_observations_require_explicit_approval_after_upgrade(self):
        live = self.ship("inbound-judging")
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute("DROP TABLE approved_bases")
            conn.execute("DROP TABLE distribution_bases")
        self.assertEqual(so.apply_overrides(self.home)[0].kind, "blocked")
        so.record_distribution(self.home, self.distribution)
        self.assertEqual(so.fork_skill(self.home, "inbound-judging").kind, "forked")
        self.assertNotIn("based_on_sha256", live.read_text())

    def test_removed_distribution_entry_never_restores_an_obsolete_skill(self):
        live = self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        so.apply_overrides(self.home)
        shutil.rmtree(self.distribution / "skills/inbound-judging")
        so.record_distribution(self.home, self.distribution)
        content = live.read_bytes()
        self.assertEqual(so.apply_overrides(self.home)[0].kind, "blocked")
        with self.assertRaises(so.UnverifiedBase):
            so.remove_override(self.home, "inbound-judging")
        self.assertEqual(live.read_bytes(), content)

    def test_accepted_rollback_records_a_b_a_in_order(self):
        self.ship("inbound-judging", description="A")
        self.ship("inbound-judging", description="B")
        self.ship("inbound-judging", description="A")
        so.record_distribution(self.home, self.distribution)
        with sqlite3.connect(self.db_path()) as conn:
            hashes = [r[0] for r in conn.execute("SELECT content_hash FROM base_observations ORDER BY observation_id")]
        self.assertEqual(len(hashes), 3)
        self.assertEqual(hashes[0], hashes[2])
        self.assertNotEqual(hashes[0], hashes[1])


class TestRecoveryBundle(OverridesCase):
    def setUp(self):
        super().setUp()
        self.ship("inbound-judging")
        so.fork_skill(self.home, "inbound-judging")
        self.override_path("inbound-judging").write_text(
            self.override_path("inbound-judging").read_text() + "\nA user correction.\n")
        so.apply_overrides(self.home)
        _, self.snapshot = bundle.capture(self.home)
        self.file = self.distribution / "recovery.json"
        self.file.write_text(json.dumps(self.snapshot))
        self.target = Path(tempfile.mkdtemp())
        shutil.copytree(self.home / "skills", self.target / "skills")

    def tearDown(self):
        shutil.rmtree(self.target, ignore_errors=True)
        super().tearDown()

    def test_cli_restore_keeps_applied_state_and_allows_removal_without_refork(self):
        env = {**os.environ, "HERMES_HOME": str(self.target)}
        (self.target / "distribution.yaml").write_text("id: test\n")
        result = subprocess.run([sys.executable, str(HERE / "skill_overrides.py"),
                                 "--restore", str(self.file)], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('"restored"', result.stdout)
        report = so.remove_override(self.target, "inbound-judging")
        self.assertEqual(report.kind, "removed")
        source = self.distribution / "skills/inbound-judging/SKILL.md"
        self.assertEqual((self.target / "skills/inbound-judging/SKILL.md").read_bytes(), source.read_bytes())

    def test_an_existing_destination_is_never_replaced(self):
        before = self.db_path().read_bytes()
        with self.assertRaises(bundle.InvalidBundle):
            bundle.restore_bundle(self.home, self.file)
        self.assertEqual(self.db_path().read_bytes(), before)

    def test_incomplete_or_corrupt_bundles_leave_no_installed_state(self):
        changes = [
            lambda x: x.update(version=2),
            lambda x: x["files"].pop(next(p for p in x["files"] if p.startswith("bases/"))),
            lambda x: x["tables"]["distribution_bases"][0].update(content_hash="0" * 64),
            lambda x: x["files"][next(iter(x["files"]))].update(sha256="0" * 64),
            lambda x: x["tables"]["override_operations"][0].update(status="invalid"),
        ]
        for change in changes:
            with self.subTest(change=change):
                data = json.loads(json.dumps(self.snapshot))
                change(data)
                self.file.write_text(json.dumps(data))
                with self.assertRaises(bundle.InvalidBundle):
                    bundle.restore_bundle(self.target, self.file)
                self.assertFalse(so._state_dir(self.target).exists())

    def test_export_refuses_a_missing_retained_base(self):
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute("CREATE TABLE future_state (value TEXT)")
        with self.assertRaises(bundle.InvalidBundle):
            bundle.capture(self.home)
        with sqlite3.connect(self.db_path()) as conn:
            conn.execute("DROP TABLE future_state")
        digest = self.snapshot["tables"]["base_blobs"][0]["content_hash"]
        (so._bases_dir(self.home) / digest / "SKILL.md").unlink()
        with self.assertRaises(bundle.InvalidBundle):
            bundle.capture(self.home)

    def test_non_utf8_override_bytes_round_trip(self):
        self.override_path("inbound-judging").write_bytes(b"invalid utf8: \xff\n")
        _, data = bundle.capture(self.home)
        self.file.write_text(json.dumps(data))
        bundle.restore_bundle(self.target, self.file)
        restored = so._overrides_dir(self.target) / "inbound-judging/SKILL.md"
        self.assertEqual(restored.read_bytes(), b"invalid utf8: \xff\n")
        self.assertTrue(any(r.kind in so.PROBLEM_KINDS for r in so.apply_overrides(self.target)))

    def test_pending_apply_history_survives_and_reconciles(self):
        current = self.override_path("inbound-judging").read_text() + "\nAnother correction.\n"
        self.override_path("inbound-judging").write_text(current)
        with patch.object(so, "_atomic_write", side_effect=OSError("interrupted write")):
            self.assertEqual(so.apply_overrides(self.home)[0].kind, "error")
        _, data = bundle.capture(self.home)
        self.assertTrue(any(r["status"] == "pending" for r in data["tables"]["override_operations"]))
        self.file.write_text(json.dumps(data))
        bundle.restore_bundle(self.target, self.file)
        self.assertEqual(so.reconcile(self.target)[0].kind, "reconciled-retry")
        self.assertEqual(so.apply_overrides(self.target)[0].kind, "applied")
        self.assertEqual((self.target / "skills/inbound-judging/SKILL.md").read_text(), current)

    def test_process_exit_before_publish_leaves_only_retryable_staging(self):
        code = """
import os, sys
from pathlib import Path
import skill_override_bundle as b
real = os.replace
def stop(src, dst):
    if Path(src).name == '.skill-overrides-restore':
        os._exit(73)
    return real(src, dst)
os.replace = stop
b.restore_bundle(Path(sys.argv[1]), Path(sys.argv[2]))
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.target), str(self.file)], cwd=HERE)
        self.assertEqual(result.returncode, 73)
        self.assertFalse(so._state_dir(self.target).exists())
        self.assertTrue((self.target / "workspace/.skill-overrides-restore").exists())
        bundle.restore_bundle(self.target, self.file)
        self.assertFalse((self.target / "workspace/.skill-overrides-restore").exists())
        self.assertEqual(so.check_overrides(self.target)[0].kind, "applied")

    def test_process_exit_after_publish_leaves_complete_recoverable_state(self):
        code = """
import os, sys
from pathlib import Path
import skill_override_bundle as b
real = os.replace
def stop(src, dst):
    result = real(src, dst)
    if Path(src).name == '.skill-overrides-restore':
        os._exit(74)
    return result
os.replace = stop
b.restore_bundle(Path(sys.argv[1]), Path(sys.argv[2]))
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.target), str(self.file)], cwd=HERE)
        self.assertEqual(result.returncode, 74)
        with self.assertRaises(bundle.InvalidBundle):
            bundle.restore_bundle(self.target, self.file)
        self.assertEqual(so.remove_override(self.target, "inbound-judging").kind, "removed")


if __name__ == "__main__":
    unittest.main()
