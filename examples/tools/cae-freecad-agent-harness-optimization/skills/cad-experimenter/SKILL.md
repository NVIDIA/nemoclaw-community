---
name: cad-experimenter
description: Run one round of the harness optimization loop on the FreeCAD CAD agent deployed on NeMo Helix. Read the NeMo Compass Insights and their traces, diagnose, propose up to two candidate changes (system prompt, skills, subagents, tool gating), deploy each beside the agent under study, measure it on the Eval Author eval, and report which Insights each candidate fixed. Use when asked to improve, fix or experiment on the CAD agent.
---
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# CAD experimenter

This skill was written for this example only. It is a worked pattern for the
"change the agent and measure it" step, not a general-purpose tool.

One round: **diagnose → propose → build → evaluate → report**. Work from the example
root. You change copies of the agent, never the agent under study, and you never
decide what ships: a human promotes a candidate.

## Inputs

- `insights.yml`: the Compass Insights, each with its supporting trace IDs.
- Eval Author's review of those Insights, if one was made: whether the eval already
  catches each one, or needs a new check.
- `evals/manifest.json`: which eval check tests which Insight.
- `ETHOS.md`: the requirements and, under **Change Scope**, what you may change.
- The agent under study (`agent/` or a previous round's candidate) and its own eval
  job, which is the baseline the candidates are compared with.

## Rules

- Change only what Change Scope marks `yes`. Never edit `evals/`, `scorer/`,
  `meshes/`, `task/`, `ETHOS.md` or `harness/`.
- Fix the behavior, not the test: no mesh values, check names, reference model
  details or verifier logic in the agent's instructions. Do not read `scorer/` or
  `evals/*/tests/`. If the agent needs to measure similarity to the mesh, write an
  independent measurement rather than mirroring the grader.
- At most **two candidates per round**, each a different strategy, not two wordings
  of one idea. Prefer the smallest change that addresses the root cause; for a small
  model, removing work (a tested routine in a skill) often beats adding rules.
- **One eval job at a time.** FreeCAD is one shared session; the Harbor agent refuses
  a second job. Never invoke a candidate directly while an eval runs.
- Tear every candidate down when its evaluation ends.

## Levers

| Lever | Where in `agent.yaml` |
| --- | --- |
| System prompt | `instructions.system.content` |
| Skills | `skills/<name>/SKILL.md` in the agent folder, with `environment.workspace: .`, and a prompt line per skill that says when to use it and to read `/skills/<name>/SKILL.md` with `read_file`. Deep Agents' own `skills.paths` does not load on this Helix version. |
| Subagents | `harnesses.deepagents.settings.deepagents.subagents`: a list of `{name, description, system_prompt, tools?}` |
| Tool gating | `tools.enabled` / `tools.blocked` |
| Model | `models.default.model`. Change Scope says `with-approval`: ask first. |

Middleware is not configurable from the agent spec.

## Steps

Create a round folder, `experiments/<YYYY-MM-DD>-<short-name>/` (git-ignored).

**1. Diagnose.** For each Insight, read its description and open at least two of its
traces:

```bash
nemo intake spans list --filter.trace-id=TRACE_ID --mode=detailed --sort=started_at --all-pages --output-format=json
```

Find the steps where the behavior happens: the code the agent ran, what it checked,
what it claimed. Write `DIAGNOSIS.md`: per Insight, the root cause in two or three
sentences, citing trace IDs and steps. Note when Insights share a cause.

**2. Propose.** Write `PLAN.md`: up to two candidates, each naming the Insights it
targets, the lever, and the checks it should move.

**3. Build.** Copy the agent under study (with its `skills/`), edit the copy, and
deploy it under its own name:

```bash
C=experiments/<round>/<candidate>; NAME=cad-agent-<candidate>
mkdir -p $C/agent && cp -R <agent under study>/. $C/agent/
# edit $C/agent/agent.yaml (and skills/); set its top-level `name:` to $NAME
nemo agents create --name $NAME --agent-config "$PWD/$C/agent/agent.yaml"
nemo agents deploy --agent $NAME --name $NAME-deployment --mode subprocess
```

Test a new skill's code in FreeCAD yourself before the agent relies on it.

**4. Evaluate.** Three attempts, one at a time; add attempts when the result is close
to the baseline's:

```bash
CAD_AGENT=$NAME CAD_DEPLOYMENT=$NAME-deployment PYTHONPATH=harness \
  harbor run -p evals/part-1-reconstruction \
  -a helix_cad_agent:HelixCadAgent --n-attempts 3 -n 1 --jobs-dir $C/runs --job-name eval
cat $C/runs/eval/*/verifier/results | sort | uniq -c   # passes per check
nemo agents undeploy --agent $NAME --yes && nemo agents delete $NAME --yes
```

Each trial's `result.json` holds the host IoU and trace ID under
`agent_result.metadata`. Write `$C/results.md`: per check, baseline and candidate
pass counts; passing runs; IoU per run; and tokens per run (`total_tokens` of each
trace in Intake). Read the failed runs' traces: a failure the change never reached is
variance, not evidence against it.

**5. Report.** Write `SUMMARY.md`: per Insight, fixed, improved, unchanged or worse,
and by which candidate; the recommended candidate (or none) with its diff and token
cost change; and what to try next.

Recommend promotion only when the candidate passes at least as many runs as the
baseline, makes no check worse, and improves the check for at least one Insight. The
next round starts with fresh source runs of the promoted agent, then Compass and Eval
Author on those traces. One task and a few attempts cannot show generalization; say
so.

## Environment

Set up Helix, Harbor, Colima and FreeCAD as in the example README's Prerequisites, and
export the Step 2 settings (`DOCKER_HOST`, `CAD_AGENT_TIMEOUT=600`,
`CAD_FREECAD_RESTART`) so candidates are measured as the baseline was.
