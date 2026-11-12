# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run the cases against a backend and decide a verdict for each one."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Collection, Iterable, List, Mapping, Optional

from .backends import Backend, ExecResult
from .cases import ALLOW, PLANNED, Case

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"
PLANNED_VERDICT = "PLANNED"
NOT_APPLICABLE = "N/A"

# Details use a fixed vocabulary. They never contain command output.
DETAIL_OK = "expected result"
DETAIL_ALLOWED_FAILED = "allowed action failed"
DETAIL_MARKER_MISSING = "allowed action did not return the expected content"
DETAIL_DENIED_SUCCEEDED = "denied action succeeded"
DETAIL_LEAK = "denied action returned protected content"
DETAIL_NO_SIGNATURE = "action failed without a boundary signature"
DETAIL_NOT_IMPLEMENTED = "case is planned and has no script"
DETAIL_NOT_APPLICABLE = "host does not have a trait that the case requires"
DETAIL_HOST_ACTION_MISSING = "host action is not available"
DETAIL_HOST_ACTION_FAILED = "host action failed"

HostActions = Mapping[str, Callable[[], None]]


@dataclass(frozen=True)
class Outcome:
    case: Case
    verdict: str
    detail: str
    exit_code: Optional[int] = None
    matched_signature: Optional[str] = None
    leak_detected: bool = False
    duration_ms: int = 0


def judge(case: Case, result: ExecResult) -> Outcome:
    """Decide the verdict for one completed case."""
    if result.error is not None or result.exit_code is None:
        return Outcome(case, INCONCLUSIVE, result.error or DETAIL_NO_SIGNATURE)

    output = result.output
    if case.expect == ALLOW:
        if result.exit_code != 0:
            return Outcome(case, FAIL, DETAIL_ALLOWED_FAILED, result.exit_code)
        if case.allow_marker and case.allow_marker not in output:
            return Outcome(case, FAIL, DETAIL_MARKER_MISSING, result.exit_code)
        return Outcome(case, PASS, DETAIL_OK, result.exit_code)

    if case.leak_marker and case.leak_marker in output:
        return Outcome(case, FAIL, DETAIL_LEAK, result.exit_code, leak_detected=True)
    if result.exit_code == 0:
        return Outcome(case, FAIL, DETAIL_DENIED_SUCCEEDED, result.exit_code)
    lowered = output.lower()
    for signature in case.deny_signatures:
        if signature in lowered:
            return Outcome(case, PASS, DETAIL_OK, result.exit_code, matched_signature=signature)
    return Outcome(case, INCONCLUSIVE, DETAIL_NO_SIGNATURE, result.exit_code)


def run_case(
    backend: Backend,
    case: Case,
    host_actions: HostActions,
    host_traits: Collection[str] = (),
) -> Outcome:
    if case.status == PLANNED or not case.script:
        return Outcome(case, PLANNED_VERDICT, DETAIL_NOT_IMPLEMENTED)
    if any(trait not in host_traits for trait in case.requires):
        return Outcome(case, NOT_APPLICABLE, DETAIL_NOT_APPLICABLE)
    for name in (case.host_before, case.host_after):
        if name and name not in host_actions:
            return Outcome(case, INCONCLUSIVE, DETAIL_HOST_ACTION_MISSING)

    started = time.monotonic()
    outcome: Optional[Outcome] = None
    restore_failed = False
    try:
        if case.host_before:
            host_actions[case.host_before]()
        outcome = judge(case, backend.run(case.script, case.timeout_seconds))
    except Exception:  # A host action failed. The result is not a boundary result.
        outcome = Outcome(case, INCONCLUSIVE, DETAIL_HOST_ACTION_FAILED)
    finally:
        if case.host_after:
            try:
                host_actions[case.host_after]()
            except Exception:
                restore_failed = True
    if restore_failed:
        outcome = Outcome(case, INCONCLUSIVE, DETAIL_HOST_ACTION_FAILED)
    elapsed = int((time.monotonic() - started) * 1000)
    return Outcome(
        outcome.case, outcome.verdict, outcome.detail, outcome.exit_code,
        outcome.matched_signature, outcome.leak_detected, elapsed,
    )


def run_suite(
    backend: Backend,
    cases: Iterable[Case],
    host_actions: Optional[HostActions] = None,
    host_traits: Collection[str] = (),
) -> List[Outcome]:
    actions = host_actions or {}
    return [run_case(backend, case, actions, host_traits) for case in cases]


def exit_status(outcomes: Iterable[Outcome]) -> int:
    """Return 0 when every runnable case passed, 1 on a failure, 2 when unsure."""
    verdicts = [outcome.verdict for outcome in outcomes]
    if FAIL in verdicts:
        return 1
    if INCONCLUSIVE in verdicts:
        return 2
    return 0


def format_table(outcomes: Iterable[Outcome]) -> str:
    lines = []
    for outcome in outcomes:
        case = outcome.case
        lines.append(
            "%-5s %-3s %-5s %-12s %s" % (
                case.case_id, case.priority, case.expect, outcome.verdict, case.title,
            )
        )
    return "\n".join(lines)
