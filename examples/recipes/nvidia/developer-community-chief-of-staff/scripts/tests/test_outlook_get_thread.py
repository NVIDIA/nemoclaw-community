# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import sys
import urllib.parse
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

SCRIPT = (
    Path(__file__).parents[2]
    / "agents/hermes/skills/outlook-email-search/scripts/get_thread.py"
)
SPEC = importlib.util.spec_from_file_location("outlook_get_thread", SCRIPT)
assert SPEC and SPEC.loader
GET_THREAD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GET_THREAD
SPEC.loader.exec_module(GET_THREAD)


class OutlookGetThreadTest(TestCase):
    def test_filtered_request_is_sorted_locally(self) -> None:
        graph_response = {
            "value": [
                {
                    "id": "latest",
                    "receivedDateTime": "2026-08-15T12:00:00Z",
                    "body": {"contentType": "text", "content": "Latest"},
                },
                {
                    "id": "earliest",
                    "receivedDateTime": "2026-08-15T10:00:00Z",
                    "body": {"contentType": "text", "content": "Earliest"},
                },
                {
                    "id": "middle",
                    "receivedDateTime": "2026-08-15T11:00:00Z",
                    "body": {"contentType": "text", "content": "Middle"},
                },
            ]
        }

        with patch.object(GET_THREAD, "_graph_get", return_value=graph_response) as get_:
            messages = GET_THREAD.fetch_thread("conversation'quoted", 100)

        path = get_.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        self.assertEqual(
            query["$filter"],
            ["conversationId eq 'conversation''quoted'"],
        )
        self.assertNotIn("$orderby", query)
        self.assertEqual(query["$top"], ["50"])
        self.assertEqual(
            [message["id"] for message in messages],
            ["earliest", "middle", "latest"],
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
