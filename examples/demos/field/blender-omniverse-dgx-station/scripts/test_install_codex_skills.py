# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for migration-safe Codex skill links."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROJECT_SKILLS = ("coach-nemoclaw-hermes", "coordinate-nemoclaw-blender")


class InstallCodexSkillsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.guide = (
            self.repo
            / "examples"
            / "demos"
            / "field"
            / "blender-omniverse-dgx-station"
        )
        self.script = self.guide / "scripts" / "install_codex_skills.sh"
        self.script.parent.mkdir(parents=True)
        source_script = Path(__file__).with_name("install_codex_skills.sh")
        shutil.copy2(source_script, self.script)

        for name in PROJECT_SKILLS:
            skill_dir = self.guide / "codex-skills" / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")

        self.ov_repo = self.root / "ov-blender-example"
        (self.ov_repo / "skills").mkdir(parents=True)
        (self.ov_repo / "skills" / "manifest.json").write_text(
            "{}\n", encoding="utf-8"
        )
        self.skills_dir = self.root / "installed-skills"
        self.skills_dir.mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_installer(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["CODEX_SKILLS_DIR"] = str(self.skills_dir)
        return subprocess.run(
            ["bash", str(self.script), str(self.ov_repo)],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

    def test_replaces_only_links_from_previous_project_path(self) -> None:
        legacy_root = (
            self.repo.resolve()
            / "examples"
            / "blender-omniverse-dgx-station"
            / "codex-skills"
        )
        for name in PROJECT_SKILLS:
            (self.skills_dir / name).symlink_to(legacy_root / name)

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        for name in PROJECT_SKILLS:
            target = self.skills_dir / name
            self.assertTrue(target.is_symlink())
            self.assertEqual(
                target.resolve(),
                (self.guide / "codex-skills" / name).resolve(),
            )
            self.assertIn(f"migrating moved project skill: {name}", result.stdout)

    def test_refuses_link_to_unrelated_location(self) -> None:
        unrelated = self.root / "unrelated" / PROJECT_SKILLS[0]
        unrelated.mkdir(parents=True)
        (unrelated / "SKILL.md").write_text("# unrelated\n", encoding="utf-8")
        target = self.skills_dir / PROJECT_SKILLS[0]
        target.symlink_to(unrelated)

        result = self.run_installer()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.resolve(), unrelated.resolve())
        self.assertIn("refusing to replace existing Codex skill", result.stderr)


if __name__ == "__main__":
    unittest.main()
