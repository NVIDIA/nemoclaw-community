# Harness Engineering Playground (`hep`)

> **⚠️ Experimental.** `hep` is an early, evolving example — expect rough
> edges and breaking changes. Today it ships one framework adapter
> (`deepagents`) and one optimizer (`ralph`); the extension seams exist so
> more can be added. Not intended for production use.

`hep` automatically tunes an agent **harness** for a given model so the model performs better on
real agent tasks — it runs a benchmark, has a frontier model diagnose and fix the failures, and
verifies each fix sticks. It's a standalone dev-tool example (a CLI you run against a source
checkout), not an OpenShell-run agent blueprint like the other examples in this repository.

## What problem this solves

A few terms first, since they drive everything below:

- **Agent harness** — the scaffolding wrapped around a raw LLM to turn it into a useful agent: the
  system prompt, the set of tools and their descriptions, and middleware that pre-/post-processes
  tool calls and results. The *same model* behaves very differently under a good vs. a poor
  harness.
- **Harness profile** — deepagents' name for that scaffolding expressed as config for one model,
  a [`HarnessProfile`](https://github.com/langchain-ai/deepagents) with fields like
  `system_prompt_suffix`, `extra_middleware`, and tool-description overrides. deepagents ships
  tuned built-in profiles for popular models; a newer or less-common model often starts with a
  blank or generic profile and underperforms until someone tunes it.
- **The deepagents eval suite** — a pytest-based *behavioral benchmark* (bundled here as the
  `external/deepagents` submodule's `libs/evals`) that runs a model through concrete agent tasks —
  file operations, tool use, memory, retrieval, and more — and scores each task pass/fail on
  whether the agent actually accomplished it. This is the objective signal `hep` optimizes against.

Tuning a harness profile by hand is slow guess-and-check: run the evals, read the failures, tweak
the prompt or middleware, re-run, repeat. `hep` closes that loop automatically. It runs the
benchmark, feeds each failing task to a frontier "proposer" model that can investigate the SDK and
eval-suite source before editing the profile, then re-runs the fix several times to confirm it
holds and doesn't regress anything else — producing a tuned profile the way a careful engineer
would, without the manual grind.

## Architecture

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
cp .env.example .env   # fill in proposer creds (RALPH_API_KEY / ANTHROPIC_API_KEY)
                       # and the model-under-test creds (OPENAI_API_BASE / OPENAI_API_KEY)
uv run --env-file .env hep langchain ralph \
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

## Environment

`hep` does not read `.env` itself — pass `--env-file .env` to `uv run` (as shown above), or export
the variables in your shell. There are two distinct credential sets, plus optional tracing:

- **Proposer model** — the frontier model that diagnoses failures and edits the profile:
  `RALPH_API_KEY` (falls back to `ANTHROPIC_API_KEY`), plus optional `RALPH_MODEL` and
  `RALPH_BASE_URL`.
- **Model under evaluation** — the harness target named by `--model`, using its provider's standard
  LangChain env vars. For an `openai:`-compatible endpoint that's `OPENAI_API_BASE` and
  `OPENAI_API_KEY`. These are inherited by the eval subprocess.
- **LangSmith (optional tracing)** — the bundled eval suite refuses to start unless tracing is
  enabled. To run fully offline with no LangSmith account, set `LANGSMITH_TRACING=true` **and**
  `LANGSMITH_TEST_TRACKING=false` (this satisfies the suite's gate while skipping all LangSmith
  network calls). To log real traces instead, set a valid `LANGSMITH_API_KEY` and drop
  `LANGSMITH_TEST_TRACKING`.

All of these have entries in `.env.example`.

## Try it: optimize a blank profile from scratch

`examples/deepagents/profiles/nvidia_nemotron_3_ultra_base.py` is a deliberately blank
`HarnessProfile` (no prompt tuning, no middleware). Point `ralph` at it directly — no
copying, no editing the submodule checkout at all:

```bash
uv run --env-file .env hep langchain ralph \
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

## Arguments

`hep langchain ralph` options:

| Flag | What it does | Default | Env var |
| --- | --- | --- | --- |
| `--model` | Model spec under evaluation — the harness target | *required* | |
| `--profile` | Path to the `HarnessProfile` Python file to improve | *required* | |
| `--evals-dir` | A deepagents checkout's `libs/evals` directory | bundled `external/deepagents` submodule | `HEP_EVALS_DIR` |
| `--ralph-model` | Proposer model that investigates and edits the profile | `anthropic:claude-opus-4-8` | `RALPH_MODEL` |
| `--ralph-max-turns` | Max tool-call turns per proposer session | `500` | `RALPH_MAX_TURNS` |
| `--ralph-base-url` | Custom Anthropic-compatible base URL for the proposer | none | `RALPH_BASE_URL` |
| `--category` | Restrict evals to a category (repeatable) | all categories | |
| `--max-iters` | Max improvement iterations across all failures | `5` | |
| `--max-iters-per-failure` | Max fix attempts per failing test per round | `3` | |
| `--verify-runs` | Consecutive passing runs required to confirm a fix | `1` | |

Run `uv run hep langchain ralph --help` for the authoritative, always-current list.

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
