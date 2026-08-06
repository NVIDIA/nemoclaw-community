# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from unittest import TestCase

HERMES_DIR = Path(__file__).parents[1]
DOCKERFILE = (HERMES_DIR / "Dockerfile").read_text(encoding="utf-8")
START_SCRIPT = (HERMES_DIR / "start.sh").read_text(encoding="utf-8")
TUI_ENTRY = "/opt/hermes/ui-tui/dist/entry.js"
TUI_DIR = "/opt/hermes/ui-tui"


class HermesTuiRuntimeContractTest(TestCase):
    def test_image_requires_the_prebuilt_tui_bundle(self) -> None:
        self.assertIn(f"RUN test -s {TUI_ENTRY}", DOCKERFILE)
        self.assertIn(f"HERMES_TUI_DIR={TUI_DIR}", DOCKERFILE)

    def test_interactive_shell_uses_the_prebuilt_tui_bundle(self) -> None:
        self.assertIn(f"if [ -s {TUI_ENTRY} ]; then", START_SCRIPT)
        self.assertIn(f'export HERMES_TUI_DIR="{TUI_DIR}"', START_SCRIPT)
        self.assertIn("export HERMES_DISABLE_LAZY_INSTALLS=1", START_SCRIPT)
