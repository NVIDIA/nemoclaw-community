<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Community Example Catalog

Examples are organized first by artifact type. Reusable recipes are organized
again by contributor provenance.

## NVIDIA Recipes

| Example | Description |
| --- | --- |
| [Developer Community Chief of Staff](recipes/nvidia/developer-community-chief-of-staff/README.md) | Synthesizes Slack, Outlook, GitHub, and mirrored community signals into operating briefs, gaps, priorities, and follow-up recommendations. |
| [NV Tech Assistant](recipes/nvidia/nv-tech-assistant/README.md) | Answers NVIDIA technical questions with cited evidence from allowlisted NVIDIA, GitHub, and arXiv sources. |
| [Payment Operations Hermes Assistant](recipes/nvidia/payment-ops-hermes/README.md) | Demonstrates constrained payment screening, evidence preparation, and a platform-enforced human release boundary. |

## Partner Recipes

| Contributor | Example | Description |
| --- | --- | --- |
| HPE | [Retail Assistant](recipes/partners/hpe/retail-assistant/README.md) | Provides role-aware retail operations through Telegram, FastAPI, PostgreSQL, Docker Compose, and Helm. |
| Shrike Security | [Shrike Security Action Governance](recipes/partners/shrike/shrike-security/README.md) | Governs agent tool calls with a `before_tool_call` plugin that returns allow / warn / require_approval / block from Shrike's enforce plane, with host-side secret handling and scoped egress to Shrike. |
| Tavily | [Watchtower](recipes/partners/tavily/watchtower/README.md) | Runs scheduled, cited web monitoring with persistent deduplication and auditable outputs. |

Future independent contributions without formal organizational provenance
belong under `recipes/community/`.

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
