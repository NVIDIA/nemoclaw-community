# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase

SCRIPTS_DIR = Path(__file__).parents[1]
HOST_SERVICES = SCRIPTS_DIR / "00-host-services.sh"
COMPOSE_FILE = SCRIPTS_DIR.parent / "extras" / "docker-compose.yml"


class HostServicesProfilesTest(TestCase):
    def run_host_services(
        self,
        github_enabled: str | None = None,
        github_token: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_docker = Path(temp_dir) / "docker"
            docker_log = Path(temp_dir) / "docker.log"
            ca_bundle = Path(temp_dir) / "ca-certificates.crt"
            ca_bundle.write_text("test CA bundle\n", encoding="utf-8")
            fake_docker.write_text(
                """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$DOCKER_LOG"
exit 0
""",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)

            environment = {
                **os.environ,
                "PATH": f"{temp_dir}:{os.environ['PATH']}",
                "DOCKER_LOG": str(docker_log),
                "ATIF_EXPORT_MODE": "local",
                "NEMOCLAW_HOST_CA_BUNDLE": str(ca_bundle),
            }
            environment.pop("SOURCE_ETL_GITHUB_ENABLED", None)
            environment.pop("GITHUB_TOKEN", None)
            if github_enabled is not None:
                environment["SOURCE_ETL_GITHUB_ENABLED"] = github_enabled
            if github_token is not None:
                environment["GITHUB_TOKEN"] = github_token

            result = subprocess.run(
                ["bash", str(HOST_SERVICES), "up"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            log = docker_log.read_text(encoding="utf-8") if docker_log.exists() else ""
            return result, log

    def test_github_etl_is_disabled_by_default(self) -> None:
        result, log = self.run_host_services()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--profile github-etl", log)
        self.assertIn("GitHub source ETL: disabled", result.stdout)

    def test_live_read_token_does_not_implicitly_enable_etl(self) -> None:
        result, log = self.run_host_services(github_token="test-token")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--profile github-etl", log)

    def test_explicit_flag_enables_github_etl_profile(self) -> None:
        result, log = self.run_host_services(github_enabled="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--profile github-etl", log)
        self.assertIn("GitHub source ETL: enabled", result.stdout)

    def test_invalid_enable_flag_fails_before_compose(self) -> None:
        result, log = self.run_host_services(github_enabled="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(log, "")
        self.assertIn("expected 0 or 1", result.stderr)

    def test_compose_service_is_profile_gated(self) -> None:
        compose = COMPOSE_FILE.read_text(encoding="utf-8")
        service_start = compose.index("  github-etl:")
        next_service = compose.index("\n  forums-etl:", service_start)
        github_service = compose[service_start:next_service]
        self.assertIn('profiles: ["github-etl"]', github_service)
