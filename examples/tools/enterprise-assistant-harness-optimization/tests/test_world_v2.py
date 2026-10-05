# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_world_v2 import build
from scripts.validate_world_v2 import validate

ROOT = Path(__file__).parents[1]


class WorldV2Test(unittest.TestCase):
    def test_checked_in_fixture_is_reproducible_and_has_fidelity_properties(self) -> None:
        base = json.loads((ROOT / "fixtures" / "world-v1.json").read_text())
        expected = build(base)
        actual = json.loads((ROOT / "fixtures" / "world-v2.json").read_text())
        self.assertEqual(actual, expected)
        errors, stats = validate(ROOT / "fixtures" / "world-v2.json")
        self.assertEqual(errors, [])
        self.assertGreaterEqual(stats["launch_register_matches"], 20)

    def test_validator_rejects_a_small_fixture_mislabeled_as_v2(self) -> None:
        world = json.loads((ROOT / "fixtures" / "world-v1.json").read_text())
        world["world_version"] = "v2"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world-v2.json"
            path.write_text(json.dumps(world))
            errors, _ = validate(path)
        self.assertTrue(any("needs at least" in error for error in errors))
