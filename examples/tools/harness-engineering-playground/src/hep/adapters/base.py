# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The HarnessAdapter abstract base class — the target-framework seam.

An Optimizer never talks to a specific agent framework directly. It only calls
methods on a HarnessAdapter, so the same optimization technique (e.g. the ralph
loop) can run against any framework that has an adapter implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class HarnessAdapter(ABC):
    """Everything an Optimizer needs to know about one target agent framework.

    Implementations own all framework-specific knowledge: how to run the eval
    suite, how to read/write/validate the config file being tuned, and how to
    describe that config's levers to a frontier model proposing fixes.
    """

    @abstractmethod
    def read_config(self, config_file: Path) -> str:
        """Return the current contents of the config file being tuned."""

    @abstractmethod
    def write_config(self, config_file: Path, content: str) -> None:
        """Persist proposed config content, overwriting the existing file."""

    @abstractmethod
    def validate_config(self, content: str) -> bool:
        """Return True if `content` is a syntactically valid config for this harness."""

    @abstractmethod
    def run_eval_suite(
        self,
        model: str,
        config_file: Path,
        report_file: Path,
        categories: list[str] | None,
    ) -> dict[str, Any]:
        """Run the full eval suite for `model` and return the parsed report.

        Args:
            model: Model spec under evaluation.
            config_file: Path to the config file currently being tuned. Adapters
                that need every eval run to pick up this specific file (rather
                than relying on some other discovery mechanism) use this to wire
                that up on each call, including the baseline run.
            report_file: Path the eval runner should write its JSON report to.
            categories: Restrict to these eval categories, or None for all.

        Returns:
            Parsed report dict with at least `passed`, `failed`, and `failures` keys.
        """

    @abstractmethod
    def run_single_test(
        self,
        node_id: str,
        model: str,
        config_file: Path,
        report_file: Path,
    ) -> tuple[bool, str]:
        """Run one eval node and return (passed, failure_message_or_empty).

        Args:
            node_id: Identifier of the eval task to re-run.
            model: Model spec under evaluation.
            config_file: Path to the config file currently being tuned (see
                `run_eval_suite`).
            report_file: Path the eval runner should write its JSON report to.

        Returns:
            A `(passed, failure_message)` tuple. `failure_message` is empty when
            `passed` is True.
        """

    @abstractmethod
    def extract_task_source(self, task_name: str) -> str | None:
        """Return the source of the eval task identified by `task_name`, if available."""

    @abstractmethod
    def collect_context(self, config_file: Path, failure_message: str) -> str:
        """Return SDK/framework source context relevant to `failure_message`.

        Used to ground the frontier model's fix proposals in the real APIs and
        defaults of the framework, rather than a hardcoded summary.
        """

    @abstractmethod
    def describe_config_surface(self) -> str:
        """Describe this harness's config levers for the optimizer's system prompt.

        Returns:
            Human-readable text explaining what fields/hooks the config file
            exposes and when to use each one — spliced into the frontier
            model's system prompt so it knows what it's allowed to change.
        """
