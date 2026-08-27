<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Community Example Catalog

Examples are organized first by artifact type. Reusable recipes are organized
again by contributor provenance. Industry is an independent discovery field.
This file is generated from the catalog metadata block at the top of each
example README. Edit that README, then run
`python3 scripts/build_catalog.py --write` from the repository root.

## NVIDIA Recipes

| Example | Industry | Description |
| --- | --- | --- |
| [Agentic AI Learning Path](recipes/nvidia/agentic-ai-learning-path/README.md) | 🎓 Academia/Education | Runs the seven-module Build an Agent workshop in an OpenShell sandbox with an AI tutor. |
| [Developer Community Chief of Staff](recipes/nvidia/developer-community-chief-of-staff/README.md) | ✨ Other | Turns community signals into operating briefs and follow-up recommendations. |
| [Kubernetes GPU Autoscaling](recipes/nvidia/kubernetes-gpu-autoscaling/README.md) | ☁️ Cloud Services | Runs NemoClaw on Kubernetes with GPU-backed Ollama autoscaling. |
| [Memory-Driven Chief of Staff](recipes/nvidia/memory-driven-chief-of-staff/README.md) | ✨ Other | Maintains and re-ranks a revisable local record of email and Slack inputs without writing back to source systems. |
| [NV Tech Assistant](recipes/nvidia/nv-tech-assistant/README.md) | 🖥️ Hardware/Semiconductor | Answers NVIDIA technical questions with citations from allowlisted sources. |
| [Payment Operations Hermes Assistant](recipes/nvidia/payment-ops-hermes/README.md) | 💳 Financial Services | Demonstrates payment screening, evidence preparation, and a platform-enforced human release boundary. |
| [PR Review Advisor](recipes/nvidia/pr-review-advisor/README.md) | ✨ Other | Reviews exact pull request (PR) heads with Hermes, produces attested artifacts, and leaves publication to a maintainer. |
| [PR Test Case Assistant](recipes/nvidia/pr-test-case-assistant/README.md) | ✨ Other | Reads public GitHub pull requests and drafts grounded feature test cases through Slack. |

## Partner Recipes

| Contributor | Example | Industry | Description |
| --- | --- | --- | --- |
| BlueTier Operations | [x402 Payment Gate](recipes/partners/bluetier/x402-payment-gate/README.md) | 💳 Financial Services | Screens x402 payment intents through a host-side maker/checker gate before signing or settlement. |
| HPE | [Retail Assistant](recipes/partners/hpe/retail-assistant/README.md) | 🛍️ Retail/Consumer Packaged Goods | Provides role-aware retail operations through Telegram with Docker Compose or Helm deployment paths. |
| Shrike Security, Inc. | [Shrike Security Action Governance](recipes/partners/shrike/shrike-security/README.md) | ✨ Other | Checks OpenClaw tool calls against Shrike policy before they run. |
| Tavily | [Watchtower](recipes/partners/tavily/watchtower/README.md) | ✨ Other | Runs scheduled, cited web monitoring with deduplication and auditable outputs. |

## Community Recipes

| Example | Industry | Description |
| --- | --- | --- |
| [Axe A11y Browser Auditor](recipes/community/axe-a11y-browser-auditor/README.md) | 🌐 Consumer Internet | Audits web pages for accessibility and captures screenshots, PDFs, and network traces. |
| [Deep Research Worker](recipes/community/deep-research-worker/README.md) | ✨ Other | Queues long-running research from a sandbox to a host-side DeepAgents worker. |

## NVIDIA Field Demos

| Example | Industry | Description |
| --- | --- | --- |
| [DGX Station Blender and Omniverse](demos/field/blender-omniverse-dgx-station/README.md) | 🎬 Media & Entertainment | Controls Blender on DGX Station for OVRTX rendering and OVPhysX simulation. |

## Launchables

| Environment | Example | Industry | Description |
| --- | --- | --- | --- |
| Brev | [Hermes](launchables/brev/hermes/README.md) | ☁️ Cloud Services | Creates a NemoClaw-managed Hermes sandbox on a fresh Brev CPU instance through a notebook. |

## Developer Tools

| Example | Industry | Description |
| --- | --- | --- |
| [Agent Memory Benchmark](tools/agent-memory-benchmark/README.md) | ✨ Other | Measures memory-system accuracy and token cost on two synthetic email-and-chat corpora. |
| [Harness Engineering Playground](tools/harness-engineering-playground/README.md) | ✨ Other | Provides an experimental command-line interface for evaluation-driven harness profile optimization. |

## Contributing An Example

Read [CONTRIBUTING.md](../CONTRIBUTING.md) and the canonical
[example taxonomy and naming policy](../.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md).
Examples must remain independently deployable and must document their
prerequisites, credentials, policies, startup behavior, verification, and
teardown behavior. Add structured catalog metadata as described in the
[contributor guide](../CONTRIBUTING.md#catalog-metadata).
