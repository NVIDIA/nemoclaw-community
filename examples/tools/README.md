<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Developer Tools

Standalone utilities that help developers build, evaluate, inspect, or operate NemoClaw agents without defining an end-user agent workflow.

## Examples

| Example | Industry | Description |
| --- | --- | --- |
| [Agent Memory Benchmark](agent-memory-benchmark/README.md) | ✨ Other | Measures memory built from synthetic email and chat, asks 186 questions on one corpus and 96 on a second, and reports accuracy by question type with ingest and answer token costs. |
| [CAE FreeCAD Agent Harness Optimization](cae-freecad-agent-harness-optimization/README.md) | 🏭 Manufacturing | Runs a CAD agent next to headless FreeCAD, traces every run to NeMo Helix, finds its failures with NeMo Compass, holds it to a proven Harbor eval built with NeMo Eval Author, and keeps only changes that improve it on parts it never saw. |
| [Harness Engineering Playground](harness-engineering-playground/README.md) | ✨ Other | Provides an experimental loop for tuning DeepAgents harness profiles against behavioral evaluations, keeping fixes that pass verification and rolling back rejected edits. |
| [Kubernetes Deployer](kubernetes-deployer/README.md) | ✨ Other | Deploys the official NemoClaw-managed Hermes image behind an OpenShell gateway on Kubernetes or OpenShift, with the Hermes dashboard, OpenAI-compatible API, and terminal access, plus extension points that skill recipes build on. |
| [NemoClaw Enterprise Assistant Harness Optimization](enterprise-assistant-harness-optimization/README.md) | ✨ Other | Improve an Enterprise Personal Assistant NemoClaw agent using a trace-to-evaluation optimization loop |
| [Tracing Agent Harness Behavior with NVIDIA NeMo Relay](hermes-relay-tracing/README.md) | ✨ Other | Runs verified Hermes Agent tool-use tasks and produces NeMo Relay traces for local inspection and evaluation. |
