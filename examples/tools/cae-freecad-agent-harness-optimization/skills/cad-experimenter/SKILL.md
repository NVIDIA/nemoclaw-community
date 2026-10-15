---
name: cad-experimenter
description: Run one round of the harness optimization loop on the FreeCAD CAD agent deployed on NeMo Helix. Read the round's eval results, NeMo Compass Insights, Eval Author review and traces, diagnose, and build up to two candidate agents (system prompt, skills, subagents, tool gating) for the next eval. Use when asked to improve, fix or experiment on the CAD agent.
---
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# CAD experimenter

This skill was written for this example only. It is a worked pattern for the
"change the agent and measure it" step, not a general-purpose tool.

## How a run is organized

- **A clean workspace.** The loop runs in a folder that holds only the base agent,
  `ETHOS.md`, `task/`, `meshes/`, `evals/`, `harness/`, `scorer/` and this skill.
  Earlier runs, earlier agents and their results are not part of it: work only from
  what the workspace and this round's evidence show.
- **An orchestrator** deploys each agent, runs the eval, runs Compass and an Eval
  Author review of the new Insights, and keeps or rejects candidates by the rule below.
- **A fresh experimenter each round**, with no memory of other rounds. That is you:
  diagnose this round's failures and build at most two candidates. Earlier rounds of
  this run are summarized in `LOG.md`; read it so you do not repeat a rejected idea.

## Inputs (in `rounds/<N>/`)

- `agent/`: the agent under study (prompt, skills, tool gating).
- `runs/eval/`: its eval job, both tasks, two attempts per part. Each trial's
  `verifier/results` lists the five checks; `result.json` holds the host IoU and the
  trace ID under `agent_result.metadata`.
- `insights.yml`: Compass Insights on this round's traces, each citing traces.
- `EVAL-AUTHOR.md`: whether the eval already catches each Insight.
- `ETHOS.md` (workspace root): the requirements and, under **Change Scope**, what you
  may change.

## Rules

- **Geometry-agnostic.** The agent must handle any part given as a mesh. The eval holds
  two different parts so that a change tuned to one shape fails the other. Never put
  part-specific values, shapes or names in the agent.
- **Fix the behavior, not the test.** Do not read `scorer/`, `evals/*/tests/` or
  `evals/*/solution/`, and never mirror the grader. If the agent must measure similarity to the mesh, write an
  independent measurement.
- Change only what Change Scope marks `yes`. Model and MCP server changes need the
  owner's approval: propose them, do not make them.
- At most **two candidates**, each a different strategy. Prefer the smallest change that
  addresses the root cause. For a small model, removing work often beats adding rules.
- **Guide through results, not rules.** A small model acts on what it has just read.
  When the agent must do something next (retry, stop, run the next step), have the
  output of the code it runs say so, rather than adding another rule to the prompt.
- **Do not use the FreeCAD GUI while an eval runs.** Test code headlessly with
  `freecadcmd`; use the GUI only when the orchestrator says it is free.

## Platform facts

Facts about this environment, learned the hard way. They are not solutions.

| Fact | Consequence |
| --- | --- |
| Deep Agents' `read_file` returns 100 lines unless you pass a larger `limit`. | An agent reading a long skill once sees only its start. Tell it the limit or keep files short. |
| The agent's file tools run in a sandbox. FreeCAD cannot see `/skills` or files the agent writes; the mesh path is valid only inside FreeCAD. | Code in a skill reaches FreeCAD only as the `code` argument of `execute_code`, copied by the model. |
| `execute_code` runs on FreeCAD's GUI thread. Over 90 s the bridge aborts the call but the work keeps running, and every later call fails until it ends. | Keep each call bounded. |
| `execute_code` rejects a `timeout` argument. Names defined in one call stay defined for the next. | Never pass `timeout`. Long code can be split across calls. |
| `execute_code_headless` fails (`freecadcmd not found`), `get_async_status` is not implemented, and `execute_code_async` gives no job handle. | These tools only feed retry loops. |
| Nemotron 3.5 Lightning reads no images; the task is text-only. | Screenshots (`get_view`) only cost tokens. |
| Deep Agents' `skills.paths` does not load on this Helix version. | Ship skills as `skills/<name>/` in the agent folder with `environment.workspace: .`, and point to them from the prompt. |
| Stopping `nemo agents invoke` does not stop the run inside the deployment. | Orchestrator: kill the deployment's adapter process before reusing FreeCAD. |

## Levers

| Lever | Where in `agent.yaml` |
| --- | --- |
| System prompt | `instructions.system.content` |
| Skills | `skills/<name>/` in the agent folder (see Platform facts), plus a prompt line per skill saying when to read it. |
| Subagents | `harnesses.deepagents.settings.deepagents.subagents`: a list of `{name, description, system_prompt, tools?}`. The agent delegates with its `task` tool. |
| Tool gating | `tools.enabled` / `tools.blocked` |
| Model | `models.default.model`. `with-approval`: propose only. |

Middleware is not configurable from the agent spec.

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

**3. Build.** For each candidate, copy `agent/` to `candidates/<short-name>/agent/`, edit
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

A step that hangs or takes over about 60 s is itself a finding: the agent's
`execute_code` calls are cut off at 90 s. Hand over at least one candidate within about
45 minutes, even if it is the simpler idea; the eval measures it.

**4. Report.** Write `CANDIDATES.md`: per candidate, the diff against `agent/`, what you
tested and its results, and what you expect on each check. The orchestrator deploys and
measures them.

## The keep rule

The orchestrator measures each candidate on both tasks, two attempts per part, and keeps
it only when it passes more runs than the agent under study, with no part and no check
worse. Otherwise the agent under study stays, and the next round diagnoses again with
fresh evidence. A run lost to the infrastructure rather than the agent (FreeCAD
killed by something else, a leftover run from another agent, a container that would
not start) is void: it is re-run, not counted. Two attempts per part is a quick, noisy signal, so the final agent is
measured again with more attempts before it is reported.
