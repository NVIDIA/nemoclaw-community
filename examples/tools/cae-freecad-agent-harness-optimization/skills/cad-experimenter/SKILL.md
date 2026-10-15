---
name: cad-experimenter
description: Run one round of the harness optimization loop on the FreeCAD CAD agent. Read the round's eval results, NeMo Compass Insights, Eval Author review and traces, diagnose, and build up to two candidate agents (system prompt, skills, subagents) for the next eval. Use when asked to improve, fix or experiment on the CAD agent.
---
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# CAD experimenter

This skill was written for this example only. It is a worked pattern for the
"change the agent and measure it" step, not a general-purpose tool.

## How a run is organized

- **Work in the example folder.** Each run has its own folder,
  `experiments/<run>/`, with one subfolder per round. Judge only from this run's
  evidence: do not read `results/`, the README's results, or other folders under
  `experiments/`.
- **An orchestrator** runs the eval on each agent, runs Compass and an Eval Author
  review of the new Insights, and keeps or rejects candidates by the rule below.
- **A fresh experimenter each round**, with no memory of other rounds. That is you:
  diagnose this round's failures and build at most two candidates. Earlier rounds of
  this run are summarized in the run's `LOG.md`; read it so you do not repeat a
  rejected idea.

## Inputs (in `experiments/<run>/round-<N>/`)

- `ETHOS.md` (example root): read it first. It holds the requirements, how and where
  the agent runs, what you may change (**Change Scope**) and how changes should be made
  (**Trade-offs**).
- `agent/`: the agent under study (prompt, model, skills).
- `runs/eval/`: its eval job, both tasks, two attempts per part. Each trial's
  `verifier/results` lists the five checks; `result.json` holds the IoU and the
  trace ID under `agent_result.metadata`.
- `insights.yml`: Compass Insights on this round's traces, each citing traces.
- `EVAL-AUTHOR.md`: whether the eval already catches each Insight.

## Rules

- **Fix the behavior, not the test.** Do not read `scorer/`, `evals/*/tests/` or
  `evals/*/solution/`, and never mirror the grader. If the agent must measure similarity
  to the mesh, write an independent measurement.
- At most **two candidates**, each a different strategy.
- **Test code headlessly** with `freecadcmd`, the FreeCAD the agent runs.

## Levers

| Lever | Where in `agent.yaml` |
| --- | --- |
| System prompt | `instructions.system.content` |
| Skills | `skills/<name>/` in the agent folder. |
| Subagents | `subagents`: a list of `{name, description, system_prompt, tools?}`. The agent delegates with its `task` tool. |
| Model | `models.default.model`. `with-approval`: propose only. |

Middleware is not configurable from `agent.yaml`.

## Steps

**1. Diagnose.** Read `LOG.md`, then this round's results per check and per part. For
each Insight and each failing check, open at least two traces:

```bash
nemo intake spans list --filter.trace-id=TRACE_ID --all-pages --output-format=json
```

Find where the behavior happens: the code the agent ran, what came back, what it
claimed. Write `DIAGNOSIS.md`: per problem, the root cause in two or three sentences,
citing trace IDs. Note shared causes, and what already works and must be kept.

**2. Propose.** Write `PLAN.md`: up to two candidates, each naming the problems it
targets, the lever, and the checks it should move on both parts.

**3. Build.** For each candidate, copy the round's `agent/` to `candidates/<short-name>/agent/`, edit
the copy, and set its top-level `name:` to the one the orchestrator gave you. Test any
code a skill relies on, headlessly, on both reference meshes:

```bash
freecadcmd -c "exec(open('my_test.py').read())"
```

Test the code exactly as the agent will run it. The routine must leave a model that
passes FreeCAD's full shape check (`shape.check(True)`). Give every test a hard time
limit and one configuration per process, so a hang costs minutes, not the round:

```bash
perl -e 'alarm 120; exec @ARGV' freecadcmd -c "exec(open('my_test.py').read())"
```

A step that hangs or takes over about 60 s is itself a finding: the whole run has
5 minutes. Hand over at least one candidate within about
45 minutes, even if it is the simpler idea; the eval measures it.

**4. Report.** Write `CANDIDATES.md`: per candidate, the diff against `agent/`, what you
tested and its results, and what you expect on each check. The orchestrator measures
them.

## The keep rule

The orchestrator measures each candidate on both tasks, two attempts per part, and keeps
it only when it passes more runs than the agent under study, with no part and no check
worse. Otherwise the agent under study stays, and the next round diagnoses again with
fresh evidence. A run lost to the infrastructure rather than the agent (the
model gateway down, a container that would not start) is void: it is re-run, not counted. Two attempts per part is a quick, noisy signal, so the final agent is
measured again with more attempts before it is reported.
