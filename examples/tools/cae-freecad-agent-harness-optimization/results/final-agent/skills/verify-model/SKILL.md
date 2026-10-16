---
name: verify-model
description: Verify a saved FreeCAD model against the mesh after reopening it - one clean solid (check(True)), faces, visibility, volume, an IoU estimate, where the sections differ, and whether each named dimension moves the part in its own way. Use after every build, before reporting.
---
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Verify the model

```bash
cd /app && MODEL=/app/model.FCStd MESH=/app/reference.obj SLICES=z freecadcmd /agent/skills/verify-model/verify.py 2>&1 | grep -v '%)'
```

About 15-50 s (each named dimension is rebuilt and checked): run it once, at the end.
Every `m.save` in build-features already prints the IoU estimate and WHERE. It reopens the file (does not change it) and prints:

- invalid objects after recompute (must be `[]`), `solids` (must be 1), `check(True)`
  (must be `ok`: anything else is an invalid part, not a warning), `faces` (aim for
  tens: about one per real surface), other visible objects (must be `[]`);
- volume ratio model/mesh, both bounding boxes, and `IoU estimate` (target >= 0.9);
- `WHERE the model differs from the mesh`: up to three regions of >= 1% of the mesh volume,
  largest first, each `MISSING` (mesh material the model lacks) or `EXTRA` (model material
  where the mesh has none), with its world box and centre, the feature it comes from
  (`added by X`, `removed by X`, or no feature: a feature not built or one that stops short),
  and `IoU if fixed`: the estimate with that region's error removed. Fix the region with the
  largest gain first;
- for each named dimension (spreadsheet alias, or named sketch constraint without an
  expression): +10% gives one clean solid? and the relative change of volume, X, Y, Z;
  then the cosine between each pair. The part needs at least two named dimensions that
  each move it (>= 0.5%) and have cosine < 0.9 (they change the part in different ways,
  e.g. a height and a diameter, or a wall thickness and an arm length), and at least one
  must change a bounding-box length by >= 1% (printed after the pairs).

The last line `VERDICT ...` sums it up. Fix the largest problem first (one change per
run; build-features' `m.save` keeps the last valid model if a change breaks the part). Report
the verdict numbers of /app/model.FCStd, nothing the output does not show.
