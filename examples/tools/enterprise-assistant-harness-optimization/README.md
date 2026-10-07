<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# NemoClaw Enterprise Assistant Harness Optimization

| Catalog field | Value |
| --- | --- |
| Description | Improve an Enterprise Personal Assistant NemoClaw agent using a trace-to-evaluation optimization loop |
| Industry | Enterprise |
| Requirements | Ubuntu with Docker, NVIDIA Build API key, Codex or an equivalent coding agent|
| NemoClaw | 0.0.131 |
| Harness | Hermes 0.21.3 |
| OpenShell | 0.1.2 |

This repository is a NemoClaw reference tutorial for optimizing an Enterprise Personal Assistant agent. The agent is built with Hermes running in OpenShell with Nemotron 3 Ultra as the LLM. The agent connects to an MCP service that contains fictional tools mimicking services like Outlook, Teams, Slack, Jira, and Confluence.

The tutorial walks through a multi-step optimization process:
- Create traces by asking the agent a series of questions that use the fictional MCP tools
- Use [NeMo Compass](https://github.com/NVIDIA-NeMo/labs-nemo-compass) to analyze the traces and identify common failures
- Use a coding agent like Codex with the [NeMo Eval Author skills](https://github.com/NVIDIA-NeMo/labs-eval-author) to create Harbor evaluation cases that (a) reflect the most common patterns from the traces, and (b) reproduce any identified failures
- Propose a change to the agent that fixes the failure
- Run the Harbor eval cases with the proposed fix, confirming improvement without introducing regressions

After completing this tutorial, you will have a core understanding of the NeMo libraries to re-implement this optimization loop with your own agent.

The repository includes checked-in artifacts for each step of this process, allowing you to reproduce the results or skip steps that you do not want to re-run.

## Fictional Agent

The optimization tutorial starts with a fictional agent. The agent is built following the NemoClaw reference pattern:
- Hermes Agent Harness
- OpenShell Runtime
- Nemotron 3 Ultra LLM

The agent is given a set of fictional MCP tools and is asked to perform tasks for a company product launch: researching
across mail, calendar, chat, files, enterprise knowledge, directory, project,
analytics, support, and connector tools.

The fictional MCP tool catalog has 15 tools backed by [synthetic data](fixtures/README.md). The tools were built to reflect real problems encountered with an actual NVIDIA enterprise assistant including: ambiguous tool definitions, tool overlap, large paginated JSON results, multi-step workflows for resolving UIDs, and human-in-the-loop requirements for draft or write actions.


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

The Hermes agent accesses these fictional MCP tools over a remote HTTP interface. The [OpenShell policy](openshell/policy.yaml) specifies this access and prohibits other network egress.


## Included Artifacts

| Step | What you do | Checked-in artifacts |
| --- | --- | --- |
| Start the agent | Set up Hermes, OpenShell and the fictional world | [Baseline profile](profiles/baseline-soul.md), [runtime configuration](harbor_agents/hermes_flywheel.py), [sandbox setup](openshell/), [world records](fixtures/world-v2.json), [workload](experiments/production-trace-matrix-v3.json) |
| Collect source traces | Run distinct production-like requests | [42 traces, corpus index and analysis input](traces/world-v3/production/) |
| Discover issues | Run NeMo Compass on traces | [Production findings](results/production-insights.yml), [analyst configuration](configs/trace-analyst.yaml) |
| Author Eval Tasks | Ask Codex + Eval Author to create Harbor eval tasks that represent common tasks and reproducible issues found in the traces | [Authoring prompt](prompts/eval-author-from-traces.md), [four Harbor tasks](evals/harbor-tasks-v3/), [technical proof receipts](evals/task-proofs/) |
| Define hold-out cases | Separate some of the eval tasks into a hold-out set. This set is not used when proposing agent improvements, but is used as a last step to check if any proposed changes introduce regressions. | [Two-development / two-held-out manifest](evals/flywheel-eval-set-v3.json), [human review sheet](evals/REVIEW.md) |
| Execute the Eval Tasks| Run eval tasks three times each and retain scores with traces | [Six scored baseline traces](traces/world-v3/baseline-development/) |
| Examine the traces from the Eval Tasks | Run NeMo Compass again on baseline development trajectories | [Scored-development findings](results/baseline-development-insights.yml) |
| Propose a change to improve the agent | Give Codex the results from NeMo Compass and ask it to propose an improvement to the agent | [Proposal](results/candidate-proposal.md), [candidate profile](profiles/candidate-soul.md), [experiment freeze](results/experiment-freeze.json) |
| Test the proposed improvements | Run the eval tasks and check for improvements and regressions | [Four baseline/candidate run summaries](results/) |
| Analyze results | Check improvement on both splits, regressions and uncertainty | [A/B comparison](results/measured-ab-v3.json), [artifact hashes](results/artifact-chain.json), [results and limits](docs/results.md) |

For the tutorial run-through that is checked into the repository:

- NeMo Compass identified an issue in the 42 checked-in traces where the agent would draft/write messages without user confirmation.
- Eval tasks were created to reproduce this issue.
- Codex suggested a change to the Hermes SOUL.md to enforce user confirmation for drafts/writes.
- The proposed change worked, and all eval tasks passed.

Your run of the tutorial may produce different results. This optimization loop was used on a production agent running at NVIDIA in a similar scenario. The improvements implemented for this production agent are described in [harness patterns](docs/harness-patterns.md).

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


## Start here

Follow the [walkthrough](docs/walkthrough.md) for the full tutorial guide.