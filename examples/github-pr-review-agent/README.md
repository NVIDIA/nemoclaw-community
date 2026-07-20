# SPDX-FileCopyrightText: Copyright (c) 2026 munnamihir
# SPDX-License-Identifier: Apache-2.0

# GitHub PR Review Agent

A NemoClaw community example that runs an always-on Hermes agent inside an
OpenShell sandbox to autonomously review GitHub pull requests.

The agent polls a GitHub repository every 15 minutes, fetches the diff for
each new open PR, generates a structured code review using NemoClaw inference,
and posts the review as a GitHub comment — without any manual intervention.

Tested on macOS (Apple Silicon, Sonoma 14.x) and Linux (Ubuntu 22.04).

## Architecture
OpenShell Sandbox
┌──────────────────────────────────────────────────────┐
│  Hermes Agent                                        │
│    │                                                 │
│    ├── github-pr-review skill (always-on watcher)   │
│    │     ├── GET api.github.com/repos/.../pulls      │
│    │     ├── GET api.github.com/repos/.../pulls/diff │
│    │     └── POST api.github.com/repos/.../comments  │
│    │                                                 │
│    └── NemoClaw inference                            │
│          └── integrate.api.nvidia.com/v1/chat        │
└──────────────────────────────────────────────────────┘
All other egress is blocked by policy.yaml
## What it does

1. Polls the configured GitHub repo every 15 minutes for new open PRs
2. Fetches the unified diff for each unreviewed PR
3. Reviews the diff using a Nemotron model via NemoClaw routed inference
4. Posts a structured review comment to the PR on GitHub
5. Tracks reviewed PRs locally to avoid double-reviewing

## Prerequisites

- macOS 13+ or Ubuntu 22.04+
- OpenShell CLI v0.0.38+
- NemoClaw installed
- NVIDIA Build API key (for inference via `integrate.api.nvidia.com`)
- GitHub fine-grained personal access token

## Setup

### 1. Create a GitHub token

Go to github.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens

Grant these permissions on your target repo:
- Pull requests: **Read only**
- Issues: **Read and Write** (needed to post comments)

### 2. Get an NVIDIA API key

Sign up at [build.nvidia.com](https://build.nvidia.com) and generate an API key.

### 3. Configure environment

```bash
cp .env.example .env
# fill in GITHUB_TOKEN, GITHUB_REPO, NVIDIA_API_KEY
```

### 4. Start the agent

```bash
openshell gateway start
bash scripts/bring-up.sh
```

The Hermes agent starts inside the sandbox and begins watching your repo.
Check the Hermes TUI to see it working.

### 5. Local dev (without sandbox)

For local testing without the full sandbox:

```bash
export GITHUB_TOKEN=your_token
export GITHUB_REPO=owner/repo
export NVIDIA_API_KEY=your_nvidia_key

# check once
python3 agents/hermes/skills/github-pr-review/scripts/pr_review.py check

# always-on mode
python3 agents/hermes/skills/github-pr-review/scripts/pr_review.py watch

# review a specific PR
python3 agents/hermes/skills/github-pr-review/scripts/pr_review.py review 42
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | Yes | — | GitHub fine-grained personal access token |
| `GITHUB_REPO` | Yes | — | Target repo in `owner/repo` format |
| `NVIDIA_API_KEY` | Yes | — | NVIDIA Build API key for inference |
| `MODEL` | No | `nvidia/llama-3.1-nemotron-ultra-253b-v1` | Inference model |
| `POLL_INTERVAL_SECONDS` | No | `900` | How often to check for new PRs (seconds) |

## Security

`policy.yaml` restricts sandbox egress to three targets only:
- `api.github.com:443` — GitHub REST API (PRs read, comments write)
- `integrate.api.nvidia.com:443` — NemoClaw routed inference
- `host.openshell.internal:6006` — Phoenix telemetry collector

Nothing else can leave the sandbox.

## Contributing

See the [nemoclaw-community contributing guide](../../CONTRIBUTING.md).
