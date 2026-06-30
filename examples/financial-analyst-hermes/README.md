<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoHermes Financial Assistant

A small financial research demo built on NemoClaw, OpenShell, and Hermes. It
streams chat responses, uses policy-scoped public market and SEC helpers, and
shows real Hermes LLM/tool activity from NeMo Relay traces in Phoenix.

The demo intentionally has one core startup command. Hermes uses its native
Relay plugin to export OpenInference traces directly to Phoenix. The browser
never receives a model API key, and no UI request bypasses Hermes with a direct
model call.

## What It Demonstrates

- Public quote snapshots and watchlists
- SEC company facts and filing-derived metrics
- Concise analyst briefs, earnings prep, and risk checklists
- Markdown and sanitized model-generated HTML
- Streaming tokens with an animated thinking state
- Actual Hermes tool and LLM spans in Phoenix
- Optional single-owner Outlook read/reply workflow

## Architecture

```text
Browser :18080
    |
    v
Finance UI server --server-side gateway token--> Hermes API forward :8642
                                              |
                                              v
                                   OpenShell sandbox + policies
                                      |                 |
                                      v                 v
                               Finance skills      Model provider

Hermes native observability/nemo_relay plugin --> Phoenix :6006
```

Hermes is the agent. The Python UI server only serves static files, proxies the
local Hermes API, fetches public watchlist quotes, and reads Phoenix. Skills and
tool execution remain inside OpenShell.

## Tested Versions

| Component    | Version                 | Why                                                 |
| ------------ | ----------------------- | --------------------------------------------------- |
| NemoClaw     | `v0.0.70`               | Latest verified tag when this example was updated   |
| Hermes Agent | `v2026.6.19` / `0.17.0` | Installed by NemoClaw; includes native NeMo Relay   |
| OpenShell    | `0.0.44`                | Version required by NemoClaw `v0.0.70`              |
| Phoenix      | `17.13.0`               | Pinned container image                              |
| Node.js      | `22.23.1`               | Installed user-locally when Node 22+ is unavailable |

Do not independently upgrade OpenShell for this demo. NemoClaw declares and
installs its compatible OpenShell range; a newer standalone OpenShell release
may not satisfy that release's blueprint contract.

## Requirements

- Linux host or Brev instance with Docker
- Git, curl, Python 3, and at least 16 GB RAM recommended
- An OpenAI-compatible chat-completions endpoint, model ID, and API key

The startup script installs NemoClaw, its compatible OpenShell, a user-local
Node.js runtime when needed, and the Hermes sandbox. A cold image build commonly
takes 10 to 15 minutes.

## Start The Demo

From this example directory:

```bash
cp .env.example .env
${EDITOR:-vi} .env
./scripts/demo.sh up
```

For NVIDIA hosted inference, keep the provided URL/model and set
`FINANCE_API_KEY` to a key from [build.nvidia.com](https://build.nvidia.com/).
For another compatible provider, set all three `FINANCE_API_URL`,
`FINANCE_API_KEY`, and `FINANCE_MODEL` values.

`demo.sh up` performs these steps:

1. Starts the pinned Phoenix service.
2. Clones the pinned NemoClaw tag into `.runtime/`.
3. Applies a strict, tested patch enabling Hermes's native Relay extra/config.
4. Runs non-interactive NemoClaw onboarding in a clean environment.
5. Applies the read-only finance and Phoenix egress policies.
6. Installs the four finance skills and the financial SOUL.
7. Starts the Hermes port forward and UI.

Open:

- Financial assistant: `http://127.0.0.1:18080`
- Phoenix: `http://127.0.0.1:6006`

## Start On Brev

From your laptop, connect to the instance:

```bash
brev shell financial-assistant-demo-1
```

On the Brev instance:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community
cd examples/financial-analyst-hermes
cp .env.example .env
${EDITOR:-vi} .env
./scripts/demo.sh up
```

Keep two laptop terminals open for forwarding:

```bash
brev port-forward financial-assistant-demo-1 -p 18080:18080
```

```bash
brev port-forward financial-assistant-demo-1 -p 6006:6006
```

Then use the same two localhost URLs shown above. The Hermes `8642` forward is
host-local and managed by `demo.sh`; it does not need to be exposed publicly.

## Operate And Verify

```bash
./scripts/demo.sh status
./scripts/demo.sh verify
./scripts/demo.sh stop
./scripts/demo.sh start
```

`stop` leaves the NemoClaw sandbox intact. `start` is the normal recovery path
after a host reboot. `verify` asks Hermes a real question, runs a real skill
discovery tool call, confirms correlated LLM/tool spans in Phoenix, and checks
desktop and mobile UI layouts.

Useful logs:

```bash
tail -f .runtime/ui.log
nemohermes financial-analyst logs --follow
docker compose -f observability/phoenix-compose.yml logs --tail 100
```

For root-cause checks and clean recovery, see
[Troubleshooting](docs/troubleshooting.md). For the optional one-owner mailbox
workflow, see [Outlook](docs/outlook.md).

## Demo Security Boundary

The UI listens on `0.0.0.0` so Brev port forwarding can reach it. It is an
unauthenticated booth/demo surface and can invoke the agent; do not expose port
`18080` beyond your intended audience. The Hermes bearer token remains on the
server and is never returned to the browser. Add authentication and TLS before
adapting this example for a shared or production deployment.

The sandbox can reach Phoenix only through the explicit OpenShell policy in
`presets/financial-phoenix-relay.yaml`.

## ATIF Object Storage Status

This demo does not configure downstream ATIF export to S3-compatible storage.
Hermes `0.17.0` locks NeMo Relay `0.3`, and the published Relay `0.4` Python
wheel also lacks the compiled object-store feature. Adding an S3 storage block
therefore fails during Relay initialization. OpenInference traces in Phoenix
are supported and verified; durable ATIF object export should be added after a
stable Relay wheel ships with object-store support.

## Local Checks

These do not require a running sandbox:

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 -m py_compile scripts/*.py skills/*/scripts/*.py
bash -n scripts/*.sh
npm ci
npx playwright install --with-deps chromium
npm test
npm run build
npm audit --audit-level=high
```

## Repository Layout

```text
agents/hermes/SOUL.md            Financial identity and runtime guidance
observability/                   Native Relay config and Phoenix service
presets/                         OpenShell network policies
providers/                       Optional Outlook provider
scripts/demo.sh                  Core install/start/verify entry point
scripts/patch_nemoclaw.py        Strict native Relay integration patch
skills/                          Market, SEC, brief, and analyst playbook skills
ui/                              React streaming chat and activity UI
```

This is public-data research support, not a trading system or source of
personalized investment advice.
