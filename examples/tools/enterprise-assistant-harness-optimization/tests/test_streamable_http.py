# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path

from pa_style_mock_mcp.streamable_http import SessionRegistries


class _Session:
    pass


class StreamableHttpStateTest(unittest.TestCase):
    def test_session_state_isolated_and_calls_are_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            call_log = Path(temp) / "calls.jsonl"
            registries = SessionRegistries(call_log=call_log)
            first = _Session()
            second = _Session()

            first_registry = registries.for_session(first)
            self.assertIs(first_registry, registries.for_session(first))
            self.assertIsNot(first_registry, registries.for_session(second))
            first_registry.call("connectors.get_status", {"connector": "crm"})

            records = [json.loads(line) for line in call_log.read_text().splitlines()]
            self.assertEqual(
                [record["name"] for record in records], ["connectors.get_status"]
            )


if __name__ == "__main__":
    unittest.main()
