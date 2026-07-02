# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""RalphLoopOptimizer — ralph loop with a tool-using proposer, not a single completion.

Ports better-harness's `invoke_deepagents_proposer` pattern (an isolated deep-agent session with
real read/edit/grep/glob file tools, scoped by FilesystemPermission) into hep's ralph loop. The
outer propose/verify/rollback control flow lives in `IterativeFixOptimizer`
(`hep.optimizers.base`) — this module implements only the "propose one candidate fix" step: a
bounded deep-agent session with real file tools scoped to an isolated workspace, plus read-only
access to the actual SDK and eval-suite source trees, so it can investigate rather than guess at
the entire replacement file from a curated, truncated context dump.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from hep.adapters.base import HarnessAdapter
from hep.optimizers._agentic_proposer import invoke_agentic_proposer
from hep.optimizers._proposer_workspace import _ProposerWorkspace, build_proposer_workspace
from hep.optimizers.base import IterativeFixOptimizer, PriorAttempt, ProposeOutcome, _sanitize_failure_message

_DEFAULT_RALPH_MODEL = "anthropic:claude-opus-4-8"
_DEFAULT_RALPH_MAX_TURNS = 500
_AGENT_WORKSPACE_PREFIX = "hep-ralph-"
_WORKSPACE_CONFIG_NAME = "profile.py"

_TRANSIENT_MARKERS = (
    "overloaded",
    "rate limit",
    "timeout",
    "error code: 529",
    # A bare 404 from an Anthropic-compatible gateway (as opposed to
    # Anthropic's own API, which returns a structured not_found_error body)
    # can be a transient routing hiccup rather than a genuine "this model
    # doesn't exist" signal, and retrying costs nothing extra beyond the
    # existing max_iters_per_failure budget — a real misconfiguration will
    # just 404 again on every attempt and still get capped, exactly as it
    # would without this entry, so there's no downside to trying.
    "error code: 404",
)

_SYSTEM_PROMPT = """\
You are an expert harness-config engineer improving a config file so a target model passes more
evals.

{config_surface}

Rules:
- Edit only /current/{config_name}. Do not create or edit any other file under /current.
- You have READ access to /sdk (the real SDK source, if available) and /evals (the real eval
  test suite) — use grep/glob/read_file to verify your understanding of an API or hook signature
  before relying on it; do not guess.
- Read /task.md first for the specific failure, prior attempts, and the current file content.
- Prefer general fixes over case-specific hacks. Don't special-case the exact input values from
  this one failing test if a more general prompt or middleware change addresses the underlying
  behavior — infer the broader policy the failure exposes.
- Make the smallest change needed to address the diagnosed failure. Do not reorganize imports,
  rename functions, or restructure the file beyond what the fix requires.
- If you cannot find a viable fix, leave /current/{config_name} unmodified and explain why in
  /proposal.md.
- Once you have made your edit to /current/{config_name} and written /proposal.md, stop — do not
  continue re-reading or re-verifying files afterward. If you notice you're re-confirming
  something you already confirmed, that's a signal to commit to your current diagnosis and
  finish, not to keep investigating.
- Finish by writing a short explanation to /proposal.md, even if you made no changes.
"""


def _warn(msg: str) -> None:
    """Print a warning to stderr, prefixed for the agentic proposer."""
    print(f"[ralph:proposer] warning: {msg}", file=sys.stderr, flush=True)


def _log(msg: str) -> None:
    """Print a progress message to stdout, prefixed for the agentic proposer."""
    print(f"[ralph:proposer] {msg}", flush=True)


def _is_transient_agent_error(message: str) -> bool:
    """Return True if `message` looks like a transient, retryable model error.

    A LangChain-wrapped model call doesn't reliably expose a `status_code`
    attribute the way the raw Anthropic SDK does (the model may not even be
    Anthropic-hosted), so classification falls back to matching known
    transient-error phrasing in the exception's string representation — the
    same approach `better-harness`'s `_is_transient_model_error` uses.
    """
    lowered = message.lower()
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)


