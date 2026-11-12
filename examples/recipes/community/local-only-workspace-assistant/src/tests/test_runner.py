# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Verdicts, host actions, and evidence, tested against a scripted backend."""

import json
import tempfile
import unittest
from pathlib import Path

from localonly import cases as case_table
from localonly import evidence, runner
from localonly.backends import (
    ERROR_NO_EXIT_MARKER,
    ERROR_TIMEOUT,
    EXIT_MARKER,
    ExecResult,
    OpenShellBackend,
    parse,
    wrap,
)
from localonly.cases import ALLOW, DENY, PLANNED, WSL2, Case

SECRET = "TOP-SECRET-FILE-CONTENT-7731"


class ScriptedBackend:
    name = "scripted"

    def __init__(self, result, log=None):
        self.result = result
        self.log = log if log is not None else []

    def run(self, script, timeout_seconds):
        self.log.append("run")
        return self.result


DENY_CASE = Case(
    case_id="T-DENY", title="denied read", priority="P0", expect=DENY, script="cat /x",
    leak_marker="CANARY", deny_signatures=("permission denied",),
)
ALLOW_CASE = Case(
    case_id="T-ALLOW", title="allowed read", priority="P0", expect=ALLOW, script="cat /y",
    allow_marker="MARKER",
)


class JudgeTests(unittest.TestCase):
    def test_denied_with_boundary_signature_passes(self):
        outcome = runner.judge(DENY_CASE, ExecResult(1, "cat: /x: Permission denied\n"))
        self.assertEqual(outcome.verdict, runner.PASS)
        self.assertEqual(outcome.matched_signature, "permission denied")

    def test_denied_action_that_succeeds_fails(self):
        outcome = runner.judge(DENY_CASE, ExecResult(0, "harmless\n"))
        self.assertEqual(outcome.verdict, runner.FAIL)

    def test_leaked_content_fails_even_when_the_exit_code_is_nonzero(self):
        outcome = runner.judge(DENY_CASE, ExecResult(1, "CANARY\npermission denied\n"))
        self.assertEqual(outcome.verdict, runner.FAIL)
        self.assertTrue(outcome.leak_detected)

    def test_failure_without_a_boundary_signature_is_inconclusive(self):
        outcome = runner.judge(DENY_CASE, ExecResult(1, "cat: /x: No such file or directory\n"))
        self.assertEqual(outcome.verdict, runner.INCONCLUSIVE)

    def test_backend_error_is_never_a_pass(self):
        for result in (
            ExecResult(None, error=ERROR_TIMEOUT),
            ExecResult(None, "sandbox not found", error=ERROR_NO_EXIT_MARKER),
        ):
            for case in (DENY_CASE, ALLOW_CASE):
                with self.subTest(error=result.error, case=case.case_id):
                    self.assertEqual(runner.judge(case, result).verdict, runner.INCONCLUSIVE)

    def test_allowed_action_needs_exit_zero_and_the_marker(self):
        self.assertEqual(runner.judge(ALLOW_CASE, ExecResult(0, "MARKER\n")).verdict, runner.PASS)
        self.assertEqual(runner.judge(ALLOW_CASE, ExecResult(0, "other\n")).verdict, runner.FAIL)
        self.assertEqual(runner.judge(ALLOW_CASE, ExecResult(1, "MARKER\n")).verdict, runner.FAIL)


