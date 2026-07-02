# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The one place `RalphLoopOptimizer` imports `deepagents`/LangChain.

Kept narrow so the hard dependency's absence produces one clear ImportError
from one obvious call site, and so tests can stub the boundary function
(`invoke_agentic_proposer`) without ever importing `deepagents` themselves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def ensure_deepagents_available() -> None:
    """Raise ImportError immediately if the `deepagents` extra isn't installed.

    Callers (the CLI) call this eagerly, before running anything, so a
    missing dependency fails fast with clear guidance instead of surfacing
    deep inside a multi-minute eval run as an opaque "agent session failed"
    warning from `RalphLoopOptimizer._invoke_agent`.
    """
    import deepagents.graph  # noqa: F401
    import langchain_anthropic  # noqa: F401
    import langchain_core.messages  # noqa: F401


def build_backend_and_permissions(
    *, workspace_root: Path, read_only_routes: dict[str, Path]
) -> tuple[Any, list[Any]]:
    """Construct the composed backend and write-scoped permissions for one session.

    Split out from `invoke_agentic_proposer` so a test can exercise the real
    `FilesystemBackend`/`FilesystemPermission` construction directly (and
    verify the write-restriction security property) without invoking a model.

    Args:
        workspace_root: The writable proposer workspace, mounted at `/`.
        read_only_routes: Map of virtual path prefix (e.g. "/sdk/") to a real
            directory mounted read-only alongside the workspace root.

    Returns:
        A `(backend, permissions)` tuple ready to pass to `create_deep_agent`.
    """
    from deepagents.backends import CompositeBackend, FilesystemBackend
    from deepagents.middleware.filesystem import FilesystemPermission

    default_backend = FilesystemBackend(root_dir=str(workspace_root), virtual_mode=True)
    routes = {
        prefix: FilesystemBackend(root_dir=str(real_dir), virtual_mode=True)
        for prefix, real_dir in read_only_routes.items()
    }
    backend = (
        CompositeBackend(default=default_backend, routes=routes) if routes else default_backend
    )

    # FilesystemMiddleware evaluates rules in list order and the first match
    # wins. "/**" matches everything, including "/current/**" — so the narrow
    # allow MUST come first (it matches and wins before the catch-all is even
    # considered) and the broad deny MUST come last, as the fallback for
    # everything the narrow rule didn't match. Verified directly against a
    # real FilesystemMiddleware in test_agentic_proposer_permissions.py — the
    # reverse order silently denies /current/** too, since the broad deny
    # would win first for every path, narrow rule or not.
    permissions = [
        FilesystemPermission(
            operations=["write"], paths=["/current/**", "/proposal.md"], mode="allow"
        ),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]
    return backend, permissions


def _resolve_model(model: str, *, base_url: str | None, api_key: str | None) -> Any:
    """Resolve a provider-prefixed model string to whatever `create_deep_agent` expects.

    `create_deep_agent(model=...)` accepts a bare provider-prefixed string
    (resolved via LangChain's `init_chat_model` convention) when no custom
    endpoint is needed. A custom Anthropic-compatible base URL (e.g. an
    internal inference gateway) isn't expressible through that string
    convention, so in that case construct the chat model directly instead.

    Args:
        model: Provider-prefixed model string, e.g. "anthropic:claude-opus-4-8".
        base_url: Custom Anthropic-compatible base URL, or None to use the
            provider's default endpoint via the plain string convention.
        api_key: API key to use when `base_url` is set, or None to fall back
            to `langchain_anthropic.ChatAnthropic`'s own environment lookup.

    Returns:
        The original `model` string if `base_url` is None, or a constructed
        `ChatAnthropic` instance otherwise.

    Raises:
        ValueError: `base_url` is set but `model` isn't an "anthropic:"-prefixed
            spec — a custom base URL is only wired up for that provider today.
    """
    if not base_url:
        return model
    if not model.startswith("anthropic:"):
        raise ValueError(f"a custom base URL needs an anthropic: model, got {model!r}")

    from langchain_anthropic import ChatAnthropic

    kwargs: dict[str, str] = {"base_url": base_url}
    if api_key:
        kwargs["api_key"] = api_key
    return ChatAnthropic(model=model.removeprefix("anthropic:"), **kwargs)


def _final_ai_message_text(result: dict[str, Any]) -> str | None:
    """Return the last non-empty AI message's text content from an agent.invoke() result."""
    from langchain_core.messages import AIMessage

    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage) and message.content:
            return message.content if isinstance(message.content, str) else str(message.content)
    return None


def invoke_agentic_proposer(
    *,
    workspace_root: Path,
    system_prompt: str,
    model: str,
    max_turns: int,
    read_only_routes: dict[str, Path],
    base_url: str | None = None,
    api_key: str | None = None,
) -> str | None:
    """Run one bounded deep-agent session against `workspace_root` and return its final message.

    The agent gets real read/write/edit/grep/glob tools scoped to
    `workspace_root` (writable) plus each entry of `read_only_routes`
    (readable, never writable — enforced by `build_backend_and_permissions`).
    Callers read the candidate config back off disk after this returns; the
    return value here is only the agent's final explanatory message, for
    logging.

    Args:
        workspace_root: The writable proposer workspace (backs the virtual `/`
            root the agent's write-scoped tools operate against).
        system_prompt: Composed system prompt for the proposer agent.
        model: Provider-prefixed model string, e.g. "anthropic:claude-opus-4-8".
        max_turns: `recursion_limit` passed to `agent.invoke`.
        read_only_routes: Map of virtual path prefix (e.g. "/sdk/", "/evals/")
            to a real directory the agent may read but never write.
        base_url: Custom Anthropic-compatible base URL, or None to use the
            provider's default endpoint (see `_resolve_model`).
        api_key: API key to use alongside `base_url`, or None to rely on the
            provider integration's own environment-variable lookup.

    Returns:
        The final AI message's text content, or None if the run produced no
        final AI message.

    Raises:
        ImportError: `deepagents`, `langchain`, or the configured model
            provider's LangChain integration package is not installed.
        ValueError: `base_url` is set but `model` isn't "anthropic:"-prefixed.
        Exception: Any exception `agent.invoke` raises (API errors, recursion
            limit exceeded via `GraphRecursionError`, etc.) propagates to the
            caller, which is responsible for classifying retryable vs. not.
    """
    from deepagents.graph import create_deep_agent
    from langchain_core.messages import HumanMessage

    backend, permissions = build_backend_and_permissions(
        workspace_root=workspace_root, read_only_routes=read_only_routes
    )
    resolved_model = _resolve_model(model, base_url=base_url, api_key=api_key)

    agent = create_deep_agent(
        model=resolved_model, system_prompt=system_prompt, backend=backend, permissions=permissions
    )
    result = agent.invoke(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Read /task.md first. Then inspect /current, /history, and (if useful) "
                        "/sdk and /evals, make the smallest edit needed under /current, and "
                        "finish by writing /proposal.md."
                    )
                )
            ]
        },
        config={"recursion_limit": max_turns},
    )
    return _final_ai_message_text(result)
