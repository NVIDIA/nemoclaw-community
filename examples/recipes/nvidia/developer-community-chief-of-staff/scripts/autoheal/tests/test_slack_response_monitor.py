# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import importlib.util
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "slack-response-monitor.py"
SPEC = importlib.util.spec_from_file_location("slack_response_monitor", MODULE_PATH)
assert SPEC and SPEC.loader
MONITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MONITOR)


class SlackResponseMonitorTest(unittest.TestCase):
    def test_split_allowed_ids(self) -> None:
        users, channels = MONITOR.split_allowed_ids("U123,D456,C789,W321,invalid")
        self.assertEqual(users, ["U123", "W321"])
        self.assertEqual(channels, ["D456", "C789"])

    def test_classifies_transport_errors(self) -> None:
        failures = MONITOR.classify_log_text("HTTP 503 inference service unavailable; Server disconnected; graph.microsoft.com:443 NET:FAIL")
        self.assertEqual(failures, {"inference_proxy", "slack_gateway", "outlook_graph"})

    def test_does_not_treat_normal_graph_traffic_as_a_failure(self) -> None:
        self.assertEqual(MONITOR.classify_log_text("ALLOWED graph.microsoft.com:443 GET /v1.0/me"), set())

    def test_cooldown(self) -> None:
        self.assertFalse(MONITOR.should_remediate(100.0, 200.0, 300))
        self.assertTrue(MONITOR.should_remediate(100.0, 400.0, 300))

    def test_reads_quoted_environment_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("SLACK_ALLOWED_IDS='U123,D456'\n# ignored\n")
            self.assertEqual(MONITOR.read_env(path)["SLACK_ALLOWED_IDS"], "U123,D456")

    def test_remediate_invokes_watchdog_with_bash(self) -> None:
        with mock.patch.object(MONITOR.subprocess, "run") as run:
            MONITOR.remediate("validation", dry_run=False)
        run.assert_called_once_with(["bash", str(MONITOR.WATCHDOG)], check=False)


if __name__ == "__main__":
    unittest.main()
