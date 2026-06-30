#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_nemoclaw import (
    DOCKERFILE_MARKER,
    patch_nemoclaw,
)


class PatchNemoClawTest(unittest.TestCase):
    def test_patches_expected_files_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hermes = root / "agents/hermes"
            config = hermes / "config"
            config.mkdir(parents=True)
            (hermes / "Dockerfile").write_text(
                "ARG BASE_IMAGE=base\n"
                "# hadolint ignore=DL3006\n"
                "FROM ${BASE_IMAGE}\n"
                "WORKDIR /sandbox\n"
                "USER sandbox\n",
                encoding="utf-8",
            )
            (config / "hermes-config.ts").write_text(
                'plugins: { enabled: ["nemoclaw"], },\n', encoding="utf-8"
            )
            (hermes / "start.sh").write_text(
                "# ── Main ─────────────────────────────────────────────────────────\n"
                "  validate_tmp_permissions\n\n  # Start Hermes gateway.\n"
                'HERMES_HOME="${HERMES_DIR}" \\\n'
                '    nohup "$HERMES" gateway run >/tmp/gateway.log 2>&1 &\n'
                '  SANDBOX_CHILD_PIDS=("$GATEWAY_PID" "$DASHBOARD_PID")\n'
                "validate_tmp_permissions\n\n# Start Hermes gateway.\n"
                "nohup \"${STEP_DOWN_PREFIX_GATEWAY[@]}\" sh -c 'run gateway'\n"
                'SANDBOX_CHILD_PIDS=("$GATEWAY_PID" "$DASHBOARD_PID")\n',
                encoding="utf-8",
            )
            relay = root / "plugins.toml"
            relay.write_text("version = 1\n", encoding="utf-8")
            patch_nemoclaw(root, relay)
            patch_nemoclaw(root, relay)

            dockerfile = (hermes / "Dockerfile").read_text(encoding="utf-8")
            generated = (config / "hermes-config.ts").read_text(encoding="utf-8")
            startup = (hermes / "start.sh").read_text(encoding="utf-8")
            self.assertEqual(dockerfile.count(DOCKERFILE_MARKER), 1)
            self.assertIn("uv sync --extra nemo-relay --locked", dockerfile)
            self.assertNotIn("maturin", dockerfile)
            self.assertNotIn("object-store", dockerfile)
            self.assertIn('"observability/nemo_relay"', generated)
            self.assertEqual(
                startup.count("# financial-assistant-native-relay-env-v2"), 1
            )
            self.assertEqual(startup.count('env "${NEMO_RELAY_GATEWAY_ENV[@]}"'), 2)
            self.assertNotIn("HERMES_NEMO_RELAY_ATIF_ENABLED", startup)
            self.assertNotIn("AWS_SESSION_TOKEN", startup)
            self.assertNotIn("start_atif_bridge", startup)
            self.assertEqual(
                (hermes / "nemo-relay-plugins.toml").read_text(encoding="utf-8"),
                "version = 1\n",
            )

    def test_rejects_unknown_upstream_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hermes = root / "agents/hermes"
            config = hermes / "config"
            config.mkdir(parents=True)
            (hermes / "Dockerfile").write_text(
                "ARG BASE_IMAGE=base\n# hadolint ignore=DL3006\nFROM ${BASE_IMAGE}\n",
                encoding="utf-8",
            )
            (config / "hermes-config.ts").write_text(
                'plugins: { enabled: ["nemoclaw"], },\n', encoding="utf-8"
            )
            (hermes / "start.sh").write_text(
                "# ── Main ─────────────────────────────────────────────────────────\n",
                encoding="utf-8",
            )
            relay = root / "plugins.toml"
            relay.write_text("version = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "integration point"):
                patch_nemoclaw(root, relay)


if __name__ == "__main__":
    unittest.main()
