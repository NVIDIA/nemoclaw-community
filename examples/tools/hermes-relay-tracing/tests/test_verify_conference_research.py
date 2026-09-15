# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import verify_conference_research

EXPECTED_NAME = "COLT 2026"
EXPECTED_SOURCE = "https://learningtheory.org/colt2026"
EXPECTED_READ_PATH = "/input/travel-plan.md"
EXPECTED_WRITE_PATH = "/output/conference-verification.md"


def successful_tool_events(
    *,
    read_path: str = EXPECTED_READ_PATH,
    source_url: str = f"{EXPECTED_SOURCE}/",
    write_path: str = EXPECTED_WRITE_PATH,
) -> list[dict[str, object]]:
    calls = (
        ("read_file", {"path": read_path}),
        ("web_search", {"query": "conference search"}),
        ("web_extract", {"urls": [source_url]}),
        ("write_file", {"path": write_path}),
    )
    events: list[dict[str, object]] = []
    for index, (name, data) in enumerate(calls):
        uuid = f"tool-{index}"
        events.extend(
            [
                {
                    "kind": "scope",
                    "category": "tool",
                    "scope_category": "start",
                    "uuid": uuid,
                    "name": name,
                    "data": data,
                },
                {
                    "kind": "scope",
                    "category": "tool",
                    "scope_category": "end",
                    "uuid": uuid,
                    "metadata": {"otel.status_code": "OK"},
                },
            ]
        )
    return events


class VerifyConferenceResearchTests(unittest.TestCase):
    def test_returned_tool_failure_cannot_satisfy_the_research_path(self) -> None:
        for index, name in enumerate(("read_file", "web_search", "web_extract", "write_file")):
            with self.subTest(tool=name):
                events = successful_tool_events()
                events[index * 2 + 1]["data"] = json.dumps({"error": "Synthetic tool failure"})
                with self.assertRaisesRegex(ValueError, name):
                    verify_conference_research.validate_research_trace(
                        events, expected_read_path=EXPECTED_READ_PATH,
                        expected_write_path=EXPECTED_WRITE_PATH,
                        expected_source_prefix=EXPECTED_SOURCE,
                    )

    def test_final_response_returns_content_after_the_last_session_id(self) -> None:
        output = "reasoning\nsession_id: first\ndraft\nsession_id: final\nCOLT 2026\n"

        self.assertEqual(
            verify_conference_research.final_response(output), EXPECTED_NAME
        )

    def test_final_response_rejects_missing_answer(self) -> None:
        with self.assertRaisesRegex(ValueError, "did not return"):
            verify_conference_research.final_response("session_id: run\n")

    def test_normalize_answer_accepts_light_markdown(self) -> None:
        self.assertEqual(
            verify_conference_research.normalize_answer("**COLT 2026**"), EXPECTED_NAME
        )

    def test_response_identifies_expected_name_accepts_expanded_name(self) -> None:
        self.assertTrue(
            verify_conference_research.response_identifies_expected_name(
                "Conference on Learning Theory (COLT 2026)", EXPECTED_NAME
            )
        )

    def test_response_identifies_expected_name_rejects_other_conference(self) -> None:
        self.assertFalse(
            verify_conference_research.response_identifies_expected_name(
                "NeurIPS 2026", EXPECTED_NAME
            )
        )

    def test_validate_report_accepts_expected_facts_and_source(self) -> None:
        report = """# COLT 2026

- Dates: June 29-July 3, 2026
- Location: San Diego, California
- Source: https://learningtheory.org/colt2026/
"""

        urls = verify_conference_research.validate_report(
            report,
            expected_name=EXPECTED_NAME,
            expected_source_prefix=EXPECTED_SOURCE,
        )

        self.assertEqual(urls, {"https://learningtheory.org/colt2026/"})

    def test_validate_report_rejects_missing_fact(self) -> None:
        report = """# COLT 2026

- Dates: June 29-July 3, 2026
- Source: https://learningtheory.org/colt2026/
"""

        with self.assertRaisesRegex(ValueError, "San Diego"):
            verify_conference_research.validate_report(
                report,
                expected_name=EXPECTED_NAME,
                expected_source_prefix=EXPECTED_SOURCE,
            )

    def test_validate_report_rejects_unofficial_source(self) -> None:
        report = """# COLT 2026

- Dates: June 29-July 3, 2026
- Location: San Diego, California
- Source: https://example.com/colt2026/
"""

        with self.assertRaisesRegex(ValueError, "official source"):
            verify_conference_research.validate_report(
                report,
                expected_name=EXPECTED_NAME,
                expected_source_prefix=EXPECTED_SOURCE,
            )

    def test_validate_report_rejects_similar_source_path(self) -> None:
        report = """# COLT 2026

- Dates: June 29-July 3, 2026
- Location: San Diego, California
- Source: https://learningtheory.org/colt20260/
"""

        with self.assertRaisesRegex(ValueError, "official source"):
            verify_conference_research.validate_report(
                report,
                expected_name=EXPECTED_NAME,
                expected_source_prefix=EXPECTED_SOURCE,
            )

    def test_validate_research_trace_accepts_required_tool_path(self) -> None:
        verify_conference_research.validate_research_trace(
            successful_tool_events(),
            expected_read_path=EXPECTED_READ_PATH,
            expected_write_path=EXPECTED_WRITE_PATH,
            expected_source_prefix=EXPECTED_SOURCE,
        )

    def test_validate_research_trace_rejects_wrong_read_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "read_file"):
            verify_conference_research.validate_research_trace(
                successful_tool_events(read_path="/etc/hosts"),
                expected_read_path=EXPECTED_READ_PATH,
                expected_write_path=EXPECTED_WRITE_PATH,
                expected_source_prefix=EXPECTED_SOURCE,
            )

    def test_validate_research_trace_rejects_wrong_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "web_extract"):
            verify_conference_research.validate_research_trace(
                successful_tool_events(source_url="https://example.com/"),
                expected_read_path=EXPECTED_READ_PATH,
                expected_write_path=EXPECTED_WRITE_PATH,
                expected_source_prefix=EXPECTED_SOURCE,
            )

    def test_validate_research_trace_rejects_wrong_write_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "write_file"):
            verify_conference_research.validate_research_trace(
                successful_tool_events(write_path="/output/unrelated.md"),
                expected_read_path=EXPECTED_READ_PATH,
                expected_write_path=EXPECTED_WRITE_PATH,
                expected_source_prefix=EXPECTED_SOURCE,
            )

    def test_validate_research_trace_rejects_out_of_order_tool_path(self) -> None:
        events = successful_tool_events()
        events[2:4], events[4:6] = events[4:6], events[2:4]

        with self.assertRaisesRegex(ValueError, "web_extract"):
            verify_conference_research.validate_research_trace(
                events,
                expected_read_path=EXPECTED_READ_PATH,
                expected_write_path=EXPECTED_WRITE_PATH,
                expected_source_prefix=EXPECTED_SOURCE,
            )
