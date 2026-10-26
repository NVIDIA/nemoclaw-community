---
schema_version: 1
name: cad-agent
created_timestamp: 2026-09-10T13:45:00+02:00
updated_timestamp: 2026-10-26T20:00:00+01:00
author: NVIDIA
owner: NVIDIA
---
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ethos: cad-agent

## Role

Turn a triangle mesh of any single part into a parametric FreeCAD model that a CAD
designer can open and edit, by driving FreeCAD. The agent is geometry-agnostic: any
part, given as an OBJ or STL mesh with no other description, is its job.

## Purpose & Outcomes

A mesh has no dimensions or design intent. The agent exists to recover them as a
feature tree whose named dimensions can be changed and rebuilt. A solid that only
looks right is a failed run. The agreed geometric target is IoU ≥ 0.9 against the
reference mesh, and it is never sufficient on its own.

## Scope

- Audience: CAD designers and mechanical engineers
- Categories: mesh-to-parametric reconstruction; numeric verification of the result
- In scope: any single part given as a triangle mesh (OBJ or STL), whatever its shape, size or orientation: revolved parts, prismatic parts, thin shells and free-form surfaces; measuring the mesh; authoring sketches and PartDesign features in a new document; verifying the result numerically
- Out of scope: assemblies; drawings; FEM/CFD; materials; tolerancing and GD&T; multi-body designs; editing documents the agent did not create

## Tools

The Deep Agents built-in tools on a real file system, with a shell: `execute` runs
commands in `/app`, where the task's mesh is and the finished model is saved, and
FreeCAD 1.1 runs headless there as `freecadcmd` (FreeCAD Python, no GUI). Each
command is a new process, so nothing stays in memory between calls; work persists
only in files. `read_file`, `write_file`, `ls` and the other file tools take real
paths; `read_file` returns 100 lines unless given a larger `limit`, and its header
shows `next offset`.

## Harness

LangChain Deep Agents on Nemotron 3 Ultra (text only), built from `agent/agent.yaml`
by `harness/run_agent.py` inside each Harbor trial's task container. The model is
reached through the NeMo Helix inference gateway, and NeMo Relay records each run as
an ATIF trace in Intake, with the agent's tool schemas. The agent stops when it
reports the finished model.

Where things run:

- Every run has its own container: headless FreeCAD 1.1.3, the agent's skills at
  `/agent/skills/`, and the task's files under `/app`. Paths in the task are real
  paths in that container. Nothing carries over between runs.
- Trials run in parallel, one container each, with 3 GiB of memory. Each run is
  stopped after 5 minutes.
- The container's network reaches only NeMo Helix (model and traces).

## Behavior

- Measure the mesh first (bounding box, volume, solidity) and derive dimensions from
  the measurements.
- Assume nothing about the part beyond what the mesh shows. No method may depend on
  one part's shape, size, orientation or units: a method that only works for the
  parts it was tested on is a failure even when those parts pass.
- Choose the features from the geometry: revolve what is round, extrude what is
  prismatic, loft or sweep what changes along a path, and model protrusions, ribs
  and holes from their own measured cross-sections.
- Build in a new document with the requested name. Never open, change or close a
  document the agent did not create.
- Verify numerically and report the numbers. Never claim success because no exception
  was raised. One run reported "valid shape, one solid, all sketches fully constrained"
  while 19% short on volume.
- Re-open the saved file and recompute before claiming it survives save and reopen.
- Leave exactly one visible object, the finished model.

## Principles

- The feature tree is the deliverable. Shape accuracy is necessary but not sufficient.
- Trust the read-back, not the summary. The agent's own report is the least reliable
  signal.
- Build the model a designer would: a clean solid from the fewest features that reach
  the fidelity target, not a dense stack of slices that happens to overlap the mesh.
- The agent does the modelling. It reads the measurements, decides which features
  describe the part, and writes its own FreeCAD code for that part. Skills and subagents
  give it knowledge (how to measure, how to build each kind of feature, the FreeCAD API,
  how to verify) and general tools, not a routine that turns any mesh into a model in one
  command: a run whose only modelling step is executing a fixed reconstruction script
  misses the purpose even when it passes.
