# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path

from pa_style_mock_mcp.jsonl import read_relay_jsonl


class RelayJsonlTests(unittest.TestCase):
    def test_recovers_valid_event_after_interrupted_record(self) -> None:
        first = {"atof_version": "0.1", "kind": "event", "uuid": "one"}
        second = {"atof_version": "0.1", "kind": "scope", "uuid": "two"}
        with tempfile.TemporaryDirectory() as raw_temp:
            path = Path(raw_temp) / "events.jsonl"
            path.write_text(json.dumps(first) + "\n" + '{"atof_version":"0.1","data":"cut' + json.dumps(second) + "\n")
            records, recovered = read_relay_jsonl(path)

        self.assertEqual(records, [first, second])
        self.assertEqual(recovered, [2])

    def test_rejects_line_without_complete_event(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            path = Path(raw_temp) / "events.jsonl"
            path.write_text('{"atof_version":"0.1"\n')
            with self.assertRaisesRegex(ValueError, "invalid Relay JSONL"):
                read_relay_jsonl(path)
