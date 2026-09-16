# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[1]
CONFIGURE_TERMINAL = REPOSITORY_ROOT / "scripts" / "configure_tutorial_terminal.sh"


class TutorialTerminalEnvironmentTests(unittest.TestCase):
    def test_environment_check_accepts_runtime_path_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermes runtime test ") as directory:
            runtime = Path(directory) / "runtime with spaces"
            python = runtime / "venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            # Stand in for the pinned runtime without installing Hermes or
            # contacting a model. Both probes must reach this executable.
            python.write_text(
                "#!/bin/bash\n"
                "source_text=$(</dev/stdin)\n"
                "case \"$source_text\" in\n"
                "  *'from hermes_cli import __version__'*) echo 0.21.1 ;;\n"
                "  *'from importlib.metadata import PackageNotFoundError, version'*) echo 0.8.3 ;;\n"
                "  *) exit 1 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            python.chmod(0o755)
            result = subprocess.run(
                ["bash", str(REPOSITORY_ROOT / "scripts" / "check_environment.sh")],
                env=os.environ | {"TUTORIAL_RUNTIME_ROOT": str(runtime)},
                capture_output=True, text=True, timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Environment is ready: Hermes 0.21.1, nemo-relay 0.8.3.", result.stdout)

    def test_configure_tutorial_terminal_overrides_inherited_docker_settings(self) -> None:
        inherited_environment = os.environ | {
            "TERMINAL_DOCKER_ENV": '{"NVIDIA_API_KEY":"should-not-forward"}',
            "TERMINAL_DOCKER_EXTRA_ARGS": '["--privileged"]',
            "TERMINAL_DOCKER_FORWARD_ENV": '["NVIDIA_API_KEY"]',
            "TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE": "true",
            "TERMINAL_DOCKER_PERSIST_ACROSS_PROCESSES": "true",
            "TERMINAL_DOCKER_RUN_AS_HOST_USER": "true",
            "TERMINAL_DOCKER_VOLUMES": '["/private/tmp:/workspace"]',
            "TERMINAL_ENV": "local",
        }
        command = "\n".join(
            [
                f'source "{CONFIGURE_TERMINAL}"',
                'configure_tutorial_terminal "tutorial-image" "/tutorial"',
                "env | grep '^TERMINAL_' | sort",
            ]
        )

        result = subprocess.run(
            ["bash", "-c", command],
            check=True,
            capture_output=True,
            env=inherited_environment,
            text=True,
        )

        self.assertEqual(
            result.stdout.splitlines(),
            [
                "TERMINAL_CONTAINER_PERSISTENT=false",
                "TERMINAL_CWD=/tutorial",
                "TERMINAL_DOCKER_ENV={}",
                "TERMINAL_DOCKER_EXTRA_ARGS=[\"--init\", \"--read-only\", \"--tmpfs\", \"/tmp:rw,exec,size=128m\", \"--pids-limit\", \"128\", \"--memory\", \"512m\", \"--memory-swap\", \"512m\", \"--cpus\", \"1\", \"--cap-drop\", \"ALL\", \"--security-opt\", \"no-new-privileges\"]",
                "TERMINAL_DOCKER_FORWARD_ENV=[]",
                "TERMINAL_DOCKER_IMAGE=tutorial-image",
                "TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE=false",
                "TERMINAL_DOCKER_NETWORK=false",
                "TERMINAL_DOCKER_PERSIST_ACROSS_PROCESSES=false",
                "TERMINAL_DOCKER_RUN_AS_HOST_USER=false",
                "TERMINAL_DOCKER_VOLUMES=[]",
                "TERMINAL_ENV=docker",
            ],
        )