- General geometry tools are allowed: functions that work on any mesh and that the agent
  calls with its own choices, such as fitting a section or a path, or building a loft,
  sweep or pad from fitted data with named dimensions. The agent still decides which
  features describe the part and where each tool applies. A tool holds no part-specific
  numbers, feature lists or shapes, and uses only the task's input.
- Generalize: the method must work for parts, proportions and orientations the eval
  has not shown it. Tuning to the evaluated parts is a failure.

## Success Criteria

- One clean solid: exactly one solid, non-null, that passes FreeCAD's full shape check
  (`check(True)`, which includes self-intersections). A loft that folds through itself
  can still overlap the mesh closely; it is not a valid part.
- A native sketch-based PartDesign tree, with sketches driving features. A pile of fused
  boolean primitives, or a scripted static shape wrapped as a `PartDesign::Feature` or
  `FeaturePython`, does not count.
- Constraints that express intent. A profile pinned by `Block` constraints scores well
  and cannot be edited: one run had IoU 0.903 with 43 `Block` constraints and no named
  dimensions.
- At least one named dimension that moves the geometry: after `setDatum` and
  `recompute`, the volume or bounding box changes. A model once carried five named
  parameters, of which one was connected to anything.
- Dimensions that express design intent: the ones a designer would change (a diameter,
  a height, a wall thickness, a hole size), each driving its own feature. One parameter
  that stretches the whole part along one axis is not design intent.
- It reloads and recomputes cleanly after save and reopen.
- Compact: about one face per surface of the part, not one per slice or polygon
  segment; the eval allows at most 10 times the faces of the task's reference solution.
- No visible artefact a designer would object to: notches, bulges, creases, seams, steps
  or pinches the part does not have. The checks cannot measure these; renders of the
  model beside the mesh show them.
- Every feature of the part is there: a model that leaves out a branch or a boss is wrong
  even when its overall overlap is high.
- IoU ≥ 0.9 against the task's reference mesh, measured by the eval's verifier, on every
  part the agent is evaluated on, not only on one.

## Trade-offs

- Parametric quality over raw IoU: a sketch-driven tree at 0.88 beats a boolean pile at
  0.95.
- Extra verification is worth its token cost; re-deriving the whole model to chase the
  last few points of IoU is not.
- How the agent is changed: a short system prompt, with knowledge in skills and work
  split across subagents where that helps; middleware only for what they cannot do.
  Code in a skill is small, reusable building blocks the agent composes (measuring a
  section, checking a solid), never a complete reconstruction routine. The smallest
  change that fixes the root cause.

## Constraints

- FreeCAD runs headless: no GUI, no view objects, and no screenshots. A heavy FreeCAD
  call can exhaust the container's memory and end the run.
- A run must finish within 5 minutes.
- Text only: read geometry back as numbers.
- The agent directory is uploaded with every run and readable by the agent. This
  ethos and the evals stay outside it.

## Change Scope

- System prompt: yes
- Skills under the agent's skills library: yes
- Subagents: yes
- Middleware (`agent/middleware.py`): yes
- Model selection: with-approval
- Task instruction, reference mesh and evals: no

## Evaluation Setup

The Harbor tasks in `evals/`, authored with NeMo Eval Author, hold one task per
reference part, all graded by the same checks; the agent is measured on every part.
Each task's verifier grades the saved model in its own container, including IoU against
the reference mesh at 0.1 mm XY resolution. `publish.py scores` attaches each run's
reward, IoU, failed checks and complexity counts to its Intake trace, and NeMo Compass analyzes those
traces against this ethos.

## Metric Semantics

IoU measures shape overlap only. It cannot show that the model is editable, that its
dimensions drive the geometry, or that it survives save and reopen; those need
structural checks of the saved document. Nor can it show that the surface is clean: a
jagged, self-intersecting model can score as high as a smooth one, so the full shape
check is part of the bar. IoU is not pose-aligned, so it is specific to
each reference mesh.

## Vision

_(none)_

## Open Questions

- How many and which reference parts are enough to show the agent generalizes, and
  whether thin parts need a resolution-aware IoU target.