class RunCaseTests(unittest.TestCase):
    def test_planned_case_is_reported_and_not_run(self):
        backend = ScriptedBackend(ExecResult(0, ""))
        planned = Case(case_id="T-PLAN", title="later", priority="P1", expect=DENY, status=PLANNED)
        outcome = runner.run_case(backend, planned, {})
        self.assertEqual(outcome.verdict, runner.PLANNED_VERDICT)
        self.assertEqual(backend.log, [])

    def test_case_that_needs_a_missing_host_trait_is_not_applicable(self):
        backend = ScriptedBackend(ExecResult(2, "ls: /mnt/c: No such file or directory"))
        case = Case(
            case_id="T-WSL", title="windows drive", priority="P0", expect=DENY, script="ls /mnt/c",
            deny_signatures=("no such file or directory",), requires=(WSL2,),
        )
        outcome = runner.run_case(backend, case, {})
        self.assertEqual(outcome.verdict, runner.NOT_APPLICABLE)
        self.assertEqual(backend.log, [])
        self.assertEqual(runner.exit_status([outcome]), 0)
        self.assertEqual(runner.run_case(backend, case, {}, [WSL2]).verdict, runner.PASS)

    def test_host_actions_run_around_the_script(self):
        log = []
        backend = ScriptedBackend(ExecResult(1, "HTTP Error 502\npermission denied"), log)
        case = Case(
            case_id="T-HOST", title="stopped server", priority="P0", expect=DENY, script="x",
            deny_signatures=("permission denied",), host_before="stop", host_after="start",
        )
        actions = {"stop": lambda: log.append("stop"), "start": lambda: log.append("start")}
        self.assertEqual(runner.run_case(backend, case, actions).verdict, runner.PASS)
        self.assertEqual(log, ["stop", "run", "start"])

    def test_restore_action_runs_when_the_first_action_fails(self):
        log = []

        def stop():
            raise RuntimeError("docker failed")

        backend = ScriptedBackend(ExecResult(1, "permission denied"), log)
        case = Case(
            case_id="T-HOST", title="stopped server", priority="P0", expect=DENY, script="x",
            deny_signatures=("permission denied",), host_before="stop", host_after="start",
        )
        outcome = runner.run_case(backend, case, {"stop": stop, "start": lambda: log.append("start")})
        self.assertEqual(outcome.verdict, runner.INCONCLUSIVE)
        self.assertEqual(log, ["start"])

    def test_missing_host_action_is_inconclusive_and_runs_nothing(self):
        backend = ScriptedBackend(ExecResult(1, "permission denied"))
        case = Case(
            case_id="T-HOST", title="stopped server", priority="P0", expect=DENY, script="x",
            deny_signatures=("permission denied",), host_before="stop", host_after="start",
        )
        self.assertEqual(runner.run_case(backend, case, {}).verdict, runner.INCONCLUSIVE)
        self.assertEqual(backend.log, [])

    def test_exit_status_ranks_fail_above_inconclusive(self):
        passed = runner.Outcome(DENY_CASE, runner.PASS, "")
        unsure = runner.Outcome(DENY_CASE, runner.INCONCLUSIVE, "")
        failed = runner.Outcome(DENY_CASE, runner.FAIL, "")
        planned = runner.Outcome(DENY_CASE, runner.PLANNED_VERDICT, "")
        self.assertEqual(runner.exit_status([passed, planned]), 0)
        self.assertEqual(runner.exit_status([passed, unsure]), 2)
        self.assertEqual(runner.exit_status([unsure, failed]), 1)


class EvidenceTests(unittest.TestCase):
    def test_evidence_never_contains_command_output(self):
        leaking = ScriptedBackend(ExecResult(0, "CANARY " + SECRET + "\n"))
        outcomes = runner.run_suite(leaking, [DENY_CASE, ALLOW_CASE])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "evidence.jsonl"
            evidence.write_jsonl(path, outcomes, leaking.name, [WSL2])
            text = path.read_text(encoding="utf-8")
            mode = path.stat().st_mode & 0o777
        self.assertNotIn(SECRET, text)
        self.assertNotIn("CANARY", text)
        self.assertEqual(mode, 0o600)
        records = [json.loads(line) for line in text.splitlines()]
        self.assertEqual([item["case_id"] for item in records], ["T-DENY", "T-ALLOW"])
        self.assertEqual(records[0]["verdict"], runner.FAIL)
        self.assertTrue(records[0]["leak_detected"])
        self.assertEqual(records[0]["host_traits"], [WSL2])
        self.assertEqual(set(records[0]), {
            "schema", "timestamp", "backend", "host_traits", "case_id", "priority", "expect", "verdict",
            "detail", "exit_code", "matched_signature", "leak_detected", "duration_ms",
        })

    def test_summary_table_never_contains_command_output(self):
        leaking = ScriptedBackend(ExecResult(0, SECRET))
        table = runner.format_table(runner.run_suite(leaking, [DENY_CASE]))
        self.assertNotIn(SECRET, table)
        self.assertIn("FAIL", table)


