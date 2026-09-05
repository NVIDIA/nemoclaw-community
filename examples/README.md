<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Community Example Catalog

Examples are organized first by artifact type. Reusable recipes are organized
again by contributor provenance. Industry is an independent discovery field.
This file is generated from the catalog metadata table in each
example README. Edit that README, then run
`python3 scripts/build_catalog.py --write` from the repository root.

## [NVIDIA Recipes](recipes/nvidia/README.md)

Reusable agent workflows authored or maintained by NVIDIA, designed as practical starting points that developers can inspect, adapt, and deploy with NemoClaw.

| Example | Industry | Description |
| --- | --- | --- |
| [Agentic AI Learning Path](recipes/nvidia/agentic-ai-learning-path/README.md) | 🎓 Academia/Education | Helps learners work through the seven-module Build an Agent workshop in JupyterLab with an AI tutor that explains concepts, offers graduated hints, and checks progress inside an OpenShell sandbox. |
| [Developer Community Chief of Staff](recipes/nvidia/developer-community-chief-of-staff/README.md) | ✨ Other | Helps developer community leaders align priorities with demand by turning available GitHub, GitLab, forum, Slack, email, and web signals into evidence-grounded briefs, gaps, and follow-up recommendations. |
| [Kubernetes GPU Autoscaling](recipes/nvidia/kubernetes-gpu-autoscaling/README.md) | ☁️ Cloud Services | Helps Kubernetes operators match GPU inference capacity to demand by pairing a CPU-only OpenShell sandbox with Ollama replicas that scale on utilization or latency and return to one after load. |
| [Memory-Driven Chief of Staff](recipes/nvidia/memory-driven-chief-of-staff/README.md) | ✨ Other | Builds a revisable local memory from email and Slack, then ranks obligations against the user's priorities while preserving pins and ignores without changing source systems. |
| [NV Tech Assistant](recipes/nvidia/nv-tech-assistant/README.md) | 🖥️ Hardware/Semiconductor | Helps developers choose and troubleshoot NVIDIA technologies by searching allowlisted documentation, repositories, model catalogs, and forums for current, evidence-linked answers. |
| [Payment Operations Hermes Assistant](recipes/nvidia/payment-ops-hermes/README.md) | 💳 Financial Services | Helps payment operators screen synthetic outbound payments, explain holds, and prepare review packets while OpenShell keeps final release authority with a human outside the Hermes sandbox. |
| [PR Review Advisor](recipes/nvidia/pr-review-advisor/README.md) | ✨ Other | Helps maintainers review exact pull request heads through staged, repository-aware Hermes analysis, producing attested JSON and Markdown findings for inspection before optional publication. |
| [PR Test Case Assistant](recipes/nvidia/pr-test-case-assistant/README.md) | ✨ Other | Helps quality engineers turn public GitHub pull request descriptions and bounded diffs into Slack briefs and proposed, unexecuted feature test cases with source evidence. |
| [Sandboxed Hermes Bot Team](recipes/nvidia/sandboxed-hermes-bots/README.md) | ✨ Other | A team of Hermes bots you talk to from Hermes Desktop, one NemoClaw sandbox each. A bot reaches only what its policy names, and when it needs something it cannot reach, it asks a teammate. |
| [Video Search and Summarization](recipes/nvidia/video-search-and-summarization/README.md) | ✨ Other | Helps video analysts and engineers deploy and operate NVIDIA VSS profiles by chat, using a sandboxed agent that runs the Compose deployment through a host-side MCP server and reports the result. |

## [Partner Recipes](recipes/partners/README.md)

Reusable NemoClaw agent workflows contributed by partner organizations, with attribution and implementation guidance preserved from each contributor.

| Example | Contributor | Industry | Description |
| --- | --- | --- | --- |
| [x402 Payment Gate](recipes/partners/bluetier/x402-payment-gate/README.md) | BlueTier Operations | 💳 Financial Services | Demonstrates a maker-checker gate for x402 payments: a sandboxed agent submits intents, while a host-side Blackwall verdict controls mock signing and settlement before any signature exists. |
| [Retail Assistant](recipes/partners/hpe/retail-assistant/README.md) | HPE | 🛍️ Retail/Consumer Packaged Goods | Helps store employees check inventory and sales or request transfers and reorders through role-aware Telegram conversations scoped to their assigned store. |
| [Shrike Security Action Governance](recipes/partners/shrike/shrike-security/README.md) | Shrike Security, Inc. | ✨ Other | Adds defense-in-depth action governance through an in-sandbox hook that checks each OpenClaw tool call against server-side Shrike policy and blocks prohibited or approval-required calls. |
| [Watchtower](recipes/partners/tavily/watchtower/README.md) | Tavily | ✨ Other | Tracks what changed across chosen web topics and why it matters, producing scheduled, deduplicated Markdown digests and JSON changelogs with source citations. |

