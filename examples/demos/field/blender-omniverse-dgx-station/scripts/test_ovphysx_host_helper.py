#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("ovphysx_host_helper.py")
SPEC = importlib.util.spec_from_file_location("ovphysx_host_helper", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ConfiguredDemoTests(unittest.TestCase):
    def test_runs_each_stage_and_returns_compact_receipt(self) -> None:
        settings = {"output_dir": "/tmp/stair-drop"}
        with (
            mock.patch.object(MODULE, "_preflight", return_value={"status": "pass"}),
            mock.patch.object(MODULE, "_prepare", return_value={"status": "pass"}),
            mock.patch.object(MODULE, "_preview", return_value={"status": "pass"}),
            mock.patch.object(
                MODULE,
                "_simulate",
                return_value={
                    "status": "pass",
                    "native_status": "pass-real",
                    "sample_count": 25,
                    "path": "/tmp/stair-drop/status.json",
                },
            ),
            mock.patch.object(
                MODULE,
                "_replay",
                return_value={
                    "status": "pass",
                    "physics_source": "native-ovphysx-readback",
                    "render_class": "blender-replay",
                    "gif": "/tmp/stair-drop/ovphysx-replay.gif",
                },
            ),
        ):
            result = MODULE._run_configured_demo(settings)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["native_status"], "pass-real")
        self.assertEqual(result["sample_count"], 25)
        self.assertEqual(result["physics_source"], "native-ovphysx-readback")
        self.assertEqual(result["render_class"], "blender-replay")
        self.assertEqual(result["gif"], "/tmp/stair-drop/ovphysx-replay.gif")

    def test_stops_when_preflight_is_blocked(self) -> None:
        blocked = {"status": "blocked", "checks": {"runtime": False}}
        with (
            mock.patch.object(MODULE, "_preflight", return_value=blocked),
            mock.patch.object(MODULE, "_prepare") as prepare,
        ):
            result = MODULE._run_configured_demo({"output_dir": "/tmp/stair-drop"})

        self.assertEqual(
            result,
            {"status": "blocked", "failed_stage": "preflight", "receipt": blocked},
        )
        prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
