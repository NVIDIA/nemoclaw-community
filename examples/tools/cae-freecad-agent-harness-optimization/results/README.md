<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Results: Nemotron 3.5 Lightning, round by round

The agent under test runs on **Nemotron 3.5 Lightning**. Every round ran the loop on
fresh runs of the current agent: the eval (both tasks, three attempts each), NeMo
Compass on that round's traces, a NeMo Eval Author review of the new Insights, one
change to the agent, and a rerun. Compass and the coding agent that diagnosed and
changed the agent used larger models; only the agent under test is Nemotron.

The final agent is in [final-agent/](final-agent/agent.yaml): a system prompt, two
skills and tool gating on top of the [base agent](../agent/agent.yaml).

## The eval

Two tasks with the same instruction and the same five checks, one per reference part:
[part-1-reconstruction](../evals/part-1-reconstruction/README.md) and
[part-2-reconstruction](../evals/part-2-reconstruction/README.md). A run passes only
when all five checks pass; the main README's [Results](../README.md#results) explains
each check. IoU must be at least 0.9.

## Round by round

Every run had 10 minutes, and runs went one at a time. Tokens are the sum over every
model call in a run's trace.

| Round | What Compass and the traces showed | Change to the agent | Part 1 | Part 2 | Median tokens per run | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| 0. Base agent | | | 0/3 | 0/3 | 1.4 M | |
| 1. Session rules | Host discovery on FreeCAD's GUI thread froze it (5 of 6 runs); the mesh was converted to static shapes | Rules for the live session (no processes or disk searches, bounded calls, a circuit breaker, never convert the mesh); a skill of tested FreeCAD recipes; a plan | 0/3 | 0/3 | 4.9 M | kept |
| 2 to 8. A routine the agent can run | Geometry far from the mesh (IoU 0 to 0.35), never measured; a nonexistent `finish` tool called dozens of times | A tested, geometry-agnostic routine as a skill; then six fixes so the model runs it as written | 0 of 9 runs | | 2 M to 7 M | kept |
| 9. Code files and one call | The agent saw only part of the skill's code | The routine split into three files under 100 lines, then one `step(...)` call | 2/3 | 1/3 | 1.2 M | kept |
| 10. Self-checks and recovery | Copy errors, tinkering after `DONE`, editability claimed without a check | The blocks test themselves; `step` recovers from errors, finishes in one call and checks that `Params.Height` changes the geometry; nothing after `DONE` | 3/3, then 1/3 | 2/3, then 1/3 | 0.3 M, then 1.3 M | kept |
| 11. Stronger self-tests | One copy error the self-test missed | The self-tests build a small box | 1/3 | 2/3 | 2.6 M | rejected |
| 12. One skill file | Round 10 measured again: the agent tried to load the separate code files from inside FreeCAD | The three blocks back in `SKILL.md`, read with `limit: 400` | 0/1 | 1/2 | 5.1 M | stopped |
| 13. **One skill file, box self-tests** | A block copied without `chains_along` still passed round 10's self-test | Round 12 with round 11's self-tests | **4/6** | **4/6** | **0.8 M** | **final** |

Round 10 was measured twice (3 attempts per part each time) because its first result,
5 of 6, looked better than it was: the second run passed 2 of 6. Rounds 12 and 13
therefore ran 6 attempts per part. Round 12 was stopped after three runs, two of them
copy errors that round 10's self-test let through.

Rounds 2 to 8 were each stopped after one or two runs, as soon as the trace showed a
failure the next change had to fix:

| Round | What happened | Next change |
| --- | --- | --- |
| 2 | The 300-line code block was retyped with a syntax error | Five short blocks |
| 3 | Blocks 1 to 4 loaded; block 5 refused a document that already held objects | Build in an existing document |
| 4 | Blocks shortened or skipped, then a frozen FreeCAD | A compact routine (three blocks) |
| 5 | Block 1 cut off at its 64th line | Found: Deep Agents' `read_file` shows 100 lines by default; one file per block |
| 6 | Blocks 1 and 2 correct; the driver block rewritten | The driver as a function: one-line `step(...)` call |
| 7 | `step` built the part (fit 0.953), then the agent deleted documents | `step` finishes in one call |
| 8 | The agent tried to load the files from inside FreeCAD and froze it | Say that FreeCAD cannot see the skill's files |

