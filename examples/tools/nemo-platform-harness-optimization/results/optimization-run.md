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
untouched). It added a `geometry_overlap_audit` step the agent must pass before
finishing, reasoning in its own docstring that *"the model cannot omit the
measurement or manufacture its values"*, and falling back to bounding-box IoU
because *"mesh/solid boolean intersections are unreliable across FreeCAD
versions"*, which is independently true of this application.

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
- The winner is a wrapper change, so it is not promotable to a deployed agent
  the way a skill or a system prompt is. Step 9 promotion applies to candidates
  that change `agent.yaml` or `workspace/skills/`.
- Objective and guardrail read the same span here, so this run does not
  demonstrate the guardrail rejecting a candidate that trades geometry for
  metric.
