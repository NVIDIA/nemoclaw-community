# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path

import yaml


class TraceAnalystConfigTest(unittest.TestCase):
    def test_ethos_stream_uses_the_versioned_demo_operating_rules(self) -> None:
        root = Path(__file__).parents[1]
        config = yaml.safe_load((root / "configs" / "trace-analyst.yaml").read_text())
        ethos = config["evidence_streams"]["ethos_divergence"]
        ethos_path = root / ethos["ethos_path"]

        self.assertTrue(ethos_path.is_file())
        self.assertIn("authorization to send", ethos_path.read_text())
        self.assertTrue(config["evidence_streams"]["anomaly_and_patterns"])
        self.assertTrue(config["evidence_streams"]["tool_issues"])
        self.assertEqual(config["model"], "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b")
        self.assertEqual(config["api_base"], "https://integrate.api.nvidia.com/v1")


if __name__ == "__main__":
    unittest.main()
