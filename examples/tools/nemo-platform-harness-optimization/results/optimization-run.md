<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Two runs, and what each one measured

Both runs used the Insight *"Mesh-fidelity verification does not establish close
geometric agreement"*, 1 round, 2 candidates, `n_attempts: 2`, one FreeCAD
session. The first produced a result that did not survive inspection. The
second was run after fixing what the first exposed.

## Run 1: a win that could not be shipped

| Arm | Validation | n |
| --- | ---: | ---: |
| `agent-0` baseline | 0.514 | 4 |
| `agent-1` winner | 0.664 | 4 |
| `agent-2` | 0.402 | 4 |

The winner's entire change was 157 lines added to `harbor_wrapper.py`, the
evaluation harness. It added a `geometry_overlap_audit` whose docstring claimed
to measure geometry *"before allowing the run to finish"*.

The traces said otherwise. The audit ran once per trial and produced real
numbers, but it was called host-side after the agent had already finished: the
agent's own trace for every trial contains no reference to it, so the result
never entered the model's context and nothing was gated. Its bounding-box proxy
reported 0.9975 on a trial whose true IoU was 0.5656.

So the +0.150 was not attributable to the change it was credited with, and the
change was not promotable in the first place. A harness edit ships nothing.

## The fix: pin everything that cannot be promoted

`_assert_promotable_change_surface` now runs before any trial and pins two
things against the originals outside the candidate:

- `harbor_wrapper.py`, byte for byte
- every `agent.yaml` block except `instructions` and `harnesses`

What remains is the change surface, and it is what a deployed agent carries:
the system prompt, subagents, and skills under `workspace/skills/`. The model
and its sampling parameters are pinned too, because a stronger model is a
deployment decision and leaving it open turns "which prompt works better" into
"which model is stronger".

Middleware and pre- or post-model hooks need no rule. The deepagents adapter
accepts only `subagents` and `interrupt_on` under `harnesses` and owns the
rest, so they cannot be expressed in `agent.yaml` and no candidate could
promote one.

## Run 2: what the loop proposed once it could only propose deployable things

Baseline, no errors in either arm:

| Arm | Mean | Median | Trials |
| --- | ---: | ---: | --- |
| `agent-0` train | 0.390 | 0.388 | 0.178, 0.227, 0.280, 0.497, 0.543, 0.613 |
| `agent-0` validation | 0.656 | 0.628 | 0.486, 0.515, 0.741, 0.882 |

Both candidates stayed inside the change surface without being stopped by the
guard; it never had to reject anything. Neither wrote a skill.

**`agent-1` changed only the system prompt** (41 lines). It added a
fidelity-gated completion loop: after every substantial geometry change,
measure reference and candidate in the same coordinate frame and compare
enclosed volume, axis-aligned bounds including placement, volumetric overlap,
and bidirectional surface distance reported separately in each direction. If a
discrepancy is material, stay in the same run and go back to fitting. Do not
complete because the document recomputes or one metric improved.

**`agent-2` added a subagent** (144 lines) under
`harnesses.deepagents.settings.deepagents.subagents`: a
`reference-geometry-analyst` with its own system prompt and a `response_format`
schema, plus a parent prompt requiring `task` as the first tool call and
forbidding construction before the analyst returns. The analyst is told to
report ordered contours rather than radii, detect cavity boundaries separately,
report X and Y extents independently, and not to infer rotational symmetry from
an object name.

## Both changes provably executed

This is the check that run 1 failed, done from the traces rather than the diff.

`agent-1`, against three baseline traces from the same session:

| marker | `agent-1` | baseline |
| --- | ---: | ---: |
| `distToShape` | 848 | 0, 0, 0 |
| `common(` | 424 | 116, 92, 0 |
| reference mesh loaded | 3923 | 0, 0, 0 |

Neither `distToShape` nor `common(` appears in the prompt, which asks for
"bidirectional surface distance" and "volumetric overlap" in English. The agent
translated those into FreeCAD calls itself, so the counts come from executed
code rather than replayed prompt text.

`agent-2`, deduplicated tool calls from one trace:

```text
execute_code 7 | list_documents 2 | ls 2 | task 1
execute_code_headless 1 | read_file 1 | ReferenceFittingSpecification 1
```

The subagent was invoked and returned its structured response, so the
`response_format` schema survived the adapter passthrough.

Note the trap in reading this. Intake's `tool_name` column holds the LangGraph
node name, not the tool, so filtering on it reports zero `task` calls. The real
calls are inside the span payloads and must be deduplicated on the call id.

## What run 2 does not establish

**The reward comparison is not usable.** Trials that error are dropped from the
denominator, not scored as zero:

| Arm | Scored | Errored | Mean |
| --- | ---: | ---: | ---: |
| `agent-0` validation | 4 | 0 | 0.656 |
| `agent-1` validation | 2 | 2 | 0.642 |
| `agent-2` validation | 1 | 2 | 0.675 |