In rounds 3 to 5 the previous round's agent was still running inside its deployment
when the round started (stopping the client does not stop the run), so those rounds'
first runs shared FreeCAD with it. Each verdict above rests on a failure seen in that
round's own trace.

### Every measurement

Per-check passes, IoU of the runs that left a model, and median tokens. Runs that ran
out of time or froze FreeCAD left nothing to score and fail every check.

| Round | Runs | `single-valid-solid` | `native-feature-tree` | `named-dimension-drives-geometry` | `mesh-fidelity` | `single-visible-object` | Passing runs | IoU per scored run | Median tokens per run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0. Base agent | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 1.4 M |
| 1. Session rules | 6 | 3 | 3 | 1 | 0 | 1 | 0 | 0.0, 0.0, 0.11, 0.35 | 4.9 M |
| 2 to 8 | 9 | 0 | 1 | 0 | 0 | 1 | 0 | 0.0 × 6 | 2 M to 7 M |
| 9. Code files and one call | 6 | 5 | 5 | 5 | 4 | 3 | 3 | 0.94 × 4, 0.07 | 1.2 M |
| 10. Self-checks and recovery | 6 | 6 | 6 | 6 | 5 | 6 | 5 | 0.94 × 5, 0.06 | 0.3 M |
| 10, measured again | 6 | 2 | 2 | 2 | 2 | 2 | 2 | 0.94 × 2, 0.0 | 1.3 M |
| 11. Stronger self-tests | 6 | 3 | 3 | 3 | 3 | 3 | 3 | 0.94 × 3 | 2.6 M |
| 12. One skill file | 3 | 1 | 1 | 1 | 1 | 1 | 1 | 0.94, 0.0, 0.0 | 5.1 M |
| 13. **One skill file, box self-tests** | 12 | 9 | 9 | 9 | 8 | 9 | **8** | 0.94 × 8, 0.06, 0.0 | **0.8 M** |

The final agent passed **8 of 12 runs, 4 of 6 on each part**. When it follows the
routine its models score IoU 0.94 on both parts (0.9397 to 0.9409 on part 1, 0.9399 on
part 2) in about a minute. Its four failures were the model going off-plan: twice a
copy error the self-tests caught, after which the agent wrote its own code instead of
copying again; once a search for the mesh that walked the disk and froze FreeCAD; and
once a finished model that the agent kept "verifying" until it had changed it.

What the rounds showed:

- **One generic routine passed both parts.** The routine slices the mesh along
  candidate directions, lofts the outlines it finds and keeps whichever direction
  matches the mesh best. It holds nothing specific to either part.
- **Most of the work was getting a small model to run code as written.** Nine of the
  thirteen rounds changed how the routine reached the agent, not what it did. The
  decisive finding came from a trace, not a guess: `read_file` returns 100 lines
  unless asked for more, so the agent never saw the end of a long skill.
- **Removing work cut tokens.** When `step` started finishing in one call, the median
  run fell from 1.2 M to 0.3 M tokens; runs that go off-plan still cost millions.
- **Measure twice.** Round 10 passed 5 of 6 and then 2 of 6. With three runs per part a
  single round can mislead, so the last rounds ran six per part. Round 11 looked like a
  strict improvement and measured worse; it was rejected.

Compass on the final agent's runs left three open Insights: the sketches carry no
Sketcher constraints, a finished model is not saved and reopened to check it, and
after a FreeCAD stall the agent spends many calls on recovery. The first two are
listed under Known limitations; the third is part of going off-plan.

## Limits

See [Known limitations](../README.md#known-limitations). The 10-minute budget is a
harness setting applied to every round, not part of the task.
