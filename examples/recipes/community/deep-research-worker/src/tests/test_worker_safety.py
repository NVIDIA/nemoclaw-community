# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from deepagents.middleware.rubric import GraderResponse, RubricMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from task_store import TaskStore
from worker import (
    WorkerPool,
    build_agent_payload,
    build_default_rubric,
    supervise_subprocess,
)


class WorkerSafetyTests(unittest.TestCase):
    def test_research_profile_requires_exact_read_only_mcp_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            pool = WorkerPool(
                TaskStore(state_dir),
                {
                    "worker_concurrency": 1,
                    "default_tool_profile": "research",
                    "allowed_mcp_tools": {"market_lookup", "tamSendEmail"},
                },
            )
            web = SimpleNamespace(name="web_search")
            lookup = SimpleNamespace(name="market_lookup")
            action = SimpleNamespace(name="tamSendEmail")
            unlisted = SimpleNamespace(name="other_lookup")

            tools, _, profile = pool._profile_tools(
                {"tool_profile": "research"},
                [web],
                [lookup, action, unlisted],
            )
            pool._http_session.close()

        self.assertEqual(profile, "research")
        self.assertEqual([tool.name for tool in tools], ["web_search", "market_lookup"])

    def test_rubric_is_present_in_invocation_state(self) -> None:
        rubric = build_default_rubric("Compare two systems", "standard")
        payload = build_agent_payload("Compare two systems", rubric)
        self.assertEqual(payload["rubric"], rubric)
        self.assertIn("Compare two systems", rubric)

    def test_unsatisfied_rubric_requests_another_model_iteration(self) -> None:
        middleware = RubricMiddleware(model="stub:test", max_iterations=2)
        middleware._grade = Mock(
            return_value=GraderResponse(
                result="needs_revision",
                explanation="A required comparison is missing.",
                criteria=[
                    {
                        "name": "comparison",
                        "passed": False,
                        "gap": "No side-by-side evidence.",
                    }
                ],
            )
        )
        state = {
            "messages": [HumanMessage(content="compare"), AIMessage(content="draft")],
            "rubric": "- Include a supported side-by-side comparison",
            "_active_rubric": "- Include a supported side-by-side comparison",
            "_current_grading_run_id": "test-run",
            "_rubric_iterations": 0,
        }
        update = middleware.after_agent(
            state,
            SimpleNamespace(stream_writer=lambda event: None),
        )
        self.assertEqual(update["jump_to"], "model")
        self.assertEqual(update["_rubric_status"], "needs_revision")

    def test_cancelled_process_cannot_continue_side_effects(self) -> None:
        self._assert_process_stops("cancelled")

    def test_timed_out_process_cannot_continue_side_effects(self) -> None:
        self._assert_process_stops("timeout")

    def test_cancellation_wins_race_with_timeout_retry(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            store = TaskStore(state_dir)
            task = store.enqueue("race", max_retries=1)
            claimed = store.claim_next()
            store.mark_cancelling(task["task_id"])
            pool = WorkerPool(store, {"worker_concurrency": 1, "default_task_max_retries": 1})

            pool._retry_after_timeout(claimed, "timed out")
            status = store.get_task(task["task_id"])["status"]
            pool._http_session.close()

        self.assertEqual(status, "cancelled")

    def _assert_process_stops(self, expected_outcome: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sentinel = Path(temp_dir) / "effects.log"
            code = (
                "import pathlib,sys,time\n"
                "p=pathlib.Path(sys.argv[1])\n"
                "while True:\n"
                " p.open('a', encoding='utf-8').write('effect\\n')\n"
                " time.sleep(0.02)\n"
            )
            process = subprocess.Popen([sys.executable, "-c", code, str(sentinel)])
            cancel_event = threading.Event()
            if expected_outcome == "cancelled":
                timer = threading.Timer(0.2, cancel_event.set)
                timer.start()
                timeout = 5.0
            else:
                timer = None
                timeout = 0.2

            outcome = supervise_subprocess(
                process,
                cancel_event,
                timeout_seconds=timeout,
                poll_seconds=0.01,
            )
            if timer:
                timer.join()
            self.assertEqual(outcome, expected_outcome)
            self.assertIsNotNone(process.poll())
            size_after_stop = sentinel.stat().st_size
            time.sleep(0.15)
            self.assertEqual(sentinel.stat().st_size, size_after_stop)


if __name__ == "__main__":
    unittest.main()
