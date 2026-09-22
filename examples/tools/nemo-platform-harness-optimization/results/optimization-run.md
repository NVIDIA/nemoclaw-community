<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# One optimization run, end to end

A bounded run of the loop described in the README, on the Insight
*"Mesh-fidelity verification does not establish close geometric agreement"*.
Config as shipped: 1 round, 2 candidates, `n_attempts: 2`, one FreeCAD session.

## Result

| Arm | Validation reward | vs baseline | n | median IoU | range |
| --- | ---: | ---: | ---: | ---: | --- |
| `agent-0` baseline | 0.514 | | 4 | 0.5139 | 0.2948 to 0.7327 |
| **`agent-1` winner** | **0.664** | **+0.150** | 4 | 0.6635 | 0.5656 to 0.7626 |
| `agent-2` | 0.402 | -0.112 | 4 | 0.3970 | 0.3360 to 0.4781 |

Baseline train reward was 0.396 over 6 trials. The Eval Author named its metric
`symmetric_material_overlap`; it reads the `eval.iou` span the wrapper
publishes, so objective and guardrail coincided in this run.

## What the candidates changed

Both proposals were reached from the traces and the Insight alone.

**`agent-1`, the winner, edited the wrapper only** (157 diff lines, `agent.yaml`
untouched), adding a `geometry_overlap_audit` method whose docstring claims to
measure geometry *"before allowing the run to finish"*.

The traces say otherwise, and this is the important finding of the run. The
audit ran once per trial in all four `agent-1` trials and in none of the
baseline trials, and it produced real numbers. But it was called host-side by
the wrapper after the agent had already finished: the agent's own trace for
each trial contains no reference to it, so the result never entered the model's
context and nothing was gated. Its bounding-box proxy also reported 0.9975 on a
trial whose true IoU was 0.5656, so it could not have gated anything useful.

**The +0.150 is therefore unexplained.** It is not attributable to the change
it was credited with. Since the harness is not promotable in the first place,
the fix is to stop such candidates from being scored at all: the wrapper is now
pinned by `_assert_promotable_change_surface`, and a candidate whose copy
differs from the original raises at import and produces no metric.

**`agent-2` edited `agent.yaml` only** (28 diff lines, wrapper untouched). It
rewrote the system prompt into three mandatory phases: coordinate-frame analysis
before any feature, construction in that frame, then axis-by-axis verification
of centers, extents, orientation and symmetry before submitting, with an
explicit rule against declaring completion while a frame contradiction remains.

That candidate is the one worth noting. A system prompt lives only in
`agent.yaml`, so under a harness that invokes a fixed deployment it would have
scored exactly the baseline. Here it scored 0.402, which is a real measurement
of a real change: **the proposal was tested and it made the result worse.**

## The guardrail held

`eval_iou` is computed by `scorer/trial_metric.py`, outside the directory the
optimizer copies into each candidate. The winner's 157-line wrapper diff
contains no reference to the metric, the scorer, or `eval.iou`, and its loader
call is unmodified. The code that measured the winner was not code the winner
could edit.

## Trace attribution

Verified across all 26 trials: no trace id appears under more than one trial,
and every trial records the agent config it was built from. An earlier run,
before trials were serialised, produced two trace ids each shared by two
different candidates reporting different scores.

The wrapper warned three times that several traces matched its window under one
agent name and that it was taking the oldest. That is the conservative path
working as intended rather than a fault, but giving each candidate a distinct
agent name would remove the ambiguity at the source.

## Limits

- One round, two candidates, four validation trials per arm. Enough to separate
  0.664 from 0.402; not enough to resolve a small difference.
- Per-trial spread is wide (baseline 0.087 to 0.744), which is why
  `n_attempts: 2` is set and why the medians matter more than any single trial.
- The winner is a wrapper change, so it is not promotable and its margin is
  not trustworthy. The run is retained as the evidence that produced the
  promotable-surface guard, not as a demonstration that the loop improved the
  agent. `agent-2` is the sound measurement in it.
- Objective and guardrail read the same span here, so this run does not
  demonstrate the guardrail rejecting a candidate that trades geometry for
  metric.
