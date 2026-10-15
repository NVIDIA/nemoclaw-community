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

The final agent is in [final-agent/](final-agent/): a four-line prompt and one skill,
`mesh-to-partdesign`, whose helper script the agent runs with `freecadcmd`.

## Round by round

Checks passed are out of 28 (two parts, two runs, seven checks); rounds 0 and 1 are
re-graded with the seven checks of the final eval.

| Round | What Compass, Eval Author and the traces showed | Change | Runs | Checks | Part 1 IoU | Part 2 IoU | Tokens / run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0. Base agent | Every run spent its 5 minutes analysing the mesh or learning FreeCAD's API by trial and error; none saved a model. | | 0/4 | 0 | | | 1.9 M |
| 1. A skill with a helper script (kept) | | Three prompt lines (time budget; save a verified model early) and a skill whose script builds the model in one command: stacked padded slices, one named dimension, save, reopen, self-check. | 0/4 | 22 | 0.91, 0.92 | 0.78 | 0.04 M |
| | Compass: "Mesh conversion always emits a dense stack of slice sketches and pads." The slice stacks passed every check on part 1. | Eval Author added **`compact-model`** (at most 10× the reference solution's faces); the part-1 slice stack became its negative control. | | | | | |
| 2. Ruled lofts (rejected) | The 1,700-face stacks fail `compact-model`; flat pads stair-step slanted walls. Two experimenters spent about 2.5 hours making lofts valid. | One ruled loft per segment of constant cross-section, outer and hole loops in one sketch. | 0/4 | 18 | invalid solid | 0.85 | 0.08 M |
| 3. Valid joints and a sound IoU estimate (kept) | Where a branch leaves part 1's main body, the fuse joined two nearly tangent walls; shared sections were resampled differently; end sections sat half a level off; the helper's IoU estimate misranked retries, and the agent shipped a model that failed the shape check. | Joints as flat steps with identical shared sections; bisected segment ends; a ray-cast IoU estimate; "a failed `check(True)` is an invalid part". Two variants, measured at once. | **4/4** | **28** | 0.97 | 0.92, **0.94** | 0.02 M |

**Confirmation** of the final agent (round 3's second variant, which keeps a thin
slanted tip of part 2 that the first variant dropped): **10 of 10**, five per part, every check passing, part 1 IoU 0.970
with 50 faces and part 2 IoU 0.943 with 62 faces, about 20 s of agent time per run. The
ten runs took 2.5 minutes, five at a time.

## What the rounds taught

- **The environment came first.** With the agent in its own container next to FreeCAD,
  sharing real paths, a skill can ship a helper script and the agent simply runs it. The
  previous version of this example drove a shared FreeCAD GUI through an MCP server: the
  agent's files lived in a virtual file system FreeCAD could not see, so methods had to be
  copied into FreeCAD as code through the prompt, and runs could not go in parallel.
- **The biggest gain was removing work from the model.** Round 0 used 1.9 M tokens per
  run and saved nothing; from round 1 the model reads one skill and runs one command, and
  most of the run is the script.
- **The eval had to catch up.** Slice stacks with ~1,700 faces passed every check, which
  is not the model a designer would build. Compass found it, Eval Author proved a check
  for it, and the loop then had to find a compact method.
- **Validity is the hard part of geometry.** Most of the experimenters' time went into
  making lofts one solid that passes FreeCAD's full shape check, not into fidelity.
- **Measure the helper's own measurements.** A wrong IoU estimate made the agent retry
  blindly; once the estimate matched the grader within 0.003, the agent stopped after one
  build.

## Insights that stayed open

- "Saved FreeCAD models contain multiple visible objects despite success claims." Eval
  Author found the saved models correct (the extra visible items are origin datums and a
  spreadsheet, with no geometry); the agent's own report overstates what it checked.
- "Generic mesh slicing produces dense loft trees instead of design-intent CAD features."
  Four lofts through 24-27 sections pass `compact-model`, but a designer would revolve
  what is round. Eval Author found no geometry-agnostic check for it yet and listed the
  evidence that would justify one.

Run folders, traces, Compass outputs and experimenter notes stay in the git-ignored
`experiments/` folder.
