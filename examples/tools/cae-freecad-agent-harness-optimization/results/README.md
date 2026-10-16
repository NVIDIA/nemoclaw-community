<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Results: Nemotron 3 Ultra, round by round

The agent under test runs on **Nemotron 3 Ultra**, one container per run with headless
FreeCAD 1.1.3 and a shell, 5 minutes and 3 GiB per run. Every round ran both eval tasks
twice, all trials in parallel, then NeMo Compass on the round's traces, a NeMo Eval
Author review of the new Insights, and a fresh experimenter
([cad-experimenter](../skills/cad-experimenter/SKILL.md)) that built up to two
candidates. A candidate was kept only if it passed more runs than the agent under study
(or as many runs and more checks), with no part and no check worse.

The story has three chapters. In the first, the loop met everything the Ethos asked for,
with an agent that ran one reconstruction script. Looking at the result, the owner saw
that the Ethos had missed part of the intent, revised it, and let the loop run again. In
the third, renders from several directions showed artefacts that no check measured, and
removing them exposed one more gap in the eval.

The final agent is in [final-agent/](final-agent/).

## Chapter 1: the original Ethos

Checks passed are out of 28 (two parts, two runs, seven checks); rounds 0 and 1 are
re-graded with the seven checks of the end of this chapter.

| Round | What Compass, Eval Author and the traces showed | Change | Runs | Checks | Part 1 IoU | Part 2 IoU | Tokens / run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0. Base agent | Every run spent its 5 minutes analysing the mesh or learning FreeCAD's API by trial and error; none saved a model. | | 0/4 | 0 | | | 1.9 M |
| 1. A skill with a helper script (kept) | | Three prompt lines (time budget; save a verified model early) and a skill whose script builds the model in one command: stacked padded slices, one named dimension, save, reopen, self-check. | 0/4 | 22 | 0.91, 0.92 | 0.78 | 0.04 M |
| | Compass: "Mesh conversion always emits a dense stack of slice sketches and pads." The slice stacks passed every check on part 1. | Eval Author added **`compact-model`** (at most 10× the reference solution's faces); the part-1 slice stack became its negative control. | | | | | |
| 2. Ruled lofts (rejected) | The 1,700-face stacks fail `compact-model`; flat pads stair-step slanted walls. | One ruled loft per segment of constant cross-section. | 0/4 | 18 | invalid solid | 0.85 | 0.08 M |
| 3. Valid joints and a sound IoU estimate (kept) | Nearly tangent walls at a branch joint; shared sections resampled differently; the helper's IoU estimate misranked retries. | Joints as flat steps; a ray-cast IoU estimate; "a failed `check(True)` is an invalid part". | **4/4** | **28** | 0.97 | 0.94 | 0.02 M |

A confirmation passed **10 of 10**. The agent read one skill and ran one command; all ten
models were identical.

## The Ethos revision

The models matched the meshes and passed every check, but a designer could only make the
part taller: one parameter, `Length`, stretched every section, and the agent's only
modelling step was running the script. The owner added to [ETHOS.md](../ETHOS.md):

- the agent does the modelling: it reads the measurements, chooses the features a
  designer would, and writes its own FreeCAD code; skills carry knowledge and small
  building blocks, never a complete reconstruction routine;
- dimensions express design intent (a diameter, a height, a wall thickness), each driving
  its own feature;
- the method must generalize beyond the evaluated parts.

Eval Author turned the second point into one check, **`independent-dimensions`**: two
named dimensions that each, changed by 10%, keep one clean solid and move the part in a
different way. Re-graded, the chapter-1 agent fell from 10/10 to **0/10**, failing only
that check. Run live, Compass named the rest: "the agent delegates the modelling to the
fixed mesh2pd script".

## Chapter 2: the revised Ethos

Checks are out of 32 (eight per run).

| Round | What Compass, Eval Author and the traces showed | Change | Runs | Checks | Part 1 IoU | Part 2 IoU | Tokens / run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4. Chapter-1 agent | Fails `independent-dimensions`; Compass: delegates the modelling to a fixed script. | | 0/4 | 28 | 0.97 | 0.94 | 0.03 M |
| 5. The agent models (rejected) | | Knowledge skills (measure, build features, verify) with small blocks; the agent plans and writes its own `build.py`. | 0/4 | 3 | | | 1.0 M |
| | 21 rewrites of 200-line API scripts in 9 minutes: API errors, mixed coordinate frames, frozen dimensions, nothing saved. 10 minutes per run did not help. | | | | | | |
| 6. Feature-level blocks (kept) | | `cadkit.py`: sections and features in world coordinates, any number an expression over named parameters; build the body first and save, then one feature at a time. | 2/4 | 30 | 0.90, 0.92 | 0.27, 0.80 | 0.24 M |
| 7. A clock and "where is it wrong" (kept) | Single wrong decisions the agent never saw (body lofted to the bounding box top, a cavity through the floor, a branch never built); no sense of time. | Middleware: a clock on every tool result and a stop-and-report at 240 s. Saves list the features in the model and the regions that are missing or extra; measurements end with a STRUCTURE summary. | **4/4** | **32** | 0.93, 0.93 | 0.95, 0.92 | 0.25 M |

This agent (`cad-u9a`) passed a 10-run confirmation with every check (part 1 IoU
0.925-0.932, part 2 0.918-0.958).

## Chapter 3: looking at the models

The owner asked the experimenter to render every model from several directions and look
for anything a designer would object to. The chapter-2 models had creases where the branch
meets the body, seams between loft sections and a faceted cavity floor on part 1, and a
pinched, hexagonal arm with a blunt end on part 2 ([render](../assets/results-views.png)
shows the final agent from the same four directions). Checks are out of 32 (eight per
run), then 36 (nine).

| Round | What the renders, traces and Insights showed | Change | Runs | Checks | Part 1 IoU | Part 2 IoU | Tokens / run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 8. Smooth bodies (rejected) | Every artefact came from a building block, the same in all ten confirmation runs. | A smooth body loft, no sections where a branch merges into the outline, smoothed outlines, branches lofted across their own axis. Part 1's artefacts went; fusing part 2's arm to the smoothed rim failed. | smoke only | | 0.95 | 0.63 | |
| 9. The arm on the rim (4/4, then 3/4) | The arm's underside and the bowl's end wall met at a grazing angle that cannot be fused cleanly. | The arm starts on the rim's flat face, so the two meet in one shared plane; a smooth tip measured from the mesh. | **4/4** | **32** | 0.92, 0.95 | 0.92, 0.93 | 0.16 M |
| | Two part-1 runs saved the model without its branch and passed every check: IoU 0.918. | Eval Author added `no-missing-feature`: the largest connected piece of the part the model leaves out must be at most 1.2% of its volume. Round 9 re-graded: 3/4. | | | | | |
| 10. A branch that is never dropped (kept) | The agent hand-edited the branch path's ends and got one wrong, so the sweep failed and was dropped; nothing told it the model was incomplete. | The measurement prints the full path with its ends in the wall; the tube repairs a bad path or falls back to the measured one; the save compares the measured structure with the model and reports COMPLETE or INCOMPLETE. | **4/4** | **36** | 0.95, 0.95 | 0.92, 0.93 | 0.13 M |

**Confirmation** of the final agent (`cad-u14a`): **10 of 10**, five per part, all nine
checks passing: part 1 IoU 0.949-0.952 with 18 faces, part 2 IoU 0.910-0.924 with 38-39
faces, the branch present in every run, about 3.5 minutes and 0.12 M tokens per run.
Against chapter 2 it ties on runs and checks; it was kept because its renders are clearly
cleaner and its mean IoU is no lower (the keep rule's tie-break).

## What the rounds taught

- **The Ethos decides what "good" means.** The loop delivered exactly what the first
  Ethos asked for, and it was not what the owner wanted. One revision, one new check and
  four more rounds produced an agent that models like an engineer.
- **Eval Author makes the Ethos bite.** Compass and the experimenter read the Ethos, but
  only a check changes the score; adding `compact-model` and `independent-dimensions` each
  turned a passing agent into a failing one, and pointed the loop at the gap.
- **Give the model decisions, not plumbing.** The agent failed while it wrote raw FreeCAD
  API, and succeeded once feature-level blocks took the API away and left the choice of
  features and dimensions to it.
- **Subagents were tried and dropped.** A measuring subagent (round 5) and a planner
  subagent (rounds 6-7) handed the main agent a lossy summary: one reported a floor at 0,
  another turned a flat arm into a round tube. The single agent with good measurement
  output did better.
- **Let the agent see what it cannot measure.** A clock (middleware), a save that names
  the missing region and the feature responsible, and a structure summary removed the
  single wrong decisions that made runs fail.
- **Look at the models.** Renders showed a missing arm and a cut through a floor before
  the numbers did, and four views showed artefacts no check measured. The experimenter
  skill now renders every model from several directions and lists what a designer would
  object to.
- **A cleaner model can expose an eval gap.** Removing artefacts made the agent's branch
  less reliable, and the eval did not notice a model without it. One more proven check,
  from those runs, put the gap back under measurement.
- **More time is not more skill.** Doubling the run to 10 minutes bought more failed
  rewrites, not convergence.

## Open points

- **Two parts, no held-out or rotated part.** The measurement and feature logic was only
  exercised on these two meshes; the old script-based agent failed on a rotated part, and
  the new one is untested there.
- **The measurement scripts suggest feature calls.** The agent still decides and writes the
  model, and Compass found no Ethos divergence, but it sits close to the Ethos's line.
- **Thin missing features.** `no-missing-feature` sees a missing piece thicker than about
  3% of the part's size; a thinner one could still pass. Part 2's fidelity margin is
  moderate (IoU 0.91-0.92).

Run folders, traces, Compass outputs and experimenter notes stay in the git-ignored
`experiments/` folder.
