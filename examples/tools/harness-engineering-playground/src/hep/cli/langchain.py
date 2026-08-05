# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""`hep langchain` — commands that target the LangChain deepagents SDK."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hep.adapters.deepagents import DeepAgentsAdapter
from hep.optimizers.ralph import _DEFAULT_RALPH_MAX_TURNS

_DEFAULT_EVALS_DIR = Path(__file__).resolve().parents[3] / "external" / "deepagents" / "libs" / "evals"
"""Bundled deepagents submodule's libs/evals, sibling to this hep example's own root."""

app = typer.Typer(name="langchain", help="Commands targeting the LangChain deepagents SDK.")


@app.command("ralph")
def ralph(
    model: Annotated[str, typer.Option(help="Model spec under evaluation, e.g. openai:nvidia/...")],
    profile: Annotated[
        Path,
        typer.Option(
            exists=True,
            dir_okay=False,
            help="Path to the HarnessProfile Python file to improve.",
        ),
    ],
    evals_dir: Annotated[
        Path,
        typer.Option(
            envvar="HEP_EVALS_DIR",
            exists=True,
            file_okay=False,
            help="Path to a deepagents checkout's libs/evals dir.",
        ),
    ] = _DEFAULT_EVALS_DIR,
    ralph_model: Annotated[
        str,
        typer.Option(
            "--ralph-model",
            envvar="RALPH_MODEL",
            help="Provider-prefixed model for the agentic proposer, e.g. anthropic:claude-opus-4-8.",
        ),
    ] = "anthropic:claude-opus-4-8",
    ralph_max_turns: Annotated[
        int,
        typer.Option(envvar="RALPH_MAX_TURNS", help="Max tool-call turns per proposer session."),
    ] = _DEFAULT_RALPH_MAX_TURNS,
    ralph_base_url: Annotated[
        str | None,
        typer.Option(
            envvar="RALPH_BASE_URL",
            help="Custom Anthropic-compatible base URL for the agentic proposer.",
        ),
    ] = None,
    category: Annotated[
        list[str], typer.Option("--category", help="Restrict evals to this category (repeatable).")
    ] = [],  # noqa: B006 - typer requires a literal default for multi-value options
    max_iters: Annotated[int, typer.Option(help="Max improvement iterations across all failures.")] = 5,
    max_iters_per_failure: Annotated[
        int, typer.Option(help="Max fix attempts per failing test per round.")
    ] = 3,
    verify_runs: Annotated[
        int, typer.Option(help="Consecutive passing runs required to confirm a fix.")
    ] = 1,
) -> None:
    """Run the ralph loop with a tool-using agentic proposer instead of a single-shot completion."""
    try:
        from hep.optimizers._agentic_proposer import ensure_deepagents_available

        ensure_deepagents_available()
        from hep.optimizers.ralph import RalphLoopOptimizer
    except ImportError as exc:
        typer.echo(
            "error: `hep langchain ralph` requires the `deepagents` extra "
            "(deepagents, langchain, langchain-anthropic). Install it with:\n"
            "  uv sync --extra deepagents\n"
            f"Import error: {exc}",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    adapter = DeepAgentsAdapter(evals_dir=evals_dir)
    optimizer = RalphLoopOptimizer(
        ralph_model=ralph_model,
        ralph_max_turns=ralph_max_turns,
        ralph_base_url=ralph_base_url,
    )
    result = optimizer.run(
        adapter=adapter,
        model=model,
        config_file=profile.resolve(),
        categories=category or None,
        max_iters=max_iters,
        max_iters_per_failure=max_iters_per_failure,
        verify_runs=verify_runs,
    )
    raise typer.Exit(code=0 if result.succeeded or result.baseline_failed == 0 else 1)
