<!--- SPDX-FileCopyrightText: Copyright (c) 2026 munnamihir -->
<!--- SPDX-License-Identifier: Apache-2.0 -->

# GitHub PR Review Agent

A NemoClaw community example that automatically reviews open GitHub pull requests
using a local Ollama model — no API keys, no credits, runs entirely on your machine.

Tested on macOS (Apple Silicon, Sonoma 14.x).

## What it does

- Fetches open PRs from a GitHub repo
- Downloads the unified diff for each PR
- Sends the diff to a local LLM for review
- Posts a structured comment back to the PR on GitHub

Inside an OpenShell sandbox, inference routes through `inference.local` to Nemotron
automatically. For local development, it talks to Ollama instead.

## Prerequisites

- macOS 13+ (Apple Silicon or Intel)
- Python 3.9+
- Node.js 22+ (`nvm install 22`)
- Docker Desktop running
- OpenShell CLI v0.0.38+
- Ollama (for local dev without sandbox)
- A GitHub fine-grained personal access token

## Setup

### 1. Install Ollama

Download from https://ollama.com and install, then pull a model:

    ollama pull llama3.2

### 2. Create a GitHub token

Go to github.com -> Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens

Grant these permissions on your target repo:
- Pull requests: Read and Write
- Issues: Read and Write

### 3. Configure environment

    cp .env.example .env
    # fill in GITHUB_TOKEN and GITHUB_REPO

### 4. Run locally

    # make sure ollama is running
    ollama serve

    # set env vars and run
    export GITHUB_TOKEN=your_token
    export GITHUB_REPO=owner/repo
    python3 agent.py

### 5. Run inside OpenShell sandbox

    openshell gateway start
    openshell sandbox create --from nemoclaw
    openshell sandbox run --policy policy.yaml -- python3 agent.py

Inside the sandbox, inference automatically routes to Nemotron via inference.local.
No Ollama needed.

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| GITHUB_TOKEN | Yes | — | GitHub fine-grained personal access token |
| GITHUB_REPO | Yes | — | Target repo in owner/repo format |
| INFERENCE_URL | No | http://localhost:11434/api/chat | Ollama locally, or inference.local in sandbox |
| MODEL | No | llama3.2 | Any model available in your Ollama install |

## Security

policy.yaml locks the sandbox to two egress targets only:
- api.github.com:443 — GitHub REST API
- inference.local:443 — OpenShell routed inference

Nothing else can leave the sandbox. Your GitHub token and repo contents
stay on your machine.

## Example output

    checking PRs for owner/repo

    PR #1 by @devuser: Add retry logic to payment service
      got diff, sending to model...
      posting comment...
      done

    finished

## Contributing

See the nemoclaw-community contributing guide at ../../CONTRIBUTING.md
