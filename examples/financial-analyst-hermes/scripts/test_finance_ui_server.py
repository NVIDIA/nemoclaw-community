#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finance_ui_server as server


class JsonResponse(BytesIO):
    def __enter__(self) -> JsonResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class FinanceUiServerTest(unittest.TestCase):
    def test_parse_timestamp_normalizes_naive_values_to_utc(self) -> None:
        aware = server.parse_timestamp("2026-06-30T12:00:00Z")
        naive = server.parse_timestamp("2026-06-30T12:00:00")
        self.assertIsNotNone(aware)
        self.assertEqual(aware, naive)
        self.assertIsNone(server.parse_timestamp("not-a-date"))

    def test_select_trace_rows_retains_a_tool_span(self) -> None:
        spans = [
            {"trace_id": "t", "name": f"llm-{index}", "kind": "llm"}
            for index in range(8)
        ]
        spans.append({"trace_id": "t", "name": "terminal", "kind": "tool"})
        selected = server.select_trace_rows(spans, 6)
        self.assertEqual(len(selected), 6)
        self.assertIn("tool", {span["kind"] for span in selected})

    @patch("finance_ui_server.urllib.request.urlopen")
    def test_phoenix_filter_returns_hierarchy_fields(self, urlopen: object) -> None:
        payload = {
            "data": {
                "projects": {
                    "edges": [
                        {
                            "node": {
                                "name": "financial-assistant-agent",
                                "spans": {
                                    "edges": [
                                        {
                                            "node": {
                                                "name": "old",
                                                "spanKind": "LLM",
                                                "statusCode": "OK",
                                                "startTime": "2026-06-30T11:59:00Z",
                                                "spanId": "old-span",
                                                "parentId": "old-parent",
                                                "trace": {"traceId": "old-trace"},
                                            }
                                        },
                                        {
                                            "node": {
                                                "name": "terminal",
                                                "spanKind": "TOOL",
                                                "statusCode": "OK",
                                                "startTime": "2026-06-30T12:01:00Z",
                                                "spanId": "tool-span",
                                                "parentId": "root-span",
                                                "trace": {"traceId": "trace-current"},
                                            }
                                        },
                                    ]
                                },
                            }
                        }
                    ]
                }
            }
        }
        urlopen.return_value = JsonResponse(json.dumps(payload).encode())

        spans = server.fetch_recent_phoenix_spans(since="2026-06-30T12:00:00Z")
        self.assertEqual(
            spans,
            [
                {
                    "name": "terminal",
                    "kind": "tool",
                    "status": "OK",
                    "trace_id": "race-current",
                    "span_id": "tool-span",
                    "parent_id": "root-span",
                    "started_at": "2026-06-30T12:01:00Z",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
