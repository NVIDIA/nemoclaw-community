# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for RalphLoopOptimizer against a FakeAdapter (no real checkout, API key, or
`deepagents` import needed — the deep-agent invocation boundary is stubbed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hep.optimizers import ralph
from hep.optimizers.ralph import RalphLoopOptimizer
from tests.unit_tests.fakes import FakeAdapter


def _stub_invoke_agentic_proposer(final_message: str = "Done.", *, write_content: str | None = None):
    """Build a fake `invoke_agentic_proposer` that writes `write_content` (if given) and returns.

    Stubs one level above `create_deep_agent`/`agent.invoke` — mirrors
    `better-harness`'s own test convention of monkeypatching
    `invoke_deepagents_proposer`, not the model call itself.
    """

    def _fake(*, workspace_root: Path, system_prompt, model, max_turns, read_only_routes, **kwargs):
        if write_content is not None:
            (workspace_root / "current" / "profile.py").write_text(write_content, encoding="utf-8")
        return final_message

    return _fake


def test_ralph_fixes_single_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "profile.py"
    config_file.write_text("# original\n")
    adapter = FakeAdapter(initial_failures=[{"test_name": "t1", "failure_message": "boom"}])
    monkeypatch.setattr(
        ralph,
        "invoke_agentic_proposer",
        _stub_invoke_agentic_proposer(write_content="new config content"),
    )

    result = RalphLoopOptimizer().run(adapter=adapter, model="fake-model", config_file=config_file)

    assert result.total_improvements == 1
    assert result.remaining_failures == []
    assert adapter.write_calls[-1] == "new config content"


def test_ralph_no_change_is_treated_as_give_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the agent leaves /current/profile.py untouched, that's the same as a NO_FIX reply."""
    config_file = tmp_path / "profile.py"
    config_file.write_text("# original\n")
    adapter = FakeAdapter(initial_failures=[{"test_name": "t1", "failure_message": "boom"}])
    monkeypatch.setattr(
        ralph, "invoke_agentic_proposer", _stub_invoke_agentic_proposer(write_content=None)
    )

    result = RalphLoopOptimizer().run(adapter=adapter, model="fake-model", config_file=config_file)

    assert result.total_improvements == 0
    assert adapter.single_test_calls == 0  # gave up before ever writing/verifying anything


def test_ralph_recursion_limit_is_recoverable_not_give_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A turn-budget exhaustion should let a later attempt still run, not end the failure outright."""
    config_file = tmp_path / "profile.py"
    config_file.write_text("# original\n")
    adapter = FakeAdapter(initial_failures=[{"test_name": "t1", "failure_message": "boom"}])

    class _FakeGraphRecursionError(Exception):
        pass

    _FakeGraphRecursionError.__name__ = "GraphRecursionError"

    calls = {"count": 0}

    def _fake_invoke(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _FakeGraphRecursionError("Recursion limit of 20 reached.")
        (kwargs["workspace_root"] / "current" / "profile.py").write_text(
            "new config content", encoding="utf-8"
        )
        return "Done."

    monkeypatch.setattr(ralph, "invoke_agentic_proposer", _fake_invoke)

    result = RalphLoopOptimizer().run(
        adapter=adapter, model="fake-model", config_file=config_file, max_iters_per_failure=5
    )

    assert calls["count"] == 2
    assert result.total_improvements == 1


@pytest.mark.parametrize(
    ("message", "expect_retry"),
    [
        ("Error code: 529 - overloaded", True),
        ("rate limit exceeded, please retry", True),
        ("Error code: 404 - {'detail': 'Not Found'}", True),
        ("Error code: 401 - invalid x-api-key", False),
    ],
)
def test_ralph_error_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str, expect_retry: bool
) -> None:
    config_file = tmp_path / "profile.py"
    config_file.write_text("# original\n")
    adapter = FakeAdapter(initial_failures=[{"test_name": "t1", "failure_message": "boom"}])

    calls = {"count": 0}

    def _fake_invoke(**kwargs):
        calls["count"] += 1
        raise RuntimeError(message)

    monkeypatch.setattr(ralph, "invoke_agentic_proposer", _fake_invoke)

    result = RalphLoopOptimizer().run(
        adapter=adapter, model="fake-model", config_file=config_file, max_iters_per_failure=3
    )

    assert result.total_improvements == 0
    assert calls["count"] == (3 if expect_retry else 1)


def test_ralph_rolls_back_on_verify_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "profile.py"
    original_content = "# original\n"
    config_file.write_text(original_content)
    adapter = FakeAdapter(
        initial_failures=[{"test_name": "t1", "failure_message": "boom"}],
        never_fixes=True,
    )
    monkeypatch.setattr(
        ralph,
        "invoke_agentic_proposer",
        _stub_invoke_agentic_proposer(write_content="attempted fix"),
    )

    result = RalphLoopOptimizer().run(
        adapter=adapter,
        model="fake-model",
        config_file=config_file,
        max_iters=6,
        max_iters_per_failure=2,
    )

    assert result.total_improvements == 0
    assert result.remaining_failures == ["t1"]
    assert adapter.read_config(config_file) == original_content
    assert adapter.single_test_calls == 2


def test_ralph_passes_adapter_roots_through_unmodified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The optimizer must not narrow/widen the adapter's read-only roots itself."""
    config_file = tmp_path / "profile.py"
    config_file.write_text("# original\n")
    sdk_root = tmp_path / "sdk"
    evals_root = tmp_path / "evals"
    adapter = FakeAdapter(
        initial_failures=[{"test_name": "t1", "failure_message": "boom"}],
        sdk_root=sdk_root,
        evals_root=evals_root,
    )

    captured: dict[str, object] = {}

    def _fake(*, workspace_root: Path, read_only_routes, **kwargs):
        captured["read_only_routes"] = read_only_routes
        (workspace_root / "current" / "profile.py").write_text("new config content", encoding="utf-8")
        return "Done."

    monkeypatch.setattr(ralph, "invoke_agentic_proposer", _fake)

    RalphLoopOptimizer().run(adapter=adapter, model="fake-model", config_file=config_file)

    assert captured["read_only_routes"] == {"/sdk/": sdk_root, "/evals/": evals_root}


def test_ralph_system_prompt_uses_qualitative_stop_condition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prompt should tell the agent to stop once done, not to count exchanges."""
    config_file = tmp_path / "profile.py"
    config_file.write_text("# original\n")
    adapter = FakeAdapter(initial_failures=[{"test_name": "t1", "failure_message": "boom"}])

    captured: dict[str, object] = {}

    def _fake(*, system_prompt, workspace_root: Path, **kwargs):
        captured["system_prompt"] = system_prompt
        (workspace_root / "current" / "profile.py").write_text("new config content", encoding="utf-8")
        return "Done."

    monkeypatch.setattr(ralph, "invoke_agentic_proposer", _fake)

    RalphLoopOptimizer().run(adapter=adapter, model="fake-model", config_file=config_file)

    prompt = captured["system_prompt"]
    assert "hard budget" not in prompt
    assert "exchanges" not in prompt
    assert "stop" in prompt.lower() and "/proposal.md" in prompt
