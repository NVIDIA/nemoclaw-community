<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Compass Insights trail

After each eval round, NeMo Compass read the round's traces against the Ethos and the
grader's results and wrote a short list of **Insights**: what went wrong, how often, and
what to change. NeMo Eval Author then judged each Insight against the eval: already
caught by a check, outside what the eval should grade, or a gap that needs a new check.
The experimenter used both to build the next candidates.

The files here are Compass's raw output, one per published round that had a Compass run
(rounds 5, 8 and 9 had none: round 5 was rejected on its runs alone, round 8 was smoke
tests only, and round 9's gap came from renders and Eval Author). Names and paths are
neutralised; nothing else is changed.

How to read one Insight:

- `name` and `description`: the finding, and Compass's suggested fix.
- `evidence`: the traces (`trace_id`) and the steps in them (`span_id`) that show it.
- `confidence` and `severity`: how sure Compass is, and how much it costs the run.

| Round | Compass Insight | Eval Author | Addressed by | Fixed? |
| --- | --- | --- | --- | --- |
| [0](round-0.yml) | Runs spend the whole 5 minutes analysing the mesh; no model saved | Caught: no file fails all six checks | A skill with a script that builds and saves a model in one command, plus a time budget (round 1) | Yes, round 1 (every run saves a model) |
| [0](round-0.yml) | Model building stalls in repeated failing FreeCAD API experiments | Caught: no file fails all six checks | Same script: the agent no longer writes raw API calls (round 1) | Yes, round 1 |
| [1](round-1.yml) | Late retries use up the run; no final report | Outside the eval: the report is not graded | A "done" rule in the skill (round 3), then a clock and stop-and-report (round 7) | Yes, round 7 (every run reports) |
| [1](round-1.yml) | Every model is a dense stack of slices | Not caught: slice stacks pass every check. **New check `compact-model`** | Lofts instead of slices (round 2, invalid), valid joints (round 3) | Yes, round 3 (50-62 faces, limit 70/360) |
| [1](round-1.yml) | Agent ships a model despite its own low fidelity estimate | Caught by `mesh-fidelity` | A sound IoU estimate and "done only at IoU 0.9" (round 3) | Yes, round 3 |
| [2](round-2.yml) | Fidelity fails in all four runs | Caught by `mesh-fidelity` (part 1's "IoU 0" was never measured: invalid solid) | Valid joints (round 3) | Yes, round 3 |
| [2](round-2.yml) | Invalid solids shipped although FreeCAD's strict check failed | Caught by `single-valid-solid` | Joints as flat steps; "a failed strict check is an invalid part" (round 3) | Yes, round 3 |
| [2](round-2.yml) | Named-dimension test passes locally but fails the grader | Caught; a side effect of the invalid solid, not of the dimension | Same fix (round 3) | Yes, round 3 |
| [2](round-2.yml) | Lofts with many sections fail `compact-model` | Caught by `compact-model` (75-83 faces, limit 70) | Same fix (round 3) | Yes, round 3 |
| [3](round-3.yml) | Saved files show several visible objects; the agent claims one (again in [round 4](round-4.yml)) | Check is right: the extras are the model's own tip and datums. The wrong claim is outside the eval | No change | Not a model defect; GUI question left open |
| [3](round-3.yml) | One generic slicing script, not design-intent features; one dimension only stretches the part | No check yet: any rule failed a reference model. Named "a second independent dimension" as the case that would justify one | Ethos revision; **new check `independent-dimensions`** | Yes, round 6 (passes on every run) |
| [4](round-4.yml) | The agent delegates the modelling to a fixed script; only `Length` moves anything | Caught by `independent-dimensions` | Script removed, knowledge skills (round 5, failed), feature-level blocks (round 6) | Yes, round 6 |
| [6](round-6.yml) | Final models below the fidelity bar (IoU 0.27, 0.80) | Caught by `mesh-fidelity` | A save that names missing and extra regions, and a structure summary (round 7) | Yes, round 7 (IoU 0.92-0.95) |
| [6](round-6.yml) | Runs end with an empty reply | Outside the eval: the reply is not graded | Clock middleware, stop-and-report at 4 minutes (round 7) | Yes, round 7 |
| [7](round-7.yml) | Late repair builds time out; an older model is submitted | Outside the eval: the submitted files pass every check | No change | Not seen again (round 10) |
| [7](round-7.yml) | The body loft swells where the branch joins it | Outside the eval (2% local, IoU still above 0.9). Risk noted: a part-1 model without its branch would pass | Smooth body loft, no sections at the branch root (round 8); branch joined on a flat face (round 9) | Yes, round 9 (renders; no check measures it) |
| [10](round-10.yml) | Runs pass below the agent's own 0.92 IoU target | Outside the eval: the bar is 0.9; 0.92 is the agent's own stop rule | No change | Not an eval gap |

## Key chains

- **Slice stacks pass every check** (round 1) → Eval Author adds `compact-model` → round 2's
  lofts are compact but invalid → round 3 makes the joints valid → fixed in round 3.
- **One script, one stretch dimension** (round 3) → Eval Author: no check without an Ethos
  rule → the owner revises the Ethos → `independent-dimensions` → Compass, round 4: "delegates
  the modelling to a fixed script" → feature-level blocks the agent assembles itself →
  fixed in round 6.
- **Models below the fidelity bar, empty replies** (rounds 1, 6) → both already graded or
  outside the eval → a clock, a stop-and-report, and a save that says what is missing →
  fixed in round 7.
- **The body swells into the branch** (round 7) → outside the eval, but Eval Author warns
  that part 1 would pass with no branch at all → smoother bodies in rounds 8-9 → two round-9
  runs leave the branch out and pass → **new check `no-missing-feature`** → round 10 never
  drops the branch → fixed in round 10.
