---
name: deep-research
description: Queue deep, multi-step research and analysis tasks to the DeepAgents worker. Supports execution depth presets, request-specific rubrics, SubAgent delegation, and RubricMiddleware cross-validation.
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Deep Research

Delegate complex, long-running research and multi-document analysis to the DeepAgents background worker service.

## Routing Rule
For deep research, comprehensive analysis, or multi-step investigations, execute `/sandbox/bin/deep-research`.

Do not perform the same long-running task again inline after it has been delegated.

## How To Use

```bash
/sandbox/bin/deep-research [--depth shallow|standard|deep] [--rubric "<custom criteria>"] "<research prompt or goal>"
```

### Examples

**Standard Research (Default):**
```bash
/sandbox/bin/deep-research "Analysis of vector database performance benchmarks in 2026"
```

**Deep Research:**
```bash
/sandbox/bin/deep-research --depth deep "Research the 5 levels of agentic workflow platform security and draft a technical whitepaper"
```

**Custom Rubric Validation:**
```bash
/sandbox/bin/deep-research --depth deep --rubric "Compare the alternatives in a table and cite each major factual claim" "Compare public retrieval architectures"
```

## Options & Arguments
- `--depth <shallow|standard|deep>`: Execution depth preset:
- `shallow`: 25 graph steps, 1 rubric iteration
- `standard` (default): 50 graph steps, 2 rubric iterations
- `deep`: 100 graph steps, 3 rubric iterations
- `--rubric "<text>"`: Optional custom quality rubric for `RubricMiddleware` cross-validation. If omitted, the worker creates a request-specific evidence rubric before invocation.
- Position 1: The research prompt or goal (required string)

## How It Works
1. **Task Enqueued**: Submitted to the DeepAgents worker service via SQLite queue.
2. **Planning**: The worker initializes `write_todos` and applies either the supplied rubric or a request-specific default rubric.
3. **SubAgent Delegation**: Research subtopics are delegated to isolated `SubAgent` workers to prevent context window saturation.
4. **Cross-Validation**: `RubricMiddleware` evaluates the output against the quality rubric, triggering iterative refinement loops if criteria are not met.
5. **Output Delivered**: Formatted report is returned to stdout.

## Execution Constraints
- Up to 5 worker threads run in parallel (`DEEPAGENTS_WORKER_CONCURRENCY=5`).
- Task results are retained for 7 days (`DEEPAGENTS_TASK_TTL_HOURS=168`).
- Only the built-in read-only web-search and document-search tools are available.
