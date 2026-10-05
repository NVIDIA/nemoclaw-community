<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Enterprise Assistant Harness Optimization

| Catalog field | Value |
| --- | --- |
| Description | Demonstrates a trace-to-evaluation optimization loop for a Hermes enterprise assistant using synthetic traces, mock MCP tools, Trace Analyst, Eval Author and Harbor. |
| Industry | ✨ Other |
| Requirements | Linux · native Docker with isolated verification support · OpenShell 0.1.2 · NVIDIA Build API key · Codex CLI and Eval Author access for task authoring |
| NemoClaw | N/A |
| Harness | Hermes 0.21.3 |
| OpenShell | 0.1.2 |

This repository is a hands-on tutorial for improving an enterprise agent harness
from observed behavior: analyze realistic production traces with NeMo Trace
Analyst, author Harbor evaluations with a coding agent, analyze scored baseline
runs, implement a candidate harness, and compare it with the baseline.

Hermes performs the work; OpenShell controls its runtime and network access;
MCP supplies the fictional company; Relay records trajectories; Trace Analyst
discovers patterns; Eval Author helps Codex construct tests; Harbor executes
and grades those tests.

The fictional agent helps a company prepare a product launch by researching
across mail, calendar, chat, files, enterprise knowledge, directory, project,
analytics, support, and connector tools. The deterministic world includes stale
and current records, ambiguous people, pagination, a large structured evidence
register, a disconnected connector, and a transient search failure.

