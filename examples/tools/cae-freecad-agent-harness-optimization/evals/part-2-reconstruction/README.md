# Part 2 reconstruction in FreeCAD

## Difficulty explanation

The agent must turn a triangle mesh into an editable CAD model with FreeCAD. Matching
the shape is not enough: the model has to be a native sketch-based PartDesign tree
whose named dimensions actually rebuild it. Agents tend to shortcut
this by assigning a scripted shape to a generic feature, or by declaring success from
bounds and validity checks without measuring similarity to the mesh.

## Environment and software requirements

- The agent runs inside the task container, next to headless FreeCAD 1.1.3
  (`freecadcmd`) and the reference mesh at `/app`: a Deep Agents agent with a shell,
  built from `agent/agent.yaml` by `harness/cad_agent.py`, the Harbor agent. It
  reaches only the NeMo Helix inference gateway and Intake on the host, and saves
  its model to `/app/model.FCStd`. The container is capped at 4 GiB of memory.
- Every trial has its own container, so trials run in parallel.
- The verifier image installs FreeCAD 1.1.3 from conda-forge at build time and grades
  offline. All software is open source.
- The verifier runs without network access. Docker Desktop on macOS cannot
  enforce that; a Docker engine whose kernel supports nftables `fib` rules can
  (native Linux, or Colima on macOS).

## Ground-truth provenance

The reference mesh `reference_part_2.obj` is a second first-party part, modelled in
FreeCAD for this example and exported to OBJ, copied into the agent's and the
verifier's images. It was
added so the evals cover more than one shape, as the agent's `ETHOS.md` requires a
method that works for any part. The 0.9 IoU threshold and the editability
requirements come from the same `ETHOS.md`. The reference solution is the FreeCAD
model the mesh was exported from (IoU 0.9985). The task shares part 1's instruction,
verifier and checks; only the mesh differs. It has no source trace.

## Solution explanation

A passing model measures the mesh, builds the body from sketches with native
additive and subtractive features (the reference uses lofts, a pad and a
revolve through sketched profiles), drives those sketches from named parameters, and matches the mesh
closely.

## Verification explanation

The verifier opens the saved document in FreeCAD and reports five checks:
`single-valid-solid` (one PartDesign body with one solid that passes FreeCAD's full
shape check, including self-intersections),
`native-feature-tree` (sketch-driven PartDesign features and no scripted shape
wrappers), `named-dimension-drives-geometry` (changing a named constraint or a
referenced named parameter by 10% leaves one clean solid and changes a bounding-box
length by at least 1%),
`mesh-fidelity` (IoU against the reference mesh at 0.1 mm resolution
is at least 0.9), and `single-visible-object` (every visible
object with geometry is the Body or its tip feature, as the instruction's "exactly one
object visible" requires; origin axes and planes are ignored). The reward is 1 only
when all five pass. The verifier also logs the model's feature, sketch and face
counts (`complexity.json`) without grading them.

## Relevant experience

Authored and reviewed by [Author], who builds CAD and simulation agents and reviewed
the five checks against hands-on FreeCAD PartDesign modeling and the agent's
recorded failures.
