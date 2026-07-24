# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared isolated-workspace scaffolding for agentic proposers.

Engine-agnostic: builds the same `/current/<config_name>`, `/task.md`, `/proposal.md`,
`/history/prior_attempts.md` layout regardless of which agent SDK actually reads/edits it.
Extracted so `RalphLoopOptimizer` (deepagents-based) and any other agentic-proposer optimizer
(e.g. a Claude Agent SDK-based one) share one implementation rather than drifting apart.
"""

from __future__ import annotations

import difflib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hep.adapters.base import HarnessAdapter
from hep.optimizers.base import PriorAttempt, _sanitize_failure_message

_TASK_MD_TEMPLATE = """\
# Ralph Agentic Proposer Task

You are fixing ONE failing eval by editing `/current/{config_name}`.

## Failing test
- Name: {test_name}
- Category: {category}

## Test source
{test_source}

## Failure details
{failure_details}

## Starting point for SDK context (not exhaustive — read /sdk and /evals directly for anything
this doesn't cover)
{sdk_hint}

## Current config file
The file at `/current/{config_name}` currently contains what's shown below (read it directly if
you need to see it again — this is just a starting reference).

{config_code}

## Prior attempts on this exact failure
See `/history/prior_attempts.md`.

## Instructions
1. Read `/current/{config_name}` and, if useful, grep/read files under `/sdk` and `/evals` to
   confirm your understanding of the relevant API, hook signature, or tool behavior before
   changing anything — do not guess.
2. Diagnose what the agent under test actually did wrong, using the test source and failure
   details above.
3. Edit `/current/{config_name}` with the smallest change that addresses the diagnosed failure.
4. Write a short explanation of your diagnosis and fix to `/proposal.md`. If you cannot find a
   viable fix, leave `/current/{config_name}` unmodified and explain why in `/proposal.md` instead.
"""


def _render_prior_attempts_md(prior_attempts: list[PriorAttempt], original_content: str) -> str:
    """Render prior attempts on this failure as unified diffs against the original baseline.

    A diff (rather than replaying each prior attempt's full file content, as
    the single-shot path's fake-conversation-turn replay does) keeps this
    section proportional to what actually changed — there's no fixed
    per-message token budget forcing terseness the way a chat completion API
    imposes, so a multi-hundred-line file repeated 2-3 times over would just
    be noise for the agent to read through.
    """
    if not prior_attempts:
        return "(none yet — this is the first attempt on this failure)"

    sections: list[str] = []
    for i, prior in enumerate(prior_attempts, start=1):
        if prior.kind == "malformed":
            sections.append(
                f"### Attempt {i} (no usable fix)\n\n"
                f"The proposer's previous session ended without producing a usable fix.\n"
                f"Explanation: {prior.note}\n"
            )
            continue

        diff = "\n".join(
            difflib.unified_diff(
                original_content.splitlines(),
                prior.content.splitlines(),
                fromfile="original",
                tofile=f"attempt {i}",
                lineterm="",
            )
        )
        sections.append(
            f"### Attempt {i} (tried, did not fix it)\n\n"
            f"This diff was tried and did not fix the failure:\n\n"
            f"```diff\n{diff}\n```\n\n"
            f"New failure after this attempt:\n{_sanitize_failure_message(prior.note)}\n"
        )
    return "\n\n".join(sections)


@dataclass(frozen=True)
class _ProposerWorkspace:
    """Isolated per-attempt workspace for an agentic proposer.

    Attributes:
        root: Workspace root directory (deleted after each attempt).
        current_config_path: Absolute path, inside the workspace, to the
            writable copy of the config file the agent may edit.
        proposal_path: Absolute path, inside the workspace, to the
            agent-authored explanation file.
        original_content: The config content this workspace was seeded with,
            for detecting whether the agent actually changed anything.
    """

    root: Path
    current_config_path: Path
    proposal_path: Path
    original_content: str


def build_proposer_workspace(
    *,
    adapter: HarnessAdapter,
    failure: dict[str, Any],
    config_code: str,
    prior_attempts: list[PriorAttempt],
    sdk_context: str,
    workspace_prefix: str,
    config_name: str,
) -> _ProposerWorkspace:
    """Scaffold a fresh, isolated workspace directory for one proposer session.

    Args:
        adapter: Target-framework adapter, used for `extract_task_source`.
        failure: Failure dict from the eval report (test_name, failure_message, etc.).
        config_code: Current content of the config file being fixed.
        prior_attempts: Earlier attempts on this same failure, rendered into
            `history/prior_attempts.md`.
        sdk_context: Curated SDK-context hint, embedded in `task.md` alongside
            the live read-only source access every engine also grants.
        workspace_prefix: `tempfile.mkdtemp` prefix, distinguishing which
            engine's workspace this is in logs/`/tmp` listings.
        config_name: Filename for the writable config copy under `/current/`.
    """
    root = Path(tempfile.mkdtemp(prefix=workspace_prefix))

    current_dir = root / "current"
    current_dir.mkdir()
    current_config_path = current_dir / config_name
    current_config_path.write_text(config_code, encoding="utf-8")

    proposal_path = root / "proposal.md"
    proposal_path.write_text("(not written yet)\n", encoding="utf-8")

    history_dir = root / "history"
    history_dir.mkdir()
    (history_dir / "prior_attempts.md").write_text(
        _render_prior_attempts_md(prior_attempts, config_code), encoding="utf-8"
    )

    test_source = adapter.extract_task_source(failure["test_name"]) or "(not available)"
    (root / "task.md").write_text(
        _TASK_MD_TEMPLATE.format(
            config_name=config_name,
            test_name=failure["test_name"],
            category=failure.get("category", "unknown"),
            test_source=test_source,
            failure_details=_sanitize_failure_message(failure.get("failure_message", "")),
            sdk_hint=sdk_context or "(none identified automatically)",
            config_code=config_code,
        ),
        encoding="utf-8",
    )

    return _ProposerWorkspace(
        root=root,
        current_config_path=current_config_path,
        proposal_path=proposal_path,
        original_content=config_code,
    )