## [Community Recipes](recipes/community/README.md)

Reusable NemoClaw agent workflows contributed independently by community members, offering practical starting points for adaptation and experimentation.

| Example | Industry | Description |
| --- | --- | --- |
| [Axe A11y Browser Auditor](recipes/community/axe-a11y-browser-auditor/README.md) | 🌐 Consumer Internet | Helps web teams find WCAG issues through a dedicated sandbox and host-side real Chrome, returning rule-level findings with optional screenshots, PDFs, recordings, and network traces. |
| [Deep Research Worker](recipes/community/deep-research-worker/README.md) | ✨ Other | Adds asynchronous research to a sandbox, so users can queue long-running jobs on a host-side worker, monitor persistent task state, and return later for text or JSON results. |

## [NVIDIA Field Demos](demos/field/README.md)

Bounded NemoClaw demonstrations built for specific NVIDIA field scenarios, hardware, or software environments rather than general-purpose deployment.

| Example | Industry | Description |
| --- | --- | --- |
| [Build-a-Claw Tutorial](demos/field/build-a-claw-tutorial/README.md) | 🎓 Academia/Education | Guides DGX Spark users through serving local multimodal models with llama.cpp, connecting an agent harness, and trying coding, vision, browser, messaging, and speech workflows. |
| [DGX Station Blender and Omniverse](demos/field/blender-omniverse-dgx-station/README.md) | 🎬 Media & Entertainment | Lets users direct a specialized Hermes agent on DGX Station across Blender and NVIDIA Omniverse workflows, producing scene edits, OVRTX renders, native OVPhysX simulations, and replay evidence. |

## [Developer Tools](tools/README.md)

Standalone utilities that help developers build, evaluate, inspect, or operate NemoClaw agents without defining an end-user agent workflow.

| Example | Industry | Description |
| --- | --- | --- |
| [Agent Memory Benchmark](tools/agent-memory-benchmark/README.md) | ✨ Other | Measures memory built from synthetic email and chat, asks 186 questions on one corpus and 96 on a second, and reports accuracy by question type with ingest and answer token costs. |
| [Harness Engineering Playground](tools/harness-engineering-playground/README.md) | ✨ Other | Provides an experimental loop for tuning DeepAgents harness profiles against behavioral evaluations, keeping fixes that pass verification and rolling back rejected edits. |

## Collections

### [Build-a-Claw](collections/build-a-claw/README.md)

Guided demos, tutorials, and reusable recipes created through the Build-a-Claw program, while every example keeps its canonical type, path, and contributor provenance.

| Example | Category | Industry | Description |
| --- | --- | --- | --- |
| [Build-a-Claw Tutorial](demos/field/build-a-claw-tutorial/README.md) | NVIDIA Field Demos | 🎓 Academia/Education | Guides DGX Spark users through serving local multimodal models with llama.cpp, connecting an agent harness, and trying coding, vision, browser, messaging, and speech workflows. |

### [Hackathon Recipes](collections/hackathon/README.md)

A curated collection of NemoClaw recipes created for or featured in hackathons, while each recipe remains organized by its contributor provenance.

_No examples are currently in this group._

## Contributing An Example

Read [CONTRIBUTING.md](../CONTRIBUTING.md) and the canonical
[example taxonomy and naming policy](../.agents/skills/nemoclaw-community-contributor-examples/references/example-taxonomy.md).
Runnable examples must remain independently deployable and must document their
prerequisites, credentials, policies, startup behavior, verification, and
teardown behavior. Documentation-only tutorials keep their canonical content
in a root `tutorial.md` beside `README.md`. Add structured catalog metadata as
described in the
[contributor guide](../CONTRIBUTING.md#catalog-metadata).