class RalphLoopOptimizer(IterativeFixOptimizer):
    """Ralph loop whose fix proposals come from a bounded deep-agent tool-using session.

    Args:
        ralph_model: `deepagents`/LangChain provider-prefixed model string
            for the proposer agent, e.g. "anthropic:claude-opus-4-8".
        ralph_max_turns: Max LangGraph recursion steps per proposer session
            (passed as `config={"recursion_limit": ...}`).
        ralph_base_url: Custom Anthropic-compatible base URL, or None to use
            the provider's default endpoint.

    Requires the `deepagents` extra (`deepagents`, `langchain`,
    `langchain-anthropic`) to be installed — call
    `hep.optimizers._agentic_proposer.ensure_deepagents_available()` first to
    fail fast with a clear error if it isn't.
    """

    def __init__(
        self,
        *,
        ralph_model: str = _DEFAULT_RALPH_MODEL,
        ralph_max_turns: int = _DEFAULT_RALPH_MAX_TURNS,
        ralph_base_url: str | None = None,
    ) -> None:
        self._ralph_model = ralph_model
        self._ralph_max_turns = ralph_max_turns
        self._ralph_base_url = ralph_base_url

    def _propose_fix(
        self,
        *,
        adapter: HarnessAdapter,
        failure: dict[str, Any],
        config_code: str,
        prior_attempts: list[PriorAttempt],
        sdk_context: str = "",
    ) -> ProposeOutcome:
        """Run one bounded agentic session and return its candidate config, if any."""
        workspace = self._build_workspace(
            adapter=adapter,
            failure=failure,
            config_code=config_code,
            prior_attempts=prior_attempts,
            sdk_context=sdk_context,
        )
        try:
            return self._invoke_agent(adapter=adapter, workspace=workspace)
        finally:
            shutil.rmtree(workspace.root, ignore_errors=True)

    def _build_workspace(
        self,
        *,
        adapter: HarnessAdapter,
        failure: dict[str, Any],
        config_code: str,
        prior_attempts: list[PriorAttempt],
        sdk_context: str,
    ) -> _ProposerWorkspace:
        """Scaffold a fresh, isolated workspace directory for one proposer session."""
        return build_proposer_workspace(
            adapter=adapter,
            failure=failure,
            config_code=config_code,
            prior_attempts=prior_attempts,
            sdk_context=sdk_context,
            workspace_prefix=_AGENT_WORKSPACE_PREFIX,
            config_name=_WORKSPACE_CONFIG_NAME,
        )

    def _invoke_agent(
        self, *, adapter: HarnessAdapter, workspace: _ProposerWorkspace
    ) -> ProposeOutcome:
        """Run the actual deep-agent session, then read the candidate config back off disk."""
        if hasattr(adapter, "sdk_and_evals_roots"):
            sdk_root, evals_dir = adapter.sdk_and_evals_roots()
        else:
            sdk_root, evals_dir = None, None
        read_only_routes: dict[str, Path] = {}
        if sdk_root is not None:
            read_only_routes["/sdk/"] = sdk_root
        if evals_dir is not None:
            read_only_routes["/evals/"] = evals_dir

        system_prompt = _SYSTEM_PROMPT.format(
            config_surface=adapter.describe_config_surface(),
            config_name=_WORKSPACE_CONFIG_NAME,
        )

        try:
            final_message = invoke_agentic_proposer(
                workspace_root=workspace.root,
                system_prompt=system_prompt,
                model=self._ralph_model,
                max_turns=self._ralph_max_turns,
                read_only_routes=read_only_routes,
                base_url=self._ralph_base_url,
                api_key=os.environ.get("RALPH_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"),
            )
        except Exception as exc:  # noqa: BLE001 - any failure here is a proposal failure
            _warn(f"agentic proposer session failed: {exc}")
            # A turn-budget exhaustion (GraphRecursionError) is deterministic
            # given the same task, but the next attempt's updated
            # history/prior_attempts.md might let it finish faster, so treat
            # it as recoverable rather than a hard give-up, same as any other
            # non-explicitly-transient failure below.
            is_recursion_limit = type(exc).__name__ == "GraphRecursionError"
            retryable = is_recursion_limit or _is_transient_agent_error(str(exc))
            return ProposeOutcome(content=None, give_up=not retryable)

        if final_message:
            _log(f"  proposer's final message: {_sanitize_failure_message(final_message)}")

        new_content = workspace.current_config_path.read_text(encoding="utf-8")
        if new_content.strip() == workspace.original_content.strip():
            _log("  agentic proposer made no changes")
            return ProposeOutcome(content=None, give_up=True)
        return ProposeOutcome(content=new_content)
