<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Compass Insights trail

Each round, NeMo Compass read the kept agent's train traces (20 runs, one per task) against
the Ethos and the grader's results and wrote a short list of **Insights**: what went wrong,
how often, and what to change. The orchestrator then checked each Insight against the eval
(Step 3, by hand: Eval Author's skills were not run in this loop): already caught by a check,
or a gap that needs a new check. The experimenters read the same
train traces and Insights, never val, and built the next candidates. The keep decision was
made on val (14 runs, two per task).

The files here are Compass's raw output, one per round that had a Compass run: rounds 0, 1,
3, 4 and 7. Rounds 2, 5, 6 and 8 had none. Their kept agent was the same as the round
before, so they reused its Insights: round 2 used round 1's, rounds 5 and 6 used round 4's,
and round 8 used round 7's. Names and paths are neutralised; nothing else is changed.

How to read one Insight:

- `name` and `description`: the finding, and Compass's suggested fix.
- `evidence`: the traces (`trace_id`) and the steps in them (`span_id`) that show it.
- `confidence` and `severity`: how sure Compass is, and how much it costs the run.

The review found every Insight already caught by an existing check. No check was added or
changed in this run. Some candidates were built from the train traces before that round's
Compass run finished; their CANDIDATES files say so. In the table, val numbers are out of
14 runs and test numbers out of 35.

| Round | Compass Insight | Eval review | Addressed by | Fixed? |
| --- | --- | --- | --- | --- |
| [0](round-0.yml) | Loft retries leave out the loft's first profile | Caught: no model saved fails every check; a broken loft fails `single-valid-solid` | A toolkit skill with sketch and loft building blocks and the right loft API (r1-skills, round 0, kept) | Yes: not raised again |
| [0](round-0.yml) | A wrong four-argument radius constraint crashes FreeCAD; no model saved | Caught, as above | Same skill: the three-argument form and building blocks (round 0) | Yes: not raised again |
| [0](round-0.yml) | Runs end with mesh measurements and no saved model | Caught: every check fails without a model | Build-and-save middleware (r1-process, round 0, dropped: 0/14 on val); the skill's one-call measuring tools and "save a first model by minute 2" (r1-skills, round 0, kept) | Partly: a valid model on val 0/14 → 10/14; raised again in rounds 1 and 7 |
| [1](round-1.yml) | Failed cavity lofts are saved anyway | Caught by `single-valid-solid` or `mesh-fidelity` | A save guard that reopens each save and rolls back a failing one (r2-process, round 1, dropped; then r3-lookguard, round 2, kept) | Yes, round 2: `single-valid-solid` 14/14 on val |
| [1](round-1.yml) | Runs measure and never run a build | Caught: every check fails without a model | Same guard, plus a clock on every tool result and no silent end (r3-lookguard, round 2) | Yes on val from round 2 (a valid model on 14/14); raised again in round 7 |
| [1](round-1.yml) | Build errors are not recovered before the run ends | Caught by `recomputes-after-reopen` or `single-valid-solid` | Same guard: it flags a script not yet run and errors hidden behind exit code 0 (r3-lookguard, round 2) | Partly: not raised in rounds 3 and 4; in round 7 one train run's builds all failed |
| [1](round-1.yml) | Valid solids miss fidelity and features | Caught by `mesh-fidelity` and `no-missing-feature` | Looking at renders (r2-vision, round 1, dropped); section fits (r3-shapes, round 2, dropped); section fits on the kept agent (r4-shapes, round 3, kept) | Partly, round 3: `mesh-fidelity` 5 → 9, `no-missing-feature` 4 → 7 on val; raised again in rounds 3, 4 and 7 |
| [3](round-3.yml) | Valid models still fail the fidelity bar | Caught by `mesh-fidelity` | Section fits (r4-shapes, round 3, kept; built before this Insight) | Partly, as above |
| [3](round-3.yml) | Named dimensions do nothing or break the model when edited | Caught by `named-dimension-drives-geometry` and `independent-dimensions` | A dimension probe after each save (r4-dims, round 3, dropped: it cost time); a cheaper polygon-edge fix (r5-dims, round 4, dropped) | Not by a kept change. Both checks 14/14 on val for the final agent; raised again in rounds 4 and 7 |
| [3](round-3.yml) | The revolve axis ignores off-axis sections | Caught by `mesh-fidelity` | A measured revolve axis and profile for round bodies (r9-body, round 8, kept) | Partly: final agent's val mean IoU 0.95; on test, cups and tubs passed 1/5 each |
| [3](round-3.yml) | High-overlap models still leave out features | Caught by `no-missing-feature` | Side-feature tools (r5-sides, round 4, and r6-sides, round 5, both dropped); the same tools plus a prompt at the first save (r7-sides, round 6, kept by judgement) | Partly, round 6: `no-missing-feature` 7 → 12 on val; 13/14 for the final agent, 17/35 on test |
| [3](round-3.yml) | Failed loft rebuilds leave an earlier, known-wrong model | Caught: the saved model is graded as it is | No candidate targeted it | Not raised again |
| [4](round-4.yml) | Self-intersecting lofts reach the grader | Caught by `single-valid-solid` | A fast IoU estimate, so a bad loft shows in seconds (r6-fast, round 5, dropped; carried into r7-sides, round 6, kept) | Yes on val: `single-valid-solid` 14/14 for the final agent; not raised again |
| [4](round-4.yml) | Valid models fail the fidelity bar | Caught by `mesh-fidelity` | Side-feature tools (r7-sides, round 6); a measured revolve profile (r9-body, round 8) | Partly: `mesh-fidelity` 9 → 12 on val (round 6); raised again in round 7 |
| [4](round-4.yml) | Feature completeness is not checked before the end | Caught by `no-missing-feature` | Side-feature tools read on demand (r6-sides, round 5, dropped), then r7-sides (round 6, kept) | Partly, as in round 3 |
| [4](round-4.yml) | Named-dimension edits make valid models invalid | Caught by `named-dimension-drives-geometry` and `independent-dimensions` | r5-dims (round 4, dropped; built before this Insight) | Not by a kept change; raised again in round 7 |
| [7](round-7.yml) | Runs end without saving a first model | Caught: every check fails without a model | A gate that blocks other work until a model is saved (r8-safe, round 7, dropped: 7/14 passed on val) | Yes on val in round 8: the final agent saved a valid model on 14/14, though no kept change aimed at it |
| [7](round-7.yml) | Low-fidelity models are delivered | Caught by `mesh-fidelity` | A measured arm arc (r8-arms, round 7, and r9-arms, round 8, both dropped); a measured revolve profile (r9-body, round 8, kept) | Partly, round 8: 11/14 passed on val, mean IoU 0.95; `mesh-fidelity` 7/35 on test |
| [7](round-7.yml) | Named dimensions fail the independent edit test | Caught by `independent-dimensions` | No candidate targeted it | Partly: 14/14 on val, 28/35 on test for the final agent |

## Key chains

- **No model saved** (rounds 0, 1, 7) → already graded → a toolkit skill (round 0), then a
  save guard with rollback and a clock (round 2) → a valid model on every val run from round 2.
  It came back on train in round 7; a save-first gate cost passes and was dropped. The final
  agent saved a valid model on every val run.
- **Valid solids that miss fidelity and features** (rounds 1, 3, 4, 7) → already graded →
  renders (dropped), section fits (kept, round 3), side-feature tools with a prompt at the
  first save (kept by judgement, round 6), a measured revolve profile (kept, round 8) → val
  passes 4 → 7 → 11 of 14. On test, `mesh-fidelity` passed on 7 of 35 runs.
- **Side features left out** (rounds 3, 4) → already graded → side-feature tools dropped
  twice (round 4: one run saved no model; round 5: one check fewer) → combined with the fast
  IoU estimate and a prompt at the first save → kept by judgement after a second val
  measurement repeated the gain (round 6).
- **Wrong revolve axis** (round 3) → already graded → no change until round 8, when most
  failed round bodies turned out to have a handle that hid their axis → profile.py measures
  the axis and the profile → kept; the final agent.
- **Named dimensions that do nothing or break** (rounds 3, 4, 7) → already graded → a
  dimension probe and a cheaper edge fix, both dropped → not resolved by a kept change. Both
  dimension checks pass 14/14 on val for the final agent, but `independent-dimensions` fails
  7 of 35 test runs.
