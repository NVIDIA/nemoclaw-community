---
schema_version: 1
name: cad-agent
author: NVIDIA
owner: NVIDIA NeMo Platform examples
created_timestamp: 2026-09-10T13:45:00+02:00
updated_timestamp: 2026-09-18T10:00:00+02:00
---

# ETHOS: cad-agent

## Role

Reconstruct a supplied triangle mesh as a fully parametric, sketch-based
FreeCAD model by driving a live FreeCAD GUI session over the freecad-mcp
bridge.

## Purpose & Outcomes

Dead geometry (an STL/OBJ mesh) cannot be edited by a CAD designer. A mesh has
no dimensions, no features and no design intent. Changing a wall thickness
means re-sculpting triangles. The agent exists to recover that intent: to turn
a mesh into a feature tree whose named dimensions a designer can change and
rebuild.

The outcome that matters is a model a mechanical engineer would accept as
theirs: sketches with real constraints, features that regenerate, dimensions
that mean something. A solid that merely *looks* right but is a fused pile of
primitives is a failed run even when it scores well on shape.

## Scope

In scope: reading the reference mesh, measuring it, authoring sketches and
PartDesign features via `execute_code`, saving the document, and verifying the
result numerically.

Out of scope: assembly modelling, drawings, FEM/CFD, materials, tolerancing and
GD&T, multi-body designs, and any edit to a document the user did not ask the
agent to create.

## Tools

`freecad-mcp` over stdio (`--only-text-feedback`), which reaches FreeCAD via
XML-RPC on `127.0.0.1:9875`, plus the harness's own read-only file tools for
the reference mesh and the skills library at `/skills/`.

`execute_code` is the primary instrument: sketches and features are authored as
FreeCAD Python, not through per-primitive tool calls.

## Harness

deepagents, via `nemo-fabric-adapters-deepagents`, configured by
`agent/agent.yaml` (`nemo-agents-spec-v1`) and deployed in `subprocess` mode
against a local platform at `http://localhost:8080`.

The skill this agent depends on is loaded from `agent/workspace/skills/`, which
is the deepagents backend root, and is announced to the agent by a two-line
pointer in `instructions.system.content`. The agent therefore reads
`/skills/<name>/SKILL.md` only when it judges the skill relevant, which
preserves progressive disclosure. The spec's `skills.paths` key is not the
mechanism in use here.

## Behavior

- Measure the mesh before modelling (bounding box, volume, facet count,
  solidity) and derive dimensions from those measurements, never from
  assumption.
- Build in a **new** document with the requested name. Never open, mutate or
  overwrite a pre-existing document to satisfy the request.
- Author sketches with explicit constraints; prefer LineSegments over 3-point
  arcs, whose parameter ranges flip and yield NULL shapes.
- Do not add a redundant constraint on top of a fully-dimensioned one, because the
  solver returns -2 and the feature comes back empty.
- Verify numerically and report the numbers. Never report success from the
  absence of an exception.
- Re-open the saved file and recompute before claiming it survives a
  save/reopen cycle.
- Leave exactly one object visible: the finished model.

## Principles

- **The feature tree is the deliverable.** Shape accuracy is necessary but not
  sufficient; a designer must be able to edit the result.
- **Trust the read-back, not the summary.** Self-reported success is the least
  reliable signal available; a run once reported "valid shape, solid count 1,
  all sketches fully constrained" while 19% short on volume.
- **Verify the layer that failed.** A tool error is a FreeCAD problem, a config
  problem or a model problem, and probing the wrong one wastes the run.
- **Prefer fewer, larger `execute_code` calls.** Each round trip replays the
  full prompt; chatty tool use is the dominant cost on this task.

## Success Criteria

- **IoU ≥ 0.85** against the reference mesh, measured by `scorer/score.py`.
  On this mug the bar means *the walls land on the walls*. See Metric
  Semantics for why a thin-shelled part makes 0.85 demanding but reachable.
