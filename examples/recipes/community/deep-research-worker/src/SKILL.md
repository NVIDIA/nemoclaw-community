---
name: deep-research
description: Queue deep, multi-step research and analysis tasks to the DeepAgents worker. Supports execution depth presets (shallow/standard/deep), domain-adaptive self-rubrics, SubAgent delegation, and RubricMiddleware cross-validation.
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Deep Research

Delegate complex, long-running research, competitive intelligence, multi-document analysis, legal/immigration studies, investment rebalancing, or security whitepapers to the **DeepAgents background worker service**.

## CRITICAL: Routing Rule
**For deep research, comprehensive analysis, multi-step investigations, or tasks that request "research", "analyze deeply", or "comprehensive report", ALWAYS execute `/sandbox/bin/deep-research`.**

Do NOT attempt to perform multi-step research inline using standard web fetch loops. Always delegate to DeepAgents.

## How To Use

```bash
/sandbox/bin/deep-research [--depth shallow|standard|deep] [--rubric "<custom criteria>"] "<research prompt or goal>"
```

### Examples

**Standard Research (Default)**:
```bash
/sandbox/bin/deep-research "Analysis of vector database performance benchmarks in 2026"
```

**Deep Exhaustive Research**:
```bash
/sandbox/bin/deep-research --depth deep "Research the 5 levels of agentic workflow platform security and draft a technical whitepaper"
```

**Custom Rubric Validation**:
```bash
/sandbox/bin/deep-research --depth deep --rubric "Must include asset allocation tables, tax drag calculations, and SEC compliance notes" "Analyze portfolio rebalancing strategy for high-net-worth tech employee"
```

## Options & Arguments
- `--depth <shallow|standard|deep>`: Execution depth preset:
- `shallow`: 25 graph steps, 1 rubric iteration
- `standard` (default): 50 graph steps, 2 rubric iterations
- `deep`: 100 graph steps, 3 rubric iterations
- `--rubric "<text>"`: Optional custom quality rubric for `RubricMiddleware` cross-validation. If omitted, the agent automatically synthesizes a domain-adaptive quality rubric.
- Position 1: The research prompt or goal (required string)

## How It Works
1. **Task Enqueued**: Submitted to the DeepAgents worker service via SQLite queue.
2. **Domain-Adaptive Self-Planning**: Worker initializes `write_todos` and synthesizes domain-appropriate quality criteria (e.g. Mermaid diagrams for tech, asset allocation tables for finance, statutory citations for legal).
3. **SubAgent Delegation**: Research subtopics are delegated to isolated `SubAgent` workers to prevent context window saturation.
4. **Cross-Validation**: `RubricMiddleware` evaluates the output against the quality rubric, triggering iterative refinement loops if criteria are not met.
5. **Output Delivered**: Formatted report is returned to stdout.

## Execution Constraints
- Up to 5 worker threads run in parallel (`DEEPAGENTS_WORKER_CONCURRENCY=5`).
- Task results are retained for 7 days (`DEEPAGENTS_TASK_TTL_HOURS=168`).
