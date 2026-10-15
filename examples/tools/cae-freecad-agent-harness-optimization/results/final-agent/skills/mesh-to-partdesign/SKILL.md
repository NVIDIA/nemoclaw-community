---
name: mesh-to-partdesign
description: Turn a closed triangle mesh (OBJ/STL) into a saved, verified, sketch-driven PartDesign model in one command. Use first for any mesh-to-CAD reconstruction, before writing your own FreeCAD code.
---
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Mesh to PartDesign

The run has 5 minutes and every model turn costs seconds. Do not explore the
FreeCAD API by trial and error: this helper is tested on FreeCAD 1.1.3 headless.

## 1. Build and verify in one command (about 10-25 s)

```bash
cd /app && MESH=/app/reference.obj OUT=/app/model.FCStd AXIS=z \
  timeout 120 freecadcmd /agent/skills/mesh-to-partdesign/mesh2pd.py 2>&1 | grep -v '%)'
```

It cuts the mesh along `AXIS`, splits the axis into segments where the cross-section
keeps the same loops, and builds one ruled AdditiveLoft per segment: every section sketch
holds all of the segment's loops (outer walls and holes, one closed B-spline each), so the
caps are faces with holes and nothing is cut. Sections are picked adaptively (fewest that
stay within tolerance of the mesh) and cut right next to each change of loops. Where a
loop splits or merges (a branch leaving the main body), the branches start just inside the
merged loop, so segments meet in flat steps, never as intersecting curved walls.
A loop gives one side face per loft span, so the model has tens of faces, not one per
slice.
All section heights are fractions of one named dimension, `Params.Length` (spreadsheet
alias). It hides the sketches, saves, reopens, recomputes, and prints:

- `reopen:` invalid objects (must be `[]`), solids (must be 1), `check(True)` (must be
  `ok`), and `faces` (aim for tens, not hundreds);
- volume ratio model/mesh and the bounding box;
- `IoU estimate`: volume overlap of model and mesh by ray casting (independent of the
  grader, target >= 0.9);
- whether changing `Params.Length` by 10% still gives one solid and moves the geometry.

## 2. Improve only if a number is off

- Write every retry to another file (`OUT=/app/try.FCStd`) and copy it over
  `/app/model.FCStd` only if its numbers are better. Never overwrite a valid model with
  an unchecked one: the saved file is what is scored.
- `check(True)` FAILED (any BOP error, GeomAbs_C0 included) is an invalid part, not a
  warning: try another `AXIS` (x or y) into a try file.
- Already one solid, `check(True) ok` and IoU estimate >= 0.9: you are done; report.
- IoU estimate below 0.9: `TOL=` half the default (closer sections) or another `AXIS`.
- Stop retrying by 3 minutes into the run and report.

## 3. Report

Report the printed numbers (solids, check, volume ratio, IoU estimate, the named
dimension test) for the file you saved. Do not claim anything the output does not show.

## FreeCAD headless notes

- Run scripts as files (`freecadcmd script.py`); inline `freecadcmd -c "..."` with a
  multi-line program often dies with "Application unexpectedly terminated".
- A Python error in a script file still exits 0: read the output for
  `Exception while processing file`.
- Filter the progress noise with `| grep -v '%)'`.
- `MeshPoint` and `Facet` are not subscriptable: use `p.x`, `f.PointIndices`.