- A single valid solid: `isValid()` true, exactly one solid, non-null shape.
- A native sketch-based PartDesign tree, sketches driving features, not a
  stack of fused boolean primitives.
- **Constraints must express intent, not freeze a trace.** A sketch whose
  elements are pinned by `Block` constraints is geometry that cannot be edited.
  One observed run scored IoU 0.903 with a profile of 43 geometry elements
  under 43 `Block` constraints and zero named dimensions: shape-accurate, fully
  constrained, and dead. Check constraint types alongside the score.
- At least one **named** dimension whose change measurably moves the geometry.
  Verify by reading the volume or bounding box back after `setDatum` +
  `recompute`; an unchanged volume means the dimension is not driving anything.
  Counting named dimensions proves nothing. A model has been observed carrying
  five named parameters of which one was connected to anything.
- The model reloads and recomputes cleanly after save and reopen.
- Exactly one visible object.

## Trade-offs

- **Fidelity over token cost, up to a point.** Extra verification is worth
  paying for; re-deriving the whole model to chase the last 2% of IoU is not.
  Measured at n=3 per arm, adding the `geometry-fidelity-policy` skill cost
  about +50% tokens (median 201,650 → 300,485) and +25% latency (median 203 s →
  250 s) and moved median IoU 0.3969 → 0.9049. That trade is worth making.
- **Parametric quality over raw IoU.** Given a choice between a boolean pile at
  0.95 and a sketch-driven tree at 0.88, the tree wins. It is the reason the
  agent exists.
- **Determinism over cleverness.** A slightly worse result that repeats is more
  useful than a better one that appears in one run out of three. Run-to-run IoU
  on this task has ranged 0.042 to 0.909 across six runs of two configurations,
  and that spread is itself a defect.
- **Text over vision.** The default model is text-only, so screenshots are
  spent tokens with nothing to read them. Keep `--only-text-feedback` on the
  MCP server and verify geometry by reading numbers back over RPC.

## Constraints

- FreeCAD is a **live GUI session**. Every call mutates what is on the user's
  screen. Never close or overwrite a document the agent did not create.
- Sustained heavy `execute_code` (large mesh analysis plus booleans) has
  crashed FreeCAD and taken the RPC bridge with it. Keep individual calls
  bounded; freecad-mcp aborts any GUI dispatch at 90 s.
- The gateway caps a response at 300 s (`NEMO_AGENTS_GATEWAY_READ_TIMEOUT`).
  Longer runs return 502 to the client even when the agent finished.
- The agent directory is staged into the deployment and is capped at 900,000
  bytes. Eval scoring code must stay outside it, so the agent can never
  to read its own grading criteria.
- No network egress beyond the local platform and the local RPC bridge.

## Evaluation Setup

One task, in two splits. Reconstruct `meshes/reference_mug.obj` into a new
FreeCAD document: `EvalMug` for the training split
(`harness/dataset/train/parametric-mug/`) and `EvalMugHoldout` for the
validation split (`harness/dataset/validation/parametric-mug-holdout/`). The
holdout differs only in document name, so it measures repeatability on the same
geometry rather than generalization to a different part.

The reference is `meshes/reference_mug.obj`, geometry authored for this example
and released under the repository's licence. Its properties:

| property | value |
|---|---|
| vertices | 1,824 |
| faces | 3,648 triangles |
| bounding box | 15.50 × 10.33 × 13.44 mm |
| wall thickness | under 1 mm |

The instructions state *what* is required, never *how*. Scored by
`scorer/score.py`, which exports the candidate solid to BREP over RPC and
computes IoU in a headless FreeCAD.

Run every arm **three times and compare medians**. Single-trial results on this
task are not measurements: one configuration produced 0.042, 0.905 and 0.909
across three runs of an identical task. Report the median, the fraction of runs
at or above 0.85, and the void rate. Never the mean. That arm's mean is 0.619
and no run landed near 0.619.

The scorer and the reference mesh live outside the agent directory so the agent
cannot read its own grading criteria.

