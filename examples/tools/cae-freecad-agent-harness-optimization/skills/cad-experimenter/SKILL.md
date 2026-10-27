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
- `runs/train/`: its eval job on the **train** split (`evals/train/`), one attempt per
  task (`loop/eval.sh`). Per trial:
  `verifier/results` lists the checks, `verifier/metrics.json` the IoU and complexity counts,
  `verifier/check.log` the details,
  `verifier/reward.txt` the reward, and the first line of `agent/run.log` the trace ID
  (`trace <id>`). The same reward, IoU, failed checks and complexity counts are attached to each trace.
- `insights.yml`: Compass Insights on this round's traces, each citing traces. Read it
  first; if it is missing, stop and say so: a round built without it repeats guesswork.
- `EVAL-AUTHOR.md`: whether the eval already catches each Insight.

## Rules

- **Fix the behavior, not the test.** Do not read any task's `tests/` or `solution/`
  folder, and never mirror the grader. If the agent must measure similarity to the
  mesh, write an independent measurement.
- **Train only.** Read only the train tasks' meshes
  (`evals/train/*/environment/reference.obj`) and train traces. Val and test
  (`evals/val/`, `evals/test/`, `evals/splits.json`) are off limits: they are how your
  change is judged.
- At most **two candidates**, each a different strategy and **one change**, in one area:
  knowledge (prompt, skill text), process (middleware), verification, or tools. One change
  per candidate is what lets the measurement say what worked.
- **Nothing specific to these parts** in the agent: no dimensions, coordinates, feature
  lists, part names or kinds of part (no "if it is a mug"). A change must help a part the
  agent has never seen. Scan your diff before you hand over.
- **Test code headlessly** in the agent's image, with the `freecadcmd` the agent runs.

## Levers

| Lever | Where |
| --- | --- |
| System prompt | `system_prompt` in `agent.yaml` |
| Skills | `skills/<name>/SKILL.md` in the agent folder, with any files beside it. Deep Agents lists each skill's description in the prompt and the agent reads it when it applies. Skills carry knowledge and small building blocks the agent composes in its own scripts, not a complete reconstruction routine (ETHOS). |
| Subagents | `subagents` in `agent.yaml`: a list of `{name, description, system_prompt, tools?}`. The agent delegates with its `task` tool. |
| Middleware | `agent/middleware.py` exporting `MIDDLEWARE`, a list of Deep Agents middleware (e.g. trimming tool output, stopping loops). Use it for what a prompt or skill cannot do, including a rule the traces show the agent ignores in the prompt: a short hint added to the tool result where it applies is often followed where the prompt rule was not. |
| Model | `model` in `agent.yaml`. `with-approval`: propose only. |
| Vision | If the agent's model reads images (ETHOS, Harness), a render it makes of its own model beside the mesh, read back with `read_file`, can show what numbers miss: a missing feature, a wrong orientation, an artefact. [render/](render/) is a working example of headless rendering with `xvfb-run`; the agent's own render tool belongs in its skills. |

## Steps

**1. Diagnose.** Read `LOG.md`, then this round's results per check and per kind of part. For
each Insight and each failing check, open at least two traces:

```bash
nemo intake spans list --filter.trace-id=TRACE_ID --all-pages --output-format=json
```

Find where the behavior happens: the code the agent ran, what came back, what it
claimed. Look at the saved models too: [render/](render/) draws each one beside its mesh
(mesh blue, model orange), headless, from several directions (iso, front, right and top
by default; `VIEWS=` for others). Read every view, passing runs included, and list the
artefacts a designer would object to even when every check passes:

- a missing, misplaced or wrongly shaped feature (a round arm built square, a branch
  that stops short);
- notches, pinches, steps or gaps where features meet;
- ripples, creases, seams or faceting on surfaces that should be smooth;
- bulges or excess material, and walls, floors or ends that are too thin or too thick.

For each artefact, name the view, the feature that causes it and why. Artefacts are
problems to diagnose like failing checks: they often cost IoU margin, and a model that
passes with them is not the model a designer would build.

```bash
docker build -t cad-env "$(ls -d evals/train/*/environment | head -1)"   # once: the agent's image (every task's is the same)
docker run --rm -v "$PWD":/w -w /w -e OUT=render.png \
  -e RENDER="<trial>/artifacts/app/model.FCStd:evals/train/<task>/environment/reference.obj" \
  cad-env xvfb-run -a -s "-screen 0 1920x1200x24" freecadcmd skills/cad-experimenter/render/render.py
```

Write `DIAGNOSIS.md`: per problem, the root cause in two or three sentences,
citing trace IDs. Note shared causes, and what already works and must be kept.

**2. Propose.** Write `PLAN.md`: up to two candidates, each naming the problems it
targets, the lever, and the checks it should move.

**3. Build.** For each candidate, copy the round's `agent/` to `candidates/<short-name>/agent/`, edit
the copy, and set its top-level `name:` to the one the orchestrator gave you. Test any
code a skill relies on in the agent's own image, on train meshes of at least three
different shapes, exactly as the agent will run it:

```bash
docker run --rm -v "$PWD":/w -w /w cad-env timeout 120 freecadcmd my_test.py
```

Run scripts as files, one configuration per process, under a hard time limit, so a hang
costs minutes, not the round. The routine must leave a model that passes FreeCAD's full
shape check (`shape.check(True)`). Hand over only candidates that do, on every mesh you
tested. To
smoke-test a candidate end to end, run one task once with `--ak agent_dir=<candidate>`
(README Step 4); the orchestrator does the real measurement.

A step that hangs or takes over about 60 s is itself a finding: the whole run has
5 minutes. Hand over at least one candidate within about
45 minutes, even if it is the simpler idea; the eval measures it.

**4. Report.** Write `CANDIDATES.md`: per candidate, the Insights it addresses, the diff
against `agent/`, what you tested and its results, and what you expect on each check. The orchestrator measures
them.

## The keep rule

The orchestrator measures each candidate on the **val** split, two attempts per task, on
tasks the experimenters never saw (`loop/eval.sh`, `loop/summary.py`), and keeps it only
when it passes more runs than the agent under study, or as many runs and more checks, with
no check passing fewer times. With equal runs and checks, the
orchestrator may keep a candidate whose renders show clearly fewer artefacts, if its IoU
is no lower; that is a judgement, recorded with the renders. Otherwise the agent under study stays, and the next round diagnoses again with
fresh evidence. A run lost to the infrastructure rather than the agent (the
model gateway down, a container that would not start) is void: it is re-run, not counted. A few val runs are a quick, noisy signal, so the final agent is
measured on **test**, once, with more attempts, before it is reported.