The tutorial is grounded in NVIDIA's internal work optimizing a production
personal assistant for employee research and actions across those kinds of
systems. The public [Nemotron 3 Ultra harness-profile case study](https://developer.nvidia.com/blog/create-a-langchain-deep-agents-harness-profile-for-nvidia-nemotron-3-ultra-to-improve-performance/)
describes related optimization methods.

## Fictional MCP tools

The full catalog has 15 tools backed by a [deterministic fictional world](fixtures/README.md).
These are illustrative enterprise-service equivalents, not live integrations.

| Tools | What the agent can do | Enterprise equivalent |
| --- | --- | --- |
| `connectors.get_status` | Check connection and authentication state | SaaS connector health / OAuth status |
| `people.search` | Find employees, including ambiguous names | Microsoft Entra ID / Google Workspace directory |
| `mail.search`, `mail.read_thread` | Find mail metadata, then read messages | Outlook / Gmail |
| `chat.search`, `chat.read_thread` | Find chat threads, then read conversations | Slack / Microsoft Teams |
| `calendar.list_events` | Find meetings and review times | Outlook Calendar / Google Calendar |
| `knowledge.search` | Search enterprise knowledge | Confluence / SharePoint / enterprise search |
| `files.search`, `files.read_json` | Find files and inspect bounded JSON sections | SharePoint / Google Drive plus a structured-file reader |
| `projects.search_tasks` | Find project work and blockers | Jira / Asana |
| `analytics.query_metrics` | Look up product metrics | Enterprise BI / product analytics |
| `support.search_tickets` | Find incident and support records | ServiceNow / Zendesk |
| `actions.prepare_message`, `actions.send_message` | Prepare a draft, then separately execute a send | Email / chat draft-and-send APIs |

Hermes and Relay run in OpenShell. The authenticated Streamable HTTP MCP server
runs outside the sandbox; Hermes reaches it through the checked-in
[OpenShell policy](openshell/policy.yaml).

## What's included: the ten-step flywheel

The tutorial uses [NeMo Trace Analyst](https://github.com/NVIDIA-NeMo/labs-trace-intel)
and Codex with [NeMo Eval Author](https://github.com/NVIDIA-NeMo/labs-eval-author).
Each step has saved artifacts to inspect or reuse:

| Step | What you do | Checked-in artifacts |
| --- | --- | --- |
| 1. [Freeze the baseline](docs/walkthrough.md#1-freeze-the-baseline) | Set up Hermes, OpenShell and the fictional world | [Baseline profile](profiles/baseline-soul.md), [runtime configuration](harbor_agents/hermes_flywheel.py), [sandbox setup](openshell/), [world records](fixtures/world-v2.json), [workload](experiments/production-trace-matrix-v3.json) |
| 2. [Collect source traces](docs/walkthrough.md#2-collect-source-traces) | Run distinct production-like requests, or use the supplied corpus | [42 traces, corpus index and analysis input](traces/world-v3/production/) |
| 3. [Discover issues](docs/walkthrough.md#3-discover-issues) | Run Trace Analyst on the production corpus | [Production findings](results/production-insights.yml), [analyst configuration](configs/trace-analyst.yaml) |
| 4. [Author and prove eval tasks](docs/walkthrough.md#4-author-and-prove-eval-tasks) | Ask Codex + Eval Author to turn supported findings into executable tests | [Authoring prompt](prompts/eval-author-from-traces.md), [four Harbor tasks](evals/harbor-tasks-v3/), [technical proof receipts](evals/task-proofs/) |
| 5. [Freeze the split](docs/walkthrough.md#5-freeze-the-split) | Review task meaning and reserve development / held-out cases | [Two-development / two-held-out manifest](evals/flywheel-eval-set-v3.json), [human review sheet](evals/REVIEW.md) |
| 6. [Measure baseline development](docs/walkthrough.md#6-measure-baseline-development) | Run development tasks three times each and retain scores with traces | [Six scored baseline traces](traces/world-v3/baseline-development/) |
| 7. [Analyze scored baseline failures](docs/walkthrough.md#7-analyze-scored-baseline-failures) | Run Trace Analyst again on baseline development trajectories | [Scored-development findings](results/baseline-development-insights.yml) |
| 8. [Build a candidate from both reports](docs/walkthrough.md#8-build-a-candidate-from-both-reports) | Use both reports to propose a general harness change, then freeze it | [Proposal](results/candidate-proposal.md), [candidate profile](profiles/candidate-soul.md), [experiment freeze](results/experiment-freeze.json) |
| 9. [Run development and held-out A/B](docs/walkthrough.md#9-run-development-and-held-out-ab) | Run the same development and held-out tasks with equal budgets | [Four baseline/candidate run summaries](results/) |
| 10. [Decide](docs/walkthrough.md#10-decide-whether-the-optimization-worked) | Check improvement on both splits, regressions and uncertainty | [A/B comparison](results/measured-ab-v3.json), [artifact hashes](results/artifact-chain.json), [results and limits](docs/results.md) |

The measured candidate clarifies that preparing a message is not authorization
to send it, and a tool-issued token is not user consent. Development scores
improve from 3/6 to 6/6 and held-out scores from 4/6 to 6/6. Other candidate
patterns—tool downsampling, bounded JSON reads and evidence-state management—are
described in [harness patterns](docs/harness-patterns.md), not claimed as measured
improvements here.

The four distinct evaluation tasks demonstrate the process: two are used for
development, and two are reserved until the candidate is frozen. Each task runs
three times per configuration, giving 24 evaluation runs. A production suite
needs broader task coverage. Your model-backed run may produce different scores;
the walkthrough explains how to assess task-level improvement and regressions.

## Repository map

| Folder | Purpose |
| --- | --- |
| [configs/](configs/) | Trace Analyst settings; [ETHOS.md](ETHOS.md) supplies the intended behavior used by analysis and task authoring. |
| [docs/](docs/) | The walkthrough, measured results, harness patterns and future Gym extension. |
| [evals/](evals/) | Eval-suite manifest, runnable Harbor tasks, proof receipts and human review sheet. |
| [experiments/](experiments/) | The 42-request workload used to collect production-like traces—not an eval suite. |
| [fixtures/](fixtures/) | Deterministic fictional company records and initial tool state. |
| [harbor_agents/](harbor_agents/) | Adapters that run Hermes in OpenShell and deliver answers/tool logs to Harbor. |
| [openshell/](openshell/) | Sandbox image recipe, network policy and model-provider profile. |
| [profiles/](profiles/) | Editable baseline and candidate Hermes system instructions. |
| [prompts/](prompts/) | The authoring request to give Codex when using Eval Author. |
| [results/](results/) | Saved Insights reports, candidate rationale, run summaries, comparisons and provenance hashes. |
| [scripts/](scripts/) | Commands for trace collection/conversion, eval execution and validation. |
| [src/](src/) | The mock MCP implementation, shared world/tool behavior and trace utilities. |
| [tests/](tests/) | Automated tests for the environment, adapters, runners and artifact checks. |
| [traces/](traces/) | Checked-in agent trajectories, corpus indexes and Trace Analyst inputs. |

Your own run outputs go under `.runs/`; private Eval Author work goes under
`.eval-author/`. Both are ignored by Git and are separate from the saved examples.

## Start here

Follow the [walkthrough](docs/walkthrough.md) for prerequisites, copyable host
setup commands, the 10-step flywheel, optional trace regeneration, and the
secondary Trace-Analyst-only path. The recommended full-run host is fresh Ubuntu
24.04 with native Docker, 8 vCPUs, 32 GB RAM, 100 GB free disk, and a working
OpenShell gateway; a Brev CPU instance is a convenient option, and a compatible
local Linux host also works. **Docker Desktop is unsupported for the full
tutorial**, including Harbor task proofs and evaluation runs: the tested Docker
Desktop kernel lacks the `CONFIG_NFT_FIB_INET` capability needed for isolated
verification. Reading and trace analysis can run locally without Docker.

Supporting detail: [fictional world](fixtures/README.md),
[trace artifacts](traces/README.md),
[harness patterns](docs/harness-patterns.md), and
[extending the environment for RL](docs/gym-extension.md).

The public example uses synthetic records throughout. Replace the workload,
fictional world, trace adapter, and task environment to apply the same method to a real
agent.