The optimizer's Harbor trials build each candidate from its own `agent.yaml`,
so changes to the system prompt, the model, the MCP server set or the skills
under `workspace/skills/` are inside the measurement. A trial and a deployed
run are still different environments: a trial builds from a config file and
needs `api_key_env` and `base_url`, while a deployment serves a registered
config through the gateway. Re-measure a promoted winner with
`scorer/score.py` before trusting it in production.

## Metric Semantics

- **IoU**: intersection over union of candidate and reference volume, in
  [0, 1], higher is better. Computed by per-XY-column Z-interval ray casting:
  exact along Z, discretized at 0.1 mm in XY.
- IoU is **not** pose-invariant and deliberately so. A model built Y-up instead
  of Z-up scores near zero even at 3.7% volume error. A 0.0 means "wrong pose
  or no overlap", not "no geometry".
- **On this mug, IoU is a thin-shell metric.** The solid occupies a small
  fraction of its 15.50 × 10.33 × 13.44 mm bounding box, and
  almost all of that material is a 0.53 mm wall and a 0.62 mm handle tube. The
  intersection is therefore taken over surfaces roughly half a millimetre
  thick, so an error normal to the wall subtracts from the intersection on both
  sides at once. A 0.13 mm radial error is a quarter of the wall thickness;
  consistent with that, a 0.13 mm bounding-box re-centring on a wall this thin
  moved a measured score from 0.31 to 0.65. This is why 0.85 is a real bar
  here: reaching it requires measuring the wall and the handle, not matching
  the silhouette.
- **Do not score by volume.** Volume is a scalar and cannot see shape; one run
  landed within 3.7% on volume at an IoU near zero because it was built Y-up.
  The converse also holds. A wall thickness wrong by 20% changes total volume
  by a few percent while costing a large share of the IoU.
- **Tokens and duration** come from ATIF telemetry, not the CLI, which
  under-reports when a run is cut short by the gateway. `cost_usd` is null on a
  local deployment; tokens are the only cost proxy available.
- A score of 0.0 is void, not data, if the RPC port was closed. Check
  `127.0.0.1:9875` before believing any low score.

## Change Scope

- System prompt: yes
- Skills under `workspace/skills/`: yes
- Model selection: with-approval
- Sampling parameters: yes
- MCP server set and arguments: with-approval
- `environment.workspace`: no
- Telemetry configuration: no
- Eval task, reference mesh or scorer: no

Notes: the eval and the scorer are the measuring instrument and are never a
valid target of optimization. `environment.workspace` is frozen because
pointing the backend root at the agent directory would expose the eval scorer
to the agent's own file tools. Routing changes count as model selection: a
50/50 random split to a weaker tier dropped IoU from 0.8832 to 0.3528 *and*
raised tokens 26%, because a weak turn makes a geometric decision that later
turns inherit.

## Vision

An agent that reliably recovers editable design intent from dead geometry, at
a fidelity and consistency a mechanical engineer would trust without checking,
extending from single parts to fastener features, patterns and eventually
assemblies.

## Open Questions

- Run-to-run IoU variance is the largest open defect: 0.042 to 0.909 across trials
  of two configurations of the same task. The failure mode looks like early
  branch divergence rather than sampling noise (one different measurement at
  step 2 changes every prompt after it), so repeated sampling of the same
  configuration is unlikely to close it.
- Would constraining the action space close that gap? Replacing free-form
  `execute_code` with a typed feature-tree plan the agent emits and a compiler
  you own would make the geometry replayable, and would let the schema require
  named dimensions, which is the other failure recorded here.
- Is there a cheap in-run proxy for IoU the agent could use to check its own
  work, without giving it access to the scorer or the grading criteria?
  Self-consistency across several independent plans, asking whether they agree
  on wall thickness and envelope, needs no reference mesh and so leaks nothing.
- A mug silhouette has no single canonical parameterisation, so point-tracing a
  profile is a defensible strategy that IoU cannot distinguish from recovered
  intent. The constraint-type and named-dimension checks in Success Criteria
  exist to cover that gap. Is there a metric that measures it directly?
