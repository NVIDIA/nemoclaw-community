# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The Optimizer seam — a technique for searching over config edits.

An Optimizer only calls methods on a HarnessAdapter, never a specific agent
framework's APIs directly, so the same technique (e.g. the ralph loop) can be
reused across any framework that has an adapter implementation.
"""

from __future__ import annotations

import difflib
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hep.adapters.base import HarnessAdapter

_DEFAULT_MAX_ITERS = 5
_DEFAULT_MAX_ITERS_PER_FAILURE = 3
_DEFAULT_VERIFY_RUNS = 1

_MAX_FAILURE_MSG_CHARS = 6000


@dataclass(frozen=True)
class OptimizationResult:
    """Summary of one Optimizer.run() call.

    Attributes:
        total_improvements: Number of failing tasks fixed during the run.
        baseline_passed: Passed-task count from the first eval run.
        baseline_failed: Failed-task count from the first eval run.
        final_passed: Passed-task count from the last eval run.
        final_failed: Failed-task count from the last eval run.
        remaining_failures: Task names still failing when the run ended.
        iters_used: Total fix attempts consumed across all tasks.
    """

    total_improvements: int
    baseline_passed: int
    baseline_failed: int
    final_passed: int
    final_failed: int
    remaining_failures: list[str] = field(default_factory=list)
    iters_used: int = 0

    @property
    def succeeded(self) -> bool:
        """Return True if at least one improvement was made."""
        return self.total_improvements > 0


class Optimizer(ABC):
    """A technique for searching over config edits to fix failing evals."""

    @abstractmethod
    def run(
        self,
        *,
        adapter: HarnessAdapter,
        model: str,
        config_file: Path,
        **kwargs: Any,
    ) -> OptimizationResult:
        """Improve `config_file` against `adapter`'s eval suite for `model`.

        Args:
            adapter: Target-framework adapter supplying eval/config operations.
            model: Model spec under evaluation.
            config_file: Path to the config file to improve in place.
            **kwargs: Optimizer-specific tuning parameters (e.g. `max_iters`).

        Returns:
            Summary of what changed and the final pass/fail counts.
        """
        raise NotImplementedError


def _warn(msg: str) -> None:
    """Print a warning to stderr, prefixed for the ralph-style outer loop."""
    print(f"[ralph] warning: {msg}", file=sys.stderr, flush=True)


def _log(msg: str) -> None:
    """Print a progress message to stdout, prefixed for the ralph-style outer loop."""
    print(f"[ralph] {msg}", flush=True)


def _sanitize_failure_message(msg: str) -> str:
    """Collapse repetitive lines and truncate to _MAX_FAILURE_MSG_CHARS.

    Runaway XML-loop failures produce the same closing tag tens of thousands of
    times. We collapse any run of identical lines to at most 3 occurrences and
    then hard-truncate, so the proposer receives a legible signal rather than a
    wall of repeated-tag noise.
    """
    lines = msg.splitlines()
    max_run_keep = 3
    collapsed: list[str] = []
    run_val: str | None = None
    run_count = 0
    for line in lines:
        stripped = line.strip()
        if stripped == run_val:
            run_count += 1
            if run_count <= max_run_keep:
                collapsed.append(line)
            elif run_count == max_run_keep + 1:
                collapsed.append(f"    ... [{stripped!r} repeated many more times — truncated] ...")
        else:
            run_val = stripped
            run_count = 1
            collapsed.append(line)
    result = "\n".join(collapsed)

    if len(result) > _MAX_FAILURE_MSG_CHARS:
        result = result[:_MAX_FAILURE_MSG_CHARS] + f"\n... [truncated at {_MAX_FAILURE_MSG_CHARS} chars]"
    return result


def _render_diff(original_content: str, new_content: str) -> str:
    """Return a unified diff between `original_content` and `new_content`, or "" if identical."""
    diff = "".join(
        difflib.unified_diff(
            original_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
        )
    )
    return diff.rstrip("\n")


def _extract_trajectory(failure_msg: str) -> str:
    """Extract the trajectory section from a failure message, or empty string."""
    idx = failure_msg.find("trajectory:")
    return failure_msg[idx:].strip() if idx != -1 else ""


@dataclass(frozen=True)
class PriorAttempt:
    """One earlier attempt at fixing the current failure, kept for corrective context.

    Attributes:
        content: What the previous attempt produced — valid config text for a
            `kind="failed_fix"` attempt, or a strategy-specific explanation of
            what went wrong for a `kind="malformed"` attempt (never a real fix
            attempt at all).
        note: Feedback to surface on the next attempt: the new failure message
            for a failed fix, or an explanation of what was malformed/empty.
        kind: `"failed_fix"` if `content` was applied and verified to still
            fail, or `"malformed"` if `content` was never a usable fix attempt
            (e.g. an unparseable single-shot response, or an agentic session
            that produced no usable edit).
    """

    content: str
    note: str
    kind: str = "failed_fix"


@dataclass(frozen=True)
class ProposeOutcome:
    """Result of one "propose a candidate fix" step, strategy-agnostic.

    Attributes:
        content: Proposed replacement config file content, or None if no
            usable fix was produced this attempt.
        give_up: True if the caller should stop retrying this failure
            entirely (the proposer explicitly declined, or a non-retryable
            error occurred) rather than continue to the next attempt.
    """

    content: str | None
    give_up: bool = False


class IterativeFixOptimizer(Optimizer):
    """Shared ralph-style outer loop: propose, apply, verify, roll back, repeat.

    Owns every part of the technique that is independent of *how* a candidate
    fix is produced — the round loop across all failures, the per-failure
    retry loop bounded by `max_iters`/`max_iters_per_failure`, snapshot/
    rollback, and prior-attempt-as-corrective-context threading. Subclasses
    implement only `_propose_fix`, which may call a single LLM completion, an
    agentic tool-using session, or any other strategy for producing one
    candidate config file content string.
    """

    def run(
        self,
        *,
        adapter: HarnessAdapter,
        model: str,
        config_file: Path,
        categories: list[str] | None = None,
        max_iters: int = _DEFAULT_MAX_ITERS,
        max_iters_per_failure: int = _DEFAULT_MAX_ITERS_PER_FAILURE,
        verify_runs: int = _DEFAULT_VERIFY_RUNS,
        report_dir: Path | None = None,
        **kwargs: Any,
    ) -> OptimizationResult:
        """Run the ralph loop against `config_file` until fixed or budget exhausted.

        Args:
            adapter: Target-framework adapter supplying eval/config operations.
            model: Model spec under evaluation.
            config_file: Path to the config file to improve in place.
            categories: Restrict evals to these categories, or None for all.
            max_iters: Max improvement iterations across all failures.
            max_iters_per_failure: Max fix attempts per failing task per round.
            verify_runs: Consecutive passing runs required to confirm a fix.
            report_dir: Directory to write eval report JSON files to. Defaults
                to the config file's parent directory.

        Returns:
            Summary of improvements made and final pass/fail counts.

        Raises:
            FileNotFoundError: `config_file` does not exist.
        """
        if not config_file.is_file():
            raise FileNotFoundError(f"config file not found: {config_file}")

        report_root = report_dir or config_file.parent
        report_file = report_root / "ralph_report.json"
        single_report = report_root / "ralph_single_report.json"

        _log(
            f"=== ralph loop: model={model}  config={config_file.name}"
            f"  max_iters={max_iters}  max_iters_per_failure={max_iters_per_failure}"
            f"  verify_runs={verify_runs} ===\n"
        )
        suite = adapter.run_eval_suite(model, config_file, report_file, categories)
        baseline_passed = suite.get("passed", 0)
        baseline_failed = suite.get("failed", 0)
        failures = suite.get("failures", [])

        if not failures:
            _log(f"baseline: {baseline_passed} passed, 0 failed — nothing to fix")
            return OptimizationResult(
                total_improvements=0,
                baseline_passed=baseline_passed,
                baseline_failed=baseline_failed,
                final_passed=baseline_passed,
                final_failed=baseline_failed,
            )

        _log(f"baseline: {baseline_passed} passed, {baseline_failed} failed")

        total_improvements = 0
        iters_used = 0
        round_num = 0

        # Outer loop: keep attacking failures until the config is clean or the
        # iteration budget is exhausted. Each round re-runs the full suite so
        # that regressions introduced by a fix are caught and fresh failures
        # from a newly-unblocked task are visible to the next round.
        while failures and iters_used < max_iters:
            round_num += 1
            _log(
                f"round {round_num}: {len(failures)} failure(s), "
                f"{max_iters - iters_used} iter(s) remaining\n"
            )
            round_improvements = 0

            for failure in failures:
                if iters_used >= max_iters:
                    break

                task_name = failure["test_name"]
                _log(f"--- fixing: {task_name} ---")
                prior_attempts: list[PriorAttempt] = []
                sdk_context = adapter.collect_context(config_file, failure.get("failure_message", ""))
                # Snapshot before the inner loop — always rolled back to this baseline.
                original_content = adapter.read_config(config_file)

                fixed = False
                attempt = 0
                while iters_used < max_iters and attempt < max_iters_per_failure:
                    iters_used += 1
                    attempt += 1
                    _log(f"  attempt {attempt} (iter {iters_used}/{max_iters})")

                    outcome = self._propose_fix(
                        adapter=adapter,
                        failure=failure,
                        config_code=original_content,
                        prior_attempts=prior_attempts,
                        sdk_context=sdk_context,
                    )

                    if outcome.content is None:
                        if outcome.give_up:
                            _log("  skipping (proposer declined or invalid response)")
                            break
                        _log("  malformed response — recording and moving to next attempt")
                        continue

                    new_content = outcome.content
                    if not adapter.validate_config(new_content):
                        _log("  skipping (proposed fix is not valid config)")
                        break
                    adapter.write_config(config_file, new_content)

                    passed, new_failure_msg = self._verify_fix(
                        adapter, task_name, model, config_file, single_report, verify_runs
                    )
                    if passed:
                        _log(f"  FIXED: {task_name}")
                        fixed = True
                        round_improvements += 1
                        total_improvements += 1
                        break

                    _log("  fix did not help:")
                    diff = _render_diff(original_content, new_content)
                    _log(f"  proposed diff:\n{_sanitize_failure_message(diff)}" if diff else "  (no textual diff)")
                    _log(f"  resulting failure:\n{_sanitize_failure_message(new_failure_msg)}")
                    _log("  rolling back")
                    adapter.write_config(config_file, original_content)
                    prior_attempts.append(PriorAttempt(content=new_content, note=new_failure_msg))

                if not fixed and attempt >= max_iters_per_failure and iters_used < max_iters:
                    _log(f"  per-failure cap reached ({max_iters_per_failure} attempts) — moving on")

                print()

            if round_improvements == 0:
                _log("no improvements this round — stopping")
                break

            _log(f"=== {round_improvements} fix(es) in round {round_num} — re-running suite ===\n")
            suite = adapter.run_eval_suite(model, config_file, report_file, categories)
            failures = suite.get("failures", [])

        if iters_used >= max_iters:
            _log(f"iteration budget exhausted ({max_iters} used)")

        final_passed = suite.get("passed", 0)
        final_failed = suite.get("failed", 0)
        remaining = [f["test_name"] for f in suite.get("failures", [])]

        if total_improvements > 0:
            _log(f"\nresult: {baseline_passed} → {final_passed} passed, {baseline_failed} → {final_failed} failed")
            if remaining:
                _log(f"remaining failures ({len(remaining)}):")
                for name in remaining:
                    _log(f"  {name}")
        else:
            _log("no improvements made")

        return OptimizationResult(
            total_improvements=total_improvements,
            baseline_passed=baseline_passed,
            baseline_failed=baseline_failed,
            final_passed=final_passed,
            final_failed=final_failed,
            remaining_failures=remaining,
            iters_used=iters_used,
        )

    def _propose_fix(
        self,
        *,
        adapter: HarnessAdapter,
        failure: dict[str, Any],
        config_code: str,
        prior_attempts: list[PriorAttempt],
        sdk_context: str = "",
    ) -> ProposeOutcome:
        """Propose one candidate replacement config file content, if any.

        Args:
            adapter: Target-framework adapter, used for context and config-surface text.
            failure: Failure dict from the eval report (test_name, failure_message, etc.).
            config_code: Current content of the config file.
            prior_attempts: Earlier attempts on the same failure, for corrective
                context. Implementations that produce a response with no usable
                fix (rather than a verified-and-rejected fix, which the caller
                records) should append a `kind="malformed"` entry themselves.
            sdk_context: Relevant SDK source context to ground the proposal.

        Returns:
            An outcome carrying the proposed content (if any) and whether the
            caller should give up on this failure entirely.
        """
        raise NotImplementedError

    def _verify_fix(
        self,
        adapter: HarnessAdapter,
        task_name: str,
        model: str,
        config_file: Path,
        report_file: Path,
        verify_runs: int,
    ) -> tuple[bool, str]:
        """Re-run `task_name` up to `verify_runs` times; all must pass.

        Returns:
            `(True, "")` if every run passes, or `(False, failure_msg)` on the
            first failing run.
        """
        for i in range(verify_runs):
            passed, failure_msg = adapter.run_single_test(task_name, model, config_file, report_file)
            if not passed:
                if verify_runs > 1:
                    _log(f"  verify run {i + 1}/{verify_runs}: failed")
                return False, failure_msg
            if verify_runs > 1:
                _log(f"  verify run {i + 1}/{verify_runs}: passed")
        return True, ""
