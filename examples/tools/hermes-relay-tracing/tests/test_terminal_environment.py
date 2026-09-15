# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[1]
CONFIGURE_TERMINAL = REPOSITORY_ROOT / "scripts" / "configure_tutorial_terminal.sh"


class TutorialTerminalEnvironmentTests(unittest.TestCase):
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
