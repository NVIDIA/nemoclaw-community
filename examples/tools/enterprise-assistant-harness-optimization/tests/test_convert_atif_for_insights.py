# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path

from scripts.convert_atif_for_insights import (
    _canonicalize_tool_names,
    _files,
    _harbor_context,
)


class ConvertAtifForInsightsTest(unittest.TestCase):
    def test_canonicalizes_catalog_and_span_names_for_analysis(self) -> None:
        trace = {
            "attributes": {
                "tool_catalog": {
                    "mcp__enterprise_world__chat_search": {"type": "object"},
                    "terminal": {"type": "object"},
                }
            },
            "root_spans": [
                {"tool_name": "mcp__enterprise_world__chat_search"},
                {"tool_name": "terminal"},
            ],
        }

        _canonicalize_tool_names(trace)

        self.assertEqual(
            set(trace["attributes"]["tool_catalog"]), {"chat.search", "terminal"}
        )
        self.assertEqual(
            [span["tool_name"] for span in trace["root_spans"]],
            ["chat.search", "terminal"],
        )

    def test_finds_corpus_and_native_relay_names_without_other_job_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            corpus = root / "corpus.atif.json"
            relay = root / "trial" / "artifacts" / "relay" / "atif" / "trajectory-1.json"
            unrelated = root / "trial" / "result.json"
            relay.parent.mkdir(parents=True)
            corpus.write_text("{}")
            relay.write_text("{}")
            unrelated.write_text("{}")

            self.assertEqual(_files([root]), [corpus, relay])

            unrelated.write_text(
                '{"task_name": "hermes-flywheel/source-coverage", '
                '"verifier_result": {"rewards": {"reward": 0.0}}}'
            )
            report = root / "trial" / "verifier" / "report.json"
            report.parent.mkdir()
            report.write_text('{"passed": false, "failures": ["missing evidence"]}')
            self.assertEqual(
                _harbor_context(relay),
                (
                    "source-coverage",
                    {
                        "harbor.reward": 0.0,
                        "harbor.passed": False,
                        "harbor.failures": ["missing evidence"],
                    },
                ),
            )


if __name__ == "__main__":
    unittest.main()
