# Part 2 reconstruction in FreeCAD

## Difficulty explanation

The agent must turn a triangle mesh into an editable CAD model inside a live FreeCAD
session. Matching the shape is not enough: the model has to be a native sketch-based
PartDesign tree whose named dimensions actually rebuild it. Agents tend to shortcut
this by assigning a scripted shape to a generic feature, or by declaring success from
bounds and validity checks without measuring similarity to the mesh.

## Environment and software requirements

- The agent runs on the host, outside the task container: a NeMo Helix deployment
  (`cad-agent`, Deep Agents) driving the FreeCAD 1.1.3 GUI through freecad-mcp 0.1.24
  over XML-RPC on `127.0.0.1:9875`. `harness/helix_cad_agent.py` is the Harbor agent
  that invokes it and hands the saved document to the task as `/app/model.FCStd`.
- Trials must run serially: there is one FreeCAD session.
- The verifier image installs FreeCAD 1.1.3 from conda-forge at build time and grades
  offline. All software is open source.
- Both containers run without network access. Docker Desktop on macOS cannot
  enforce that; a Docker engine whose kernel supports nftables `fib` rules can
  (native Linux, or Colima on macOS).

## Ground-truth provenance

The reference mesh `reference_part_2.obj` is a second first-party part, modelled in
FreeCAD for this example and exported to OBJ; the verifier alone keeps it. It was
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
`single-valid-solid` (one PartDesign body with one valid solid),
`native-feature-tree` (sketch-driven PartDesign features and no scripted shape
wrappers), `named-dimension-drives-geometry` (changing a named constraint or a
referenced named parameter by 10% changes the recomputed geometry),
`mesh-fidelity` (IoU against the reference mesh, recomputed with the same algorithm
as the host scorer, is at least 0.9), and `single-visible-object` (every visible
object with geometry is the Body or its tip feature, as the instruction's "exactly one
object visible" requires; origin axes and planes are ignored). The reward is 1 only
when all five pass.

## Relevant experience

Authored and reviewed by [Author], who builds CAD and simulation agents and reviewed
the five checks against hands-on FreeCAD PartDesign modeling and the agent's
recorded failures.