A baseline averaged over four runs against candidates averaged over two and one
is survivorship bias, and no reading of those means is sound. The failures were
environmental rather than candidate-specific: one Docker
`EnvironmentStartTimeoutError` at 600 s, one `RewardFileNotFoundError`, and two
trials the wrapper refused to score because FreeCAD's GUI dispatch was
unhealthy. That last one is the harness working as intended, declining to turn
an application failure into a score of zero, but it still distorts the
comparison.

The run was stopped before the candidate train arms, which would have added
12 trials at roughly 9 minutes each without addressing any of the above.

**Objective and guardrail coincided again.** The Eval Author named its metric
`symmetric_geometry_fidelity` and it returned exactly `eval_iou` on every
trial, as `symmetric_material_overlap` did in run 1. So neither run exercises
the guardrail rejecting a candidate that trades geometry for metric.

## What changed between the runs, and why

Three runs against the same Insight, and the differences are mostly the
harness, not the agent:

| | Harness allowed | Eval Author wrote | Candidates went to |
| --- | --- | --- | --- |
| earlier run | a fixed deployment; candidate configs never executed | `geometry_fidelity_validation` | a skill, and the wrapper |
| run 1 | candidate-local invocation, nothing pinned | `symmetric_material_overlap` | the wrapper, and the system prompt |
| run 2 | wrapper and non-promotable config pinned | `symmetric_geometry_fidelity` | the system prompt, and a subagent |

Two things move independently.

**The candidates follow the change surface.** When the wrapper was editable a
candidate took it every time, because it is the shortest path to moving a
number. Pin it and the same coding agent, on the same Insight, writes a
completion gate and a subagent instead. The loop was never choosing between
shippable and unshippable work; it was taking whatever was open.

**The Eval Author is non-deterministic.** Same Insight, same traces, three runs,
three differently named metrics. Re-authoring is a re-baselining event rather
than a refresh, which is why comparing rewards across runs is meaningless and
every comparison here is within one run or measured out of loop. All three
metrics also resolved to the same `eval.iou` span in the end, so no run
exercised the guardrail.

## The three surfaces came from three different candidates

Worth stating plainly, because the table below puts them side by side. A round
is a baseline plus `max_candidates` rival agents, each a full copy of
`agent_source/` carrying **one** change. They compete; they are never merged.

| Surface | Candidate | Run |
| --- | --- | --- |
| `workspace/skills/geometry-fidelity-policy/` | one candidate | an earlier run |
| `instructions.system.content` | `agent-1` | run 2 |
| `harnesses...deepagents.subagents` | `agent-2` | run 2 |

No candidate proposed more than one of them, and no run produced all three. Each
was promoted onto the baseline separately and measured on its own.

## Measured out of loop

The loop's reward table was unusable, so both candidates were re-measured
directly: `nemo agents invoke --agent-config` against each config, scored by
`scorer/score.py`, same task, same session, one run each, arms alternating.
FreeCAD health was recorded at scoring time so a void could not be mistaken for
a low score. All three runs were healthy.

| Agent | Surface changed | IoU | Tokens | Spans | Wall time |
| --- | --- | ---: | ---: | ---: | ---: |
| baseline | nothing | 0.4783 | 196,289 | 135 | 3m23s |
| skill | `workspace/skills/geometry-fidelity-policy` | 0.5370 | 236,650 | 151 | 5m04s |
| system prompt | `instructions.system.content` | **0.8974** | 235,581 | 154 | 4m14s |
| subagent | `harnesses...deepagents.subagents` | **0.9414** | 632,265 | 289 | 8m44s |

Tokens and spans come from the ATIF trace of each run, not the CLI. `cost_usd`
is null on a local deployment because no price list is attached to the inference
gateway, so tokens are the only honest cost proxy.

The two unconditional changes won. A skill is read only if the agent judges it
relevant, and the failure being fixed is the agent judging that it does not need
to check; a completion gate and a forced analysis phase have no such opt-out.

The prompt and subagent arms land above every baseline trial measured that day;
the optimizer's baseline spanned 0.178 to 0.882 across ten scored trials.

**This is n=1 per arm.** One paired observation is a signal, not an effect size,
and this task is bimodal: the same configuration has produced 0.042, 0.905 and
0.909 across three runs. Treat the table as evidence that both changes reach
the agent and do something, and as a reason to run n=3 before quoting a number
anywhere that matters. Raw results are in
[`results/candidates/measurement.csv`](candidates/measurement.csv).

The subagent is the most accurate and by far the most expensive, at 2.6x the
baseline's wall time for its separate analysis phase.

## What it does establish

The loop, restricted to surfaces that can be deployed, proposed two changes
that a human would recognise as reasonable, and both of them ran. One is a
prompt, one is a subagent, and each promotes by copying `agent.yaml` and the
workspace. Whether either is better than the baseline is unmeasured.

The measurable claim from these two runs together is about the harness, not the
agent: a loop will optimize whatever surface you leave open, including one that
cannot be shipped, and it will do so convincingly enough to survive a diff
review. Pinning the surface is what makes the reward mean something.

## Reproducing

`results/candidates/` holds all three proposed surfaces as produced:
`system-prompt.yaml`, `subagent.yaml` and `geometry-fidelity-policy/`.
