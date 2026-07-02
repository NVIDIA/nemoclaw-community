# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fake HarnessAdapter for exercising Optimizer logic without a real checkout."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hep.adapters.base import HarnessAdapter


class FakeAdapter(HarnessAdapter):
    """In-memory HarnessAdapter double.

    Args:
        initial_failures: Failure dicts returned by the first `run_eval_suite`
            call. `run_single_test` clears them (simulating a successful fix)
            unless `never_fixes` is True.
        never_fixes: If True, `run_single_test` always reports failure —
            simulates a proposed fix that never resolves the eval.
    """

    def __init__(
        self,
        initial_failures: list[dict[str, Any]] | None = None,
        *,
        never_fixes: bool = False,
        sdk_root: Path | None = None,
        evals_root: Path | None = None,
    ) -> None:
        self._failures = initial_failures or []
        self._never_fixes = never_fixes
        self._sdk_root = sdk_root
        self._evals_root = evals_root
        self.write_calls: list[str] = []
        self.eval_suite_calls = 0
        self.single_test_calls = 0

    def read_config(self, config_file: Path) -> str:
        return config_file.read_text(encoding="utf-8")

    def write_config(self, config_file: Path, content: str) -> None:
        config_file.write_text(content, encoding="utf-8")
        self.write_calls.append(content)

    def validate_config(self, content: str) -> bool:
        return True

    def run_eval_suite(
        self, model: str, config_file: Path, report_file: Path, categories: list[str] | None
    ) -> dict[str, Any]:
        self.eval_suite_calls += 1
        if self._failures:
            return {"passed": 0, "failed": len(self._failures), "failures": self._failures}
        return {"passed": 1, "failed": 0, "failures": []}

    def run_single_test(
        self, node_id: str, model: str, config_file: Path, report_file: Path
    ) -> tuple[bool, str]:
        self.single_test_calls += 1
        if self._never_fixes:
            return False, "still failing"
        self._failures = []
        return True, ""

    def extract_task_source(self, task_name: str) -> str | None:
        return None

    def collect_context(self, config_file: Path, failure_message: str) -> str:
        return ""

    def describe_config_surface(self) -> str:
        return "A fake config exposes a `value: str` field."

    def sdk_and_evals_roots(self) -> tuple[Path | None, Path | None]:
        return self._sdk_root, self._evals_root
