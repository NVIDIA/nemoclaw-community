<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Tracing Agent Harness Behavior with NVIDIA NeMo Relay

| Catalog field | Value |
| --- | --- |
| Description | Runs verified Hermes Agent tool-use tasks and produces NeMo Relay traces for local inspection and evaluation. |
| Industry | ✨ Other |
| Requirements | macOS or Linux · Git · curl · Docker · NVIDIA Build API key · internet access for the live research task |
| NemoClaw | N/A |
| Harness | Hermes 0.21.1 |
| OpenShell | N/A |

## At A Glance

| Question | Answer |
| --- | --- |
| Category | Developer Tool |
| Contributor or provenance | NVIDIA |
| Use this when | You need to inspect Hermes Agent model and tool behavior or evaluate one controlled harness change. |
| You will get | A verified terminal-task result, local ATOF and ATIF files, and a Phoenix trace for the research task. |
| Runs on | macOS or Linux with Docker. |
| Requires | Git, curl, Docker, an NVIDIA Build API key, and internet access for the live research task. |
| Verified on | Not yet verified in NemoClaw Community. |
| Evidence level | local/static |
| Support and maturity | Best-effort community support. See [SUPPORT.md](../../../SUPPORT.md). |
| External access, data, and actions | Sends prompts to NVIDIA Build. Example 2 sends a public research query to web services, writes a report under `artifacts/`, and starts a local Phoenix container. |
| Start here | [Run Example 1](#quick-start). |
| Confirm success | [Verify Example 1](#quick-start). |

## Overview

An agent's final response does not tell you everything that happened during the
run. An incorrect result can come from missing context, a poor tool choice, or a
failed call. Even a correct result can hide repeated searches, unnecessary
retries, and extra model calls. Tracing the run helps you find these behaviors
and understand their effect on reliability, latency, and token usage.

[NVIDIA NeMo Relay](https://docs.nvidia.com/nemo/relay/latest/about-nemo-relay/overview)
gives agent developers a common way to observe and control model and tool
execution. [Hermes Agent](https://hermes-agent.nousresearch.com/) includes Relay
natively and maps its sessions, turns, model calls, and tool calls to Relay's
scope hierarchy. Relay records lifecycle events as that work begins and ends,
preserving timing and parent-child relationships.

**In this tutorial, you will:**

1. Set up an isolated environment for Hermes Agent and its built-in NeMo Relay
   integration.
2. Ask Hermes to run a small Python script, verify the expected result, and
   inspect the resulting ATOF event stream and ATIF trajectory.
3. Ask Hermes to find a conference that fits a travel plan, save a verified
   report, and explore the run in Phoenix.
4. Learn how to combine task verification with trace data when evaluating a
   controlled change to the prompt, tools, or agent harness.

## Quick Start

Before you begin, make sure you have:

- A macOS or Linux system.
- [Git](https://git-scm.com/downloads),
  [curl](https://curl.se/download.html), and
  [Docker](https://docs.docker.com/get-started/get-docker/), with Docker running.
- An API key from the
  [Nemotron 3.5 Lightning model page](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b)
  on NVIDIA Build.

### Set Up the Tutorial

Run these commands in order:

```bash
# Clone the tutorial repository.
git clone https://github.com/NVIDIA/nemoclaw-community.git

# Enter the cloned repository.
cd nemoclaw-community/examples/tools/hermes-relay-tracing

# Create the isolated Hermes Agent and NeMo Relay runtime.
./scripts/setup_tutorial_runtime.sh

# Copy the API-key template.
cp keys.env.example keys.env
```

The setup script creates an isolated environment under `.tutorial-runtime/`
and installs Hermes Agent `0.21.1` with its pinned NeMo Relay `0.8.3`
dependency. It does not change your existing Hermes installation.

Open `keys.env` and set `NVIDIA_API_KEY` to the key you generated. The repository
ignores this file, and editing it keeps the key out of your shell history.

```ini
NVIDIA_API_KEY=<your-nvidia-api-key>
```

### Example 1: Run and Trace a Terminal Task

Start with a small, predictable task to confirm that the setup works before
moving to the more realistic scenario in Example 2. The included
[`sample.py`](sample-project/sample.py) script contains one statement:
`print("VALUE=42")`. Hermes sends Nemotron 3.5 Lightning an instruction to run
that file. To complete the task, the model must request Hermes Agent's terminal
tool, which executes the script inside an isolated Docker container.

The runner checks that Hermes returns the exact output `VALUE=42`. A passing
run confirms that the model call, terminal-tool execution, Docker sandbox, and
Relay trace exporters all worked together.

Confirm that Docker is running, build the task image, and start the example:

```bash
# Confirm that the Docker client can reach the Docker service.
docker version

# Build the Docker image for the terminal-tool task.
./scripts/build_tutorial_image.sh

# Run the task and export the ATOF event stream and ATIF trajectory.
./scripts/run_tutorial.sh
```

**What you should see:** On a successful run, Hermes returns `VALUE=42`. The
runner validates the result and trace files, then prints their ATOF and ATIF
summaries. One verified run produced:

```text
ATOF summary:
trace: .../artifacts/runs/<run-id>/atof/run.jsonl
events: 74
completed llm scopes: 2
llm scopes with usage: 2
prompt tokens: 7239
completion tokens: 96
total tokens: 7335
tool calls: 1
tool errors: 0
correlated events: 74

ATIF summary:
trajectory: .../artifacts/runs/<run-id>/atif/trajectory-<session-id>.json
agent: Hermes Agent
model: nvidia/nemotron-3.5-lightning-30b-a3b
steps: 3
llm calls: 2
requested tool calls: 1

Task verified: VALUE=42

Artifacts: .../artifacts/runs/<run-id>
```

The counts, identifiers, and run directory vary between runs. The runner exits
with an error if the result or trace validation fails.

### Why the Task Runs in Docker

Hermes can execute terminal commands, so this tutorial runs them in an isolated
Docker container instead of on your host. The container cannot access the
network, repository checkout, or NVIDIA API key.

## Explore Agent Traces and Run Example 2

After Example 1 succeeds, continue with the [detailed tutorial](tutorial.md).

## License

This repository is licensed under the [Apache License 2.0](../../../LICENSE).

## Screenshot

![Phoenix trace for a completed Nemotron research task, showing model, file, and web spans with token and duration information.](screenshots/phoenix-nemotron-final-llm-span.png)

The detailed tutorial shows how to inspect model and tool spans in Phoenix,
including timing, inputs, outputs, token usage, and errors.

## Cleanup

Example 1 leaves its generated traces in `artifacts/`. Example 2 starts a local
Phoenix container. Remove that container when you finish:

```bash
./scripts/stop_phoenix.sh
```

## Known Limitations

- Example 2 depends on live web search and an external conference website. It
  is useful for trace exploration, not for controlled benchmarking.
- The example is pinned to Hermes Agent `0.21.1` and the NeMo Relay version
  selected by that Hermes release. Run the documented verification after
  changing either dependency.
- Traces can contain prompts, model responses, tool inputs and outputs, and
  file paths. Review trace contents before sharing them.
