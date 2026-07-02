# Verifying hep works

## 1. Unit tests (no checkout or API key required)

```bash
cd examples/harness-engineering-playground
uv sync
uv run pytest
```

All adapter and optimizer logic is tested against a `FakeAdapter`
(`tests/unit_tests/fakes.py`), so this step doesn't touch a real deepagents checkout or call the
Anthropic API. Expect all tests to pass before doing anything else.

## 2. CLI smoke test

```bash
uv run hep --help
uv run hep langchain ralph --help
```

Confirms the CLI wires up correctly (Typer app registration, adapter/optimizer imports) without
needing any credentials. The command must work even without the `deepagents` extra installed —
its heavier dependencies are only checked when the command actually runs, not at import/`--help`
time. Confirm the fail-fast guard, without the extra installed:

```bash
uv run hep langchain ralph --model x --profile <any-existing-file> --evals-dir .
```

This should print `error: ... requires the \`deepagents\` extra ...` and exit 1 immediately — not
a raw traceback, and not several seconds into a baseline eval run.

## 3. Baseline run and agentic proposer smoke test against a real deepagents checkout

Requires:
- The bundled `external/deepagents` submodule initialized (`git submodule update --init`), or a
  separate deepagents source checkout with `libs/evals` set up per its own `README.md` (`uv sync`
  inside `libs/evals`) if you'd rather point `--evals-dir` at something else.
- `RALPH_API_KEY` or `ANTHROPIC_API_KEY` set (see `.env.example`).
- Access to the model under evaluation.
- `uv sync --extra deepagents` (installs `deepagents`, `langchain`, `langchain-anthropic` into
  hep's own venv).

```bash
uv run hep langchain ralph \
  --model "<model-spec>" \
  --profile external/deepagents/libs/deepagents/deepagents/profiles/harness/<some-profile>.py \
  --category <one-narrow-category> \
  --max-iters 1 \
  --ralph-max-turns 20
```

`--evals-dir` is omitted — it defaults to the bundled submodule's `libs/evals`. Pass
`--evals-dir <other-checkout>/libs/evals` (and point `--profile` at that checkout too) to run
against a different checkout instead. With `--max-iters 1` this only runs the baseline eval suite
and, if there's a failure, at most one fix attempt — cheap and fast to sanity check.
`--ralph-max-turns 20` here is a deliberate override for a quick, cheap check — the real default
is 500 (see `--help`), sized for genuine investigation of a subtle SDK-internal bug, not a fast
sanity check. Confirm:
- The baseline `passed`/`failed` counts match what running the deepagents eval suite directly
  reports for that category and model.
- The log format matches `[ralph] ...` / `[hep:deepagents] ...` / `[ralph:proposer] ...` prefixed
  lines with no unexpected tracebacks.
- If the proposed fix is rejected (verify still fails), the config file on disk afterward is
  byte-identical to its state before the command ran (`git diff --stat` shows nothing) — this is
  the rollback guarantee, and the single most important check in this section: the agentic session
  only ever edits an isolated workspace copy, never the real file, so this should hold
  unconditionally.

Once the baseline run looks right, increase `--max-iters` and drop `--category` to run the full
improvement loop.

## 4. Custom-profile registration (the `hep_profile_plugin.py` mechanism)

Confirms `--profile` works for a file that does **not** live inside the deepagents checkout —
proving the pytest plugin, not the SDK's own hardcoded built-in imports, is what registered it.

```bash
uv run hep langchain ralph \
  --model "openai:nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B" \
  --profile examples/deepagents/profiles/nvidia_nemotron_3_ultra_base.py \
  --category <one-narrow-category> \
  --max-iters 1
```

Confirm the baseline run's failure count is consistent with a **blank** profile (no
`system_prompt_suffix`, no middleware) — i.e. it should generally show *more* failures than the
same category run against the checkout's real, tuned `_nvidia_nemotron_3_ultra.py`. If the
baseline instead matches the tuned profile's results, the plugin isn't actually taking effect —
check that `-p hep_profile_plugin` appears in the pytest invocation logs and that
`HEP_PROFILE_FILE`/`PYTHONPATH` are set (add `-s` to `pytest_args` or inspect the subprocess
command directly if needed).

## 5. Agentic proposer write-restriction check

Confirms the agentic proposer's write access is genuinely scoped to the one config file, not the
whole checkout — the core safety property the workspace design is built around. Automated in
`tests/unit_tests/test_agentic_proposer_permissions.py` (runs whenever the `deepagents` extra is
installed); to double-check manually against a real run, diff the deepagents checkout's git status
before and after a `ralph` invocation and confirm it's unchanged regardless of whether the
proposed fix was accepted or rolled back — only the `--profile` file itself (outside the checkout,
or one of its tracked files if pointed in-tree) should ever change.
