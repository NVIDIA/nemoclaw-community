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
  its model to `/app/model.FCStd`. The container is capped at 3 GiB of memory.
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

The verifier opens the saved model in FreeCAD, rebuilds every feature from its inputs,
and reports nine checks; the reward is 1 only when all pass:

- `recomputes-after-reopen`: after the rebuild no object is invalid or in error, so the
  model survives save and reopen (the stored shape alone could hide a broken tree).
- `single-valid-solid`: one PartDesign Body with one solid that passes FreeCAD's full
  shape check, including self-intersections.
- `native-feature-tree`: sketch-driven PartDesign features, and no scripted shape
  wrappers or scripted base shape (`BaseFeature`).
- `named-dimension-drives-geometry`: changing a named constraint or a referenced named
  parameter by 10% leaves one clean solid and changes a bounding-box length by at
  least 1%.
- `independent-dimensions`: design intent. Two named dimensions each, changed by 10%,
  leave one clean solid and move the volume or a bounding-box length by at least 0.5%,
  and change the part in different ways (cosine below 0.9 between their relative
  changes of volume, X, Y and Z). One parameter that stretches the whole part, or
  several that stretch it along the same axis, fails.
- `mesh-fidelity`: IoU against the reference mesh at 0.1 mm resolution is at least 0.9.
- `no-missing-feature`: the largest connected piece of the reference that the model leaves
  out is at most 1.2% of the reference volume. IoU barely notices a missing branch or boss;
  this check does. Features thinner than about 3% of the part's size are below its
  resolution.
- `single-visible-object`: every visible object with geometry is the Body or its tip,
  as saved in the file (origin axes and planes are ignored). FreeCAD without its GUI
  does not hide sketches, so the agent must.
- `compact-model`: the solid has at most 10 times the faces of the reference
  solution (`REF_FACES` in `tests/test.sh`). A designer's model has about one face per
  surface of the part; stacked slices and faceted profiles add faces with every band
  and segment.

The verifier also logs the model's feature, sketch and face counts
(`complexity.json`).

## Relevant experience

Authored and reviewed by [Author], who builds CAD and simulation agents and reviewed
the checks against hands-on FreeCAD PartDesign modeling and the agent's
recorded failures.
