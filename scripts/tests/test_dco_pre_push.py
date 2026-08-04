# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the repository DCO checker and pre-push hook."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "check_dco_signoffs.sh"
PRE_PUSH = REPO_ROOT / ".githooks" / "pre-push"
ZERO_SHA = "0" * 40


class DcoPrePushTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        (self.repo / "scripts").mkdir()
        (self.repo / ".githooks").mkdir()
        shutil.copy2(CHECKER, self.repo / "scripts" / CHECKER.name)
        shutil.copy2(PRE_PUSH, self.repo / ".githooks" / PRE_PUSH.name)

        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Test Contributor")
        self.git("config", "user.email", "contributor@example.com")
        self.commit("chore: establish base", signed_off=True)
        self.base_sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("update-ref", "refs/remotes/origin/main", self.base_sha)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def commit(self, subject: str, *, signed_off: bool) -> str:
        args = ["commit", "--allow-empty", "-m", subject]
        if signed_off:
            args.append("--signoff")
        self.git(*args)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def run_checker(self, head_sha: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.repo / "scripts" / CHECKER.name), self.base_sha, head_sha],
            cwd=self.repo,
            check=False,
            capture_output=True,
            text=True,
        )

    def run_pre_push(self, head_sha: str) -> subprocess.CompletedProcess[str]:
        update = f"refs/heads/topic {head_sha} refs/heads/topic {ZERO_SHA}\n"
        return subprocess.run(
            [str(self.repo / ".githooks" / PRE_PUSH.name), "origin", "unused"],
            cwd=self.repo,
            input=update,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_checker_accepts_a_signed_off_commit(self) -> None:
        head_sha = self.commit("fix: preserve sign-off", signed_off=True)

        result = self.run_checker(head_sha)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed for 1 commit", result.stdout)

    def test_checker_rejects_an_unsigned_commit(self) -> None:
        head_sha = self.commit("fix: omit sign-off", signed_off=False)

        result = self.run_checker(head_sha)

        self.assertEqual(result.returncode, 1)
        self.assertIn("missing a valid Signed-off-by trailer", result.stderr)

    def test_pre_push_stops_an_unsigned_new_branch(self) -> None:
        head_sha = self.commit("fix: stop unsigned push", signed_off=False)

        result = self.run_pre_push(head_sha)

        self.assertEqual(result.returncode, 1)
        self.assertIn("was stopped before data was sent", result.stderr)

    def test_pre_push_accepts_a_signed_off_new_branch(self) -> None:
        head_sha = self.commit("fix: allow signed push", signed_off=True)

        result = self.run_pre_push(head_sha)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed for 1 commit", result.stdout)


if __name__ == "__main__":
    unittest.main()
