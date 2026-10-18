<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Results: Nemotron 3 Ultra, round by round

The agent runs on **Nemotron 3 Ultra**, one container per run with headless FreeCAD 1.1.3
and a shell, 5 minutes and 3 GiB per run. Each round ran both eval tasks twice, all runs in
parallel; then NeMo Compass read the round's traces, NeMo Eval Author checked whether the
eval caught each Insight, and a fresh experimenter
([cad-experimenter](../skills/cad-experimenter/SKILL.md)) built up to two candidates. A
candidate was kept only if it passed more runs than the agent under study (or as many runs
and more checks), with no part and no check worse.

![Checks passed, best IoU per part and tokens per run, by round](../assets/results-rounds.png)

Every Compass Insight, the check that caught it and the round that fixed it:
[insights/](insights/README.md). The final agent: [final-agent/](final-agent/), described
in the [README](../README.md#what-the-loop-built). The chart is drawn by
[rounds_chart.py](rounds_chart.py).

## Chapter 1: the original Ethos

Checks are out of 28 (four runs, seven checks).

| Round | What the evidence showed | Change | Runs | Checks | IoU (part 1 · part 2) |
| --- | --- | --- | --- | --- | --- |
| 0 | Runs spent their 5 minutes learning FreeCAD; none saved a model. | none (base agent) | 0/4 | 0 | none |
| 1 (kept) | No method, no sense of time. | A skill whose script builds and saves a model in one command; a time budget. | 0/4 | 22 | 0.92 · 0.78 |
| | **Compass:** the models are dense stacks of slices, and they pass every check. | **Eval Author adds `compact-model`.** | | | |
| 2 | Slice stacks fail the new check. | Lofts instead of slices: compact, but not one valid solid. | 0/4 | 18 | none · 0.85 |
| 3 (kept) | Joints that fail the shape check; a misleading overlap estimate. | Valid joints and a trustworthy overlap estimate. | **4/4** | **28** | 0.97 · 0.94 |

A confirmation passed **10 of 10**: the agent read one skill and ran one command, and all
ten models were identical.

## The Ethos revision

The models matched the meshes and passed every check, but a designer could only make the
part taller: one parameter stretched every section, and the agent's only modelling step was
running the script. This is the shortcut the
[Eval Author team warns about](https://github.com/NVIDIA-NeMo/eval-author/blob/main/docs/dev-notes/posts/2026-10-08-introducing-eval-author.md):
a task passed while the behaviour it was meant to test was missing. The owner added to
[ETHOS.md](../ETHOS.md): the agent writes its own model (skills carry knowledge, never a
complete routine); dimensions express design intent; the method generalizes. Eval Author
turned the second into **`independent-dimensions`**, two named dimensions that move the
part in different ways. Re-graded, the chapter-1 agent fell from 10/10 to **0/10**, and
Compass reported that "the agent delegates the modelling to a fixed script".

## Chapter 2: the revised Ethos

Checks are out of 32 (four runs, eight checks).

| Round | What the evidence showed | Change | Runs | Checks | IoU (part 1 · part 2) |
| --- | --- | --- | --- | --- | --- |
| 4 | **Compass:** the agent delegates the modelling to a fixed script. | none (new baseline) | 0/4 | 28 | 0.97 · 0.94 |
| 5 | | Knowledge skills; the agent writes its own build script. A measuring subagent in one candidate. | 0/4 | 3 | none |
| | 200-line scripts of raw FreeCAD calls, wrong coordinates, nothing saved. | | | | |
| 6 (kept) | | Feature-level building blocks (`cadkit.py`); build the body first and save. A planner subagent. | 2/4 | 30 | 0.92 · 0.80 |
| 7 (kept) | **Compass:** models below the fidelity bar; runs end with no reply. Single wrong decisions the agent never saw. | A clock (middleware); a save that names what is missing; a structure summary. Planner dropped. | **4/4** | **32** | 0.93 · 0.95 |

This agent passed a 10-run confirmation with every check.

## Chapter 3: looking at the models

Rendered from four directions, the chapter-2 models had creases where the branch meets the
body, seams between sections and a pinched arm, none of which a check measured. Checks
are out of 32, then 36 (nine checks).

| Round | What the evidence showed | Change | Runs | Checks | IoU (part 1 · part 2) |
| --- | --- | --- | --- | --- | --- |
| 8 | Every artefact came from a building block. | Smoother bodies and branches; fusing part 2's arm failed (smoke test only). | | | 0.95 · 0.63 |
| 9 | The arm met the body at a grazing angle. | The arm starts on the rim's flat face. | **4/4** | **32** | 0.95 · 0.93 |
| | Two runs left part 1's branch out and still passed. | **Eval Author adds `no-missing-feature`**; round 9 re-graded to 3/4. | | | |
| 10 (kept) | The agent got the branch path wrong and dropped the branch unnoticed. | The measured path; a tube that repairs or falls back; a save that reports COMPLETE or INCOMPLETE. | **4/4** | **36** | 0.95 · 0.93 |

**Confirmation** of the final agent: **10 of 10**, five per part, all nine checks passing:
part 1 IoU 0.949-0.952 with 18 faces, part 2 0.910-0.924 with 38-39 faces, about 3.5
minutes and 0.12 M tokens per run.

## What the rounds taught

- **The Ethos decides what "good" means.** The loop delivered what the first Ethos asked
  for, and it was not what the owner wanted. One revision and one new check redirected it.
- **Eval Author makes the Ethos bite.** Only a check changes the score: `compact-model`,
  `independent-dimensions` and `no-missing-feature` each turned a passing agent into a
  failing one and pointed the loop at the gap.
- **Compass finds what to fix.** Its Insights named the slice stacks, the delegated
  script, the low fidelity and the silent runs, each with the traces that show it
  ([insights/](insights/README.md)).
- **Give the model decisions, not plumbing.** Raw FreeCAD API code failed; feature-level
  blocks that leave the choice of features to the agent succeeded.
- **Subagents were tried and dropped.** A measuring subagent and a planner subagent handed
  the main agent lossy summaries; one agent with good measurement output did better.
- **Let the agent see what it cannot measure.** A clock, a save that names what is missing
  and a structure summary removed the single wrong decisions that failed runs.
- **Look at the models.** Renders showed artefacts no check measured, and fixing them
  exposed the last gap in the eval.
- **More time is not more skill.** 10-minute runs bought more failed rewrites, not
  convergence.

## Open points

- **Two parts, no held-out or rotated part.** Both scores are training scores.
- **The measurement scripts suggest feature calls.** The agent still decides and writes the
  model, and Compass found no Ethos divergence, but it sits close to the Ethos's line.
- **Thin missing features.** `no-missing-feature` sees a missing piece thicker than about
  3% of the part's size; part 2's fidelity margin is moderate (IoU 0.91-0.92).

Run folders, traces and experimenter notes stay in the git-ignored `experiments/` folder;
Compass's Insights per round are in [insights/](insights/).
