# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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
    spawn_isolated_subprocess,
    supervise_subprocess,
)


class WorkerSafetyTests(unittest.TestCase):
    def test_research_profile_exposes_only_builtin_search_tools(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            pool = WorkerPool(
                TaskStore(state_dir),
                {
                    "worker_concurrency": 1,
                    "default_tool_profile": "research",
                },
            )
            web = SimpleNamespace(name="web_search")
            docs = SimpleNamespace(name="doc_search")
            transfer = SimpleNamespace(name="transfer_funds")
            deploy = SimpleNamespace(name="deploy_service")
            sql = SimpleNamespace(name="run_sql")

            tools, _, profile = pool._profile_tools(
                {"tool_profile": "research"},
                [web, docs, transfer, deploy, sql],
            )
            pool._http_session.close()

        self.assertEqual(profile, "research")
        self.assertEqual([tool.name for tool in tools], ["web_search", "doc_search"])

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

    def test_timed_out_process_cannot_leave_side_effecting_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sentinel = Path(temp_dir) / "descendant-effect.txt"
            child_code = (
                "import pathlib,sys,time\n"
                "time.sleep(0.5)\n"
                "pathlib.Path(sys.argv[1]).write_text('effect', encoding='utf-8')\n"
            )
            parent_code = (
                "import subprocess,sys,time\n"
                "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]])\n"
                "while True:\n"
                " time.sleep(1)\n"
            )
            process = spawn_isolated_subprocess(
                [sys.executable, "-c", parent_code, child_code, str(sentinel)],
            )

            outcome = supervise_subprocess(
                process,
                threading.Event(),
                timeout_seconds=0.2,
                poll_seconds=0.01,
            )
            self.assertEqual(outcome, "timeout")
            time.sleep(0.6)
            self.assertFalse(sentinel.exists())

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
            process = spawn_isolated_subprocess(
                [sys.executable, "-c", code, str(sentinel)],
            )
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