class BackendTests(unittest.TestCase):
    def test_wrapped_script_reports_its_exit_status_last(self):
        wrapped = wrap("cat /x")
        self.assertTrue(wrapped.startswith("( cat /x ) 2>&1;"))
        self.assertIn(EXIT_MARKER, wrapped)

    def test_parse_reads_the_last_exit_marker(self):
        result = parse("out\n" + EXIT_MARKER + "0\nmore\n" + EXIT_MARKER + "13\n")
        self.assertEqual(result.exit_code, 13)
        self.assertIsNone(result.error)
        self.assertIn("more", result.output)

    def test_parse_without_a_marker_is_a_backend_error(self):
        result = parse("Error: sandbox not found\n")
        self.assertIsNone(result.exit_code)
        self.assertEqual(result.error, ERROR_NO_EXIT_MARKER)

    def test_openshell_command_passes_the_script_as_one_argument(self):
        command = OpenShellBackend("test-sandbox").command("cat '/a b'")
        self.assertEqual(command[:8], ["openshell", "sandbox", "exec", "-n", "test-sandbox", "--no-tty", "--", "sh"])
        self.assertEqual(command[8], "-c")
        self.assertEqual(len(command), 10)

    def test_missing_openshell_is_a_backend_error(self):
        backend = OpenShellBackend("test-sandbox", executable="openshell-command-that-does-not-exist")
        result = backend.run("true", 5)
        self.assertIsNotNone(result.error)
        self.assertEqual(runner.judge(DENY_CASE, result).verdict, runner.INCONCLUSIVE)


class CaseTableTests(unittest.TestCase):
    def test_case_ids_are_unique(self):
        ids = [case.case_id for case in case_table.CASES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ready_cases_are_complete(self):
        for case in case_table.CASES:
            if case.status == PLANNED:
                self.assertTrue(case.note, case.case_id)
                continue
            with self.subTest(case=case.case_id):
                self.assertTrue(case.script)
                self.assertIn(case.expect, (ALLOW, DENY))
                if case.expect == DENY:
                    self.assertTrue(case.deny_signatures)
                    for signature in case.deny_signatures:
                        self.assertEqual(signature, signature.lower())
                else:
                    self.assertTrue(case.allow_marker)

    def test_every_filesystem_escape_case_watches_for_the_canary(self):
        for case in case_table.CASES:
            if case_table.CANARY_PATH in case.script:
                self.assertEqual(case.leak_marker, case_table.CANARY_MARKER, case.case_id)

    def test_case_that_stops_inference_restores_it_and_runs_last(self):
        stopping = [case for case in case_table.CASES if case.host_before == "stop_inference"]
        self.assertEqual(len(stopping), 1)
        self.assertEqual(stopping[0].host_after, "start_inference")
        self.assertIs(case_table.CASES[-1], stopping[0])

    def test_markers_match_the_fixture_files(self):
        root = Path(__file__).resolve().parents[2] / "fixtures"
        self.assertIn(
            case_table.WORKSPACE_MARKER, (root / "workspace" / "hello.txt").read_text(encoding="utf-8"),
        )
        self.assertIn(
            case_table.CANARY_MARKER, (root / "image" / "outside-canary.txt").read_text(encoding="utf-8"),
        )

    def test_no_script_names_a_host_tool_of_one_sandbox_technology(self):
        for case in case_table.CASES:
            self.assertNotIn("openshell", case.script, case.case_id)

    def test_cases_about_windows_drives_require_a_wsl2_host(self):
        for case in case_table.CASES:
            if "/mnt/c" in case.script:
                self.assertEqual(case.requires, (WSL2,), case.case_id)

    def test_priority_filter(self):
        self.assertTrue(all(case.priority == "P0" for case in case_table.select("P0")))
        self.assertEqual(case_table.select(), case_table.CASES)


if __name__ == "__main__":
    unittest.main()
