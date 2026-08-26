<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Community Example Catalog

Examples are organized first by artifact type. Reusable recipes are organized
again by contributor provenance.

## NVIDIA Recipes

| Example | Description |
| --- | --- |
| [Agentic AI Learning Path](recipes/nvidia/agentic-ai-learning-path/README.md) | Runs the seven-module Build an Agent workshop in an OpenShell sandbox with an AI tutor. |
| [Developer Community Chief of Staff](recipes/nvidia/developer-community-chief-of-staff/README.md) | Turns community signals into operating briefs and follow-up recommendations. |
| [Kubernetes GPU Autoscaling](recipes/nvidia/kubernetes-gpu-autoscaling/README.md) | Runs NemoClaw on Kubernetes with GPU-backed Ollama autoscaling. |
| [Memory-Driven Chief of Staff](recipes/nvidia/memory-driven-chief-of-staff/README.md) | Maintains and re-ranks a revisable local record of email and Slack inputs without writing back. |
| [NV Tech Assistant](recipes/nvidia/nv-tech-assistant/README.md) | Answers NVIDIA technical questions with citations from allowlisted sources. |
| [Payment Operations Hermes Assistant](recipes/nvidia/payment-ops-hermes/README.md) | Demonstrates payment screening, evidence preparation, and a platform-enforced human release boundary. |
| [PR Review Advisor](recipes/nvidia/pr-review-advisor/README.md) | Reviews exact pull request heads with Hermes, produces attested artifacts, and leaves publication to a maintainer. |

## Partner Recipes

| Contributor | Example | Description |
| --- | --- | --- |
| BlueTier | [x402 Payment Gate](recipes/partners/bluetier/x402-payment-gate/README.md) | Screens x402 payment intents through a host-side maker/checker gate before signing or settlement. |
| HPE | [Retail Assistant](recipes/partners/hpe/retail-assistant/README.md) | Provides role-aware retail operations through Telegram with Docker Compose or Helm deployment paths. |
| Shrike Security | [Shrike Security Action Governance](recipes/partners/shrike/shrike-security/README.md) | Applies Shrike decisions before agent tool calls run. |
| Tavily | [Watchtower](recipes/partners/tavily/watchtower/README.md) | Runs scheduled, cited web monitoring with deduplication and auditable outputs. |

## Community Recipes

| Example | Description |
| --- | --- |
| [Axe A11y Browser Auditor](recipes/community/axe-a11y-browser-auditor/README.md) | Audits web pages for accessibility and captures screenshots, PDFs, and network traces. |
| [Deep Research Worker](recipes/community/deep-research-worker/README.md) | Queues long-running research from a sandbox to a host-side DeepAgents worker. |

## NVIDIA Field Demos

| Example | Description |
| --- | --- |
| [DGX Station Blender and Omniverse](demos/field/blender-omniverse-dgx-station/README.md) | Controls Blender on DGX Station for OVRTX rendering and OVPhysX simulation. |

## Launchables

| Environment | Example | Description |
| --- | --- | --- |
| Brev | [Hermes](launchables/brev/hermes/README.md) | Takes a fresh Brev CPU instance to a NemoClaw-managed Hermes sandbox through a notebook. |

## Developer Tools

| Example | Description |
| --- | --- |
| [Agent Memory Benchmark](tools/agent-memory-benchmark/README.md) | Measures the memory a system builds from a corpus: it feeds a system synthetic email and chat, asks 186 questions on one corpus and 96 on a second, and reports accuracy per question type alongside ingest and per-answer token cost. |
| [Harness Engineering Playground](tools/harness-engineering-playground/README.md) | Provides an experimental command-line interface for evaluation-driven harness profile optimization. |

## Contributing An Example

Read [CONTRIBUTING.md](../CONTRIBUTING.md) and the canonical
[example taxonomy and naming policy](../.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md).
Examples must remain independently deployable and must document their
prerequisites, credentials, policies, startup behavior, verification, and
teardown behavior.
