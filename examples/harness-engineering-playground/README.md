# Harness Engineering Playground (`hep`)

A CLI for automated, eval-driven harness profile improvement. `hep` is a standalone dev-tool
example — a CLI you run against a source checkout, not an OpenShell-run agent blueprint like the
other examples in this repository.

`hep` is built around two extension seams:

- **`HarnessAdapter`** — knows how to run one target framework's eval suite and read/write/validate
  its config file. `DeepAgentsAdapter` (targeting the [LangChain deepagents SDK](https://github.com/langchain-ai/deepagents))
  is the first implementation.
- **`Optimizer`** — a technique for searching over config edits to fix failing evals.
  - **`RalphLoopOptimizer`** (`hep langchain ralph`) proposes a fix via a bounded
    tool-using deep-agent session built on LangChain's `deepagents` — the model gets real
    `read_file`/`edit_file`/`grep`/`glob` tools scoped to an isolated workspace, plus read-only
    access to the real SDK and eval-suite source trees, so it can investigate instead of guessing
    from a fixed snippet. It shares its propose/apply/verify/roll-back outer loop
    (`IterativeFixOptimizer`) with any other `Optimizer` implementation. Requires the
    `deepagents` extra (`uv sync --extra deepagents`).

An `Optimizer` only calls `HarnessAdapter` methods, never a specific framework's APIs directly —
so the same technique runs unmodified against any framework with an adapter, and a new technique
is immediately usable against every existing adapter.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- An Anthropic API key (or an Anthropic-compatible endpoint) for the frontier model that proposes
  fixes
- The bundled `deepagents` git submodule (`external/deepagents`), initialized via
  `git submodule update --init` — supplies `libs/evals`, the eval test files used by
  `hep langchain ralph` that aren't published in the `deepagents-evals` pip package.
  `--evals-dir`/`HEP_EVALS_DIR` defaults to this submodule's `libs/evals`; only set it explicitly
  to point at a different checkout.
- The `deepagents` extra (`uv sync --extra deepagents`) — a hard requirement, not optional. It
  installs `deepagents`, `langchain`, and `langchain-anthropic` into hep's own venv.

## Quickstart

```bash
cd examples/harness-engineering-playground
git submodule update --init                 # fetches external/deepagents if not already present
uv sync --extra deepagents
cp .env.example .env   # fill in RALPH_API_KEY (or ANTHROPIC_API_KEY)
uv run hep langchain ralph \
  --model "openai:nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B" \
  --profile external/deepagents/libs/deepagents/deepagents/profiles/harness/_nvidia_nemotron_3_ultra.py \
  --ralph-model anthropic:claude-opus-4-8 \
  --category file_operations \
  --max-iters 5 \
  --verify-runs 3
```

`--evals-dir` is omitted above — it defaults to the bundled submodule. Pass
`--evals-dir /path/to/other-checkout/libs/evals` to point at a different deepagents checkout
instead (e.g. one with local, uncommitted profile tuning of your own).

See [docs/verify-functionality.md](docs/verify-functionality.md) to confirm your setup works
before running a real improvement loop, and the `Extending` section below for how to add a
new `Optimizer` or a new `HarnessAdapter`.

## Try it: optimize a blank profile from scratch

`examples/deepagents/profiles/nvidia_nemotron_3_ultra_base.py` is a deliberately blank
`HarnessProfile` (no prompt tuning, no middleware). Point `ralph` at it directly — no
copying, no editing the submodule checkout at all:

```bash
uv run hep langchain ralph \
  --model "openai:nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B" \
  --profile examples/deepagents/profiles/nvidia_nemotron_3_ultra_base.py \
  --category file_operations \
  --max-iters 5
```

Watch it iteratively rediscover the kind of tuning already checked into deepagents' own built-in
`_nvidia_nemotron_3_ultra.py`.

**This also works for a genuinely custom profile you write yourself** — the profile file doesn't
need to live inside the deepagents checkout, or be one of the SDK's built-in files. Every eval
run passes `--profile`'s path to a small pytest plugin (`hep_profile_plugin.py`, loaded via `-p`)
that imports it and calls its `register()` function before test collection — the same `register()`
convention every built-in profile file already follows
(`deepagents.profiles.harness.harness_profiles.HarnessProfile` +
`register_harness_profile`/`_register_harness_profile_impl`). Point `--profile` at any file
following that shape, anywhere, and `ralph` will tune it — no deepagents source edits
required.

## Layout

```
plugins/
└── hep_profile_plugin.py   — standalone pytest plugin; registers --profile's file before collection
examples/deepagents/profiles/
└── nvidia_nemotron_3_ultra_base.py   — reference blank-baseline profile, runnable as-is
external/deepagents/        — git submodule (langchain-ai/deepagents); default --evals-dir target
src/hep/
├── main.py                 — root Typer app
├── adapters/
│   ├── base.py             — HarnessAdapter ABC
│   └── deepagents.py       — DeepAgentsAdapter
├── optimizers/
│   ├── base.py                  — Optimizer ABC + OptimizationResult + IterativeFixOptimizer
│   │                               (shared propose/apply/verify/roll-back outer loop)
│   ├── _proposer_workspace.py    — shared isolated-workspace scaffolding for agentic proposers
│   │                               (task.md/current/proposal.md/history layout)
│   ├── ralph.py                   — RalphLoopOptimizer (deepagents-based agentic proposer)
│   └── _agentic_proposer.py      — the one module that imports deepagents/LangChain; narrow on
│                                    purpose so the hard dependency's absence fails fast and
│                                    cleanly at the CLI boundary
└── cli/
    └── langchain.py        — `hep langchain ralph`
tests/unit_tests/           — adapter/optimizer tests against a FakeAdapter
```

## Extending

**New optimization technique for an existing framework** — implement `Optimizer`, add a CLI
command under the relevant `cli/<framework>.py` group. It can reuse any existing adapter.

**New target framework** — implement `HarnessAdapter`, add a `cli/<framework>.py` Typer group
registering it against `RalphLoopOptimizer` (or any other existing `Optimizer`) unmodified.
