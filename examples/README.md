<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Community Example Catalog

Examples are organized first by artifact type. Reusable recipes are organized
again by contributor provenance.

## NVIDIA Recipes

| Example | Description |
| --- | --- |
| [Developer Community Chief of Staff](recipes/nvidia/developer-community-chief-of-staff/README.md) | Synthesizes Slack, Outlook, GitHub, and mirrored community signals into operating briefs, gaps, priorities, and follow-up recommendations. |
| [Kubernetes GPU Autoscaling](recipes/nvidia/kubernetes-gpu-autoscaling/README.md) | Runs a CPU-only NemoClaw/OpenClaw sandbox through OpenShell on Kubernetes and autoscales authenticated, GPU-backed Ollama inference pods from DCGM utilization. |
| [Memory-Driven Chief of Staff](recipes/nvidia/memory-driven-chief-of-staff/README.md) | Keeps a locally-authoritative, revisable record per inbound email and Slack message, re-judged on a schedule and re-ranked under fixed caps, without writing back to the source. |
| [NV Tech Assistant](recipes/nvidia/nv-tech-assistant/README.md) | Answers NVIDIA technical questions with cited evidence from allowlisted NVIDIA, GitHub, and arXiv sources. |
| [Payment Operations Hermes Assistant](recipes/nvidia/payment-ops-hermes/README.md) | Demonstrates constrained payment screening, evidence preparation, and a platform-enforced human release boundary. |
| [PR Review Advisor](recipes/nvidia/pr-review-advisor/README.md) | Reviews exact pull request heads with a constrained Hermes workflow, produces attested artifacts, and publishes only through a separate maintainer action. |

## Partner Recipes

| Contributor | Example | Description |
| --- | --- | --- |
| BlueTier | [x402 Payment Gate](recipes/partners/bluetier/x402-payment-gate/README.md) | Releases an agent's x402 payments through a maker/checker boundary: the sandboxed agent can only submit payment intents, and a host-side gate outside the sandbox re-screens each one with pre-signature GO/HOLD/STOP verdicts (counterparty reputation, price anomaly, OFAC sanctions) before anything is signed or settled. |
| HPE | [Retail Assistant](recipes/partners/hpe/retail-assistant/README.md) | Provides role-aware retail operations through Telegram, FastAPI, PostgreSQL, Docker Compose, and Helm. |
| Linespotting AB | [Build Remote Agent pairing](recipes/partners/linespotting/gbr-pair/README.md) | Installs host-side `gbr-agent`, which discovers host terminal windows. If NemoClaw or OpenShell is a TTY on that host, a phone can see that TTY the same way it sees any other terminal. There is no NemoClaw-specific adapter. |
| Shrike Security | [Shrike Security Action Governance](recipes/partners/shrike/shrike-security/README.md) | Governs agent tool calls with a `before_tool_call` plugin that returns allow / warn / require_approval / block from Shrike's enforce plane, with host-side secret handling and scoped egress to Shrike. |
| Tavily | [Watchtower](recipes/partners/tavily/watchtower/README.md) | Runs scheduled, cited web monitoring with persistent deduplication and auditable outputs. |

## Community Recipes

| Example | Description |
| --- | --- |
| [Axe A11y Browser Auditor](recipes/community/axe-a11y-browser-auditor/README.md) | Performs automated WCAG accessibility audits, visual screenshots, PDF exports, and network tracing via a sidecar MCP server using axe-core and Patchright with real Google Chrome. |
| [Deep Research Worker](recipes/community/deep-research-worker/README.md) | Queues long-running research tasks from one sandbox to a host-side DeepAgents worker, with a narrow worker-only sandbox policy and optional read-only host-side search integrations. |

## NVIDIA Field Demos

| Example | Description |
| --- | --- |
| [DGX Station Blender and Omniverse](demos/field/blender-omniverse-dgx-station/README.md) | Controls visible Blender on DGX Station, renders with OVRTX, and runs native OVPhysX simulations. |

## Launchables

| Environment | Example | Description |
| --- | --- | --- |
| Brev | [Hermes](launchables/brev/hermes/README.md) | Provides a notebook path from a fresh Brev CPU instance to a NemoClaw-managed Hermes sandbox. |

## Developer Tools

| Example | Description |
| --- | --- |
| [Harness Engineering Playground](tools/harness-engineering-playground/README.md) | Provides an experimental CLI for eval-driven harness profile optimization. It is not an OpenShell blueprint. |

## Contributing An Example

Read [CONTRIBUTING.md](../CONTRIBUTING.md) and the canonical
[example taxonomy and naming policy](../.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md).
Examples must remain independently deployable and must document their
prerequisites, credentials, policies, startup behavior, verification, and
teardown behavior.
