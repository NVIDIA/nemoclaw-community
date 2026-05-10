# openclaw-omni-demo: OpenClaw Vision Sub-Agent

A NemoClaw/OpenClaw demo that keeps the main agent text-focused and delegates
visual tasks to a `vision-operator` sub-agent backed by Nemotron 3 Nano Omni.

## What This Demonstrates

- OpenClaw multi-agent configuration inside an existing sandbox.
- A `vision-operator` sub-agent that handles image analysis with Omni.
- Main-agent delegation through `agents_list` and `sessions_spawn`.
- A repeatable smoke test for provider auth, direct vision, delegation, and
  missing-image behavior.
- Optional Phoenix host service for consistent observability setup.

## Structure

| Path | Purpose |
|---|---|
| `agents/openclaw/openclaw.json` | Reference config showing the intended provider and agent shape. |
| `agents/openclaw/workspace/` | `AGENTS.md` and `TOOLS.md` copied into the shared OpenClaw workspace. |
| `policy.yaml` | Reference sandbox policy with the NVIDIA/node allowance this demo needs. |
| `scripts/apply-omni-subagent.sh` | Patches a live sandbox with the Omni provider and sub-agent config. |
| `scripts/verify.sh` | End-to-end smoke test. |
| `scripts/fix-spark-gateway.sh` | Recovery helper for restricted network namespace hosts. |
| `extras/` | Optional Phoenix host service. |
| `docs/` | Additional upstream walkthrough and telemetry notes. |

## Requirements

- Docker and a running OpenClaw sandbox created with `nemoclaw onboard`.
- `nemoclaw` and `openshell` CLIs.
- NVIDIA API key with Omni access.
- Main model: `nvidia/nemotron-3-super-120b-a12b`.
- Vision model: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`.

## Quickstart

Onboard a fresh OpenClaw sandbox:

```bash
nemoclaw onboard
```

Configure the example:

```bash
cd examples/openclaw-omni-demo
cp .env.example .env
# edit SANDBOX and NVIDIA_API_KEY
bash scripts/apply-omni-subagent.sh
```

Run the smoke test:

```bash
bash scripts/verify.sh
```

For a one-command apply-and-test loop:

```bash
bash scripts/bring-up.sh
```

## How It Works

The helper updates the live sandbox rather than building a new image. It:

- Adds or refreshes the `nvidia-omni` provider in `/sandbox/.openclaw/openclaw.json`.
- Creates `main` and `vision-operator` agent entries.
- Writes provider auth profiles for the vision sub-agent.
- Copies `AGENTS.md` and `TOOLS.md` into `/sandbox/.openclaw-data/workspace/`.
- Ensures the `nvidia` network policy allows `/usr/local/bin/node`.
- Disables unrelated bundled plugins so validation does not spend time staging
  providers this demo does not use.

The smoke test creates a tiny red image, asks `vision-operator` to inspect it,
then asks the main agent to delegate the same task and write an output file.

## Optional Phoenix

```bash
bash scripts/00-host-services.sh
```

Set `PHOENIX_COLLECTOR_ENDPOINT` and `NEMO_FLOW_PROJECT_NAME=openclaw-omni-demo`
when testing with a NemoFlow-enabled OpenClaw runtime. See
[docs/telemetry.md](docs/telemetry.md) for the runtime caveat and plugin config
shape.
