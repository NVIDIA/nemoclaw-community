# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for auto-heal installation after the example path changes."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


OLD_EXAMPLE_DIR = "/checkout/examples/personal-community-sentiment-triage"


class InstallMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        source_example = Path(__file__).resolve().parents[3]
        self.example_dir = (
            self.root
            / "checkout"
            / "examples"
            / "recipes"
            / "nvidia"
            / "developer-community-chief-of-staff"
        )
        shutil.copytree(source_example / "scripts", self.example_dir / "scripts")
        (self.example_dir / ".env").write_text("\n", encoding="utf-8")

        self.home = self.root / "home"
        self.config_home = self.root / "config"
        self.bin_dir = self.root / "bin"
        self.home.mkdir()
        self.bin_dir.mkdir()
        self.systemctl_log = self.root / "systemctl.log"
        self._write_executable(
            "systemctl",
            '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$SYSTEMCTL_LOG"\n',
        )
        self._write_executable("docker", "#!/usr/bin/env bash\nexit 0\n")
        self._write_executable("curl", "#!/usr/bin/env bash\nexit 0\n")
        self._write_executable(
            "openshell",
            """#!/usr/bin/env bash
if [[ "$1 $2" == "sandbox list" ]]; then
  printf 'hermes-direct Ready\\n'
fi
exit 0
""",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_executable(self, name: str, content: str) -> None:
        path = self.bin_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def run_installer(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["XDG_CONFIG_HOME"] = str(self.config_home)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"
        env["SYSTEMCTL_LOG"] = str(self.systemctl_log)
        return subprocess.run(
            ["bash", "scripts/autoheal/install.sh"],
            cwd=self.example_dir,
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

    def test_rewrites_paths_and_restarts_owned_units(self) -> None:
        config_dir = self.config_home / "nemoclaw-autoheal"
        config_dir.mkdir(parents=True)
        (config_dir / "runtime.env").write_text(
            f"EXAMPLE_DIR={OLD_EXAMPLE_DIR}\nSANDBOX_NAME=hermes-direct\n",
            encoding="utf-8",
        )

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        installed_example_dir = self.example_dir.resolve()
        runtime_env = (config_dir / "runtime.env").read_text(encoding="utf-8")
        self.assertIn(f"EXAMPLE_DIR={installed_example_dir}", runtime_env)
        self.assertNotIn(OLD_EXAMPLE_DIR, runtime_env)

        unit_dir = self.config_home / "systemd" / "user"
        gateway_unit = (
            unit_dir / "nemoclaw-hermes-gateway-forward.service"
        ).read_text(encoding="utf-8")
        self.assertIn(str(installed_example_dir), gateway_unit)
        self.assertNotIn(OLD_EXAMPLE_DIR, gateway_unit)
        runtime_unit = (unit_dir / "nemoclaw-hermes-runtime.service").read_text(
            encoding="utf-8"
        )
        self.assertIn(str(installed_example_dir), runtime_unit)
        self.assertIn(
            "openshell sandbox exec --name ${SANDBOX_NAME} -- "
            "/usr/local/bin/nemoclaw-start",
            runtime_unit,
        )
        self.assertNotIn("/tmp/nemoclaw-proxy-env.sh", runtime_unit)

        systemctl_calls = self.systemctl_log.read_text(encoding="utf-8")
        for unit in (
            "nemoclaw-hermes-gateway-forward.service",
            "nemoclaw-hermes-watchdog.timer",
            "nemoclaw-slack-response-monitor.timer",
        ):
            self.assertIn(f"--user restart {unit}", systemctl_calls)
        self.assertIn(
            f"Migrated auto-heal from {OLD_EXAMPLE_DIR} to {installed_example_dir}.",
            result.stdout,
        )
        self.assertEqual(list(config_dir.glob("runtime.env.*")), [])
        self.assertEqual(list(unit_dir.glob("*.service.*")), [])
        self.assertEqual(list(unit_dir.glob("*.timer.*")), [])

    def test_first_install_does_not_restart_units(self) -> None:
        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        unit_dir = self.config_home / "systemd" / "user"
        self.assertTrue((unit_dir / "nemoclaw-hermes-runtime.service").is_file())
        systemctl_calls = self.systemctl_log.read_text(encoding="utf-8")
        self.assertNotIn("--user restart ", systemctl_calls)
        self.assertNotIn("Migrated auto-heal from", result.stdout)


if __name__ == "__main__":
    unittest.main()
