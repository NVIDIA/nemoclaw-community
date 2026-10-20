---
name: measure-mesh
description: Measure a triangle mesh before modelling it - size, volume, wall thickness, principal axes, the loops of its cross-sections along each axis (outer or hole, centre, widths, roundness, drift), the centre lines of branches (handles, arms), and how far a straight feature reaches. Use first, on any mesh-to-CAD task.
---
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Measure the mesh

Each command takes a few seconds. All coordinates printed are WORLD coordinates: pass them
to the build-features blocks as they are.

## 1. Overview, sections along axes, branches and the part's STRUCTURE (one command)

```bash
cd /app && MESH=/app/reference.obj AXIS=all N=12 freecadcmd /agent/skills/measure-mesh/measure.py 2>&1 | grep -v '%)'
```

With `AXIS=all` it also runs branch.py and ends with `STRUCTURE`: the main axis, where the
body starts and ends (its STEP when a branch continues beyond it), each cavity's floor and
extent, and the branches. Read it before you plan; build from it.

measure.py: `AXIS` = `x`, `y`, `z`, `all` or a direction `"nx,ny,nz"`; `N` levels (`N=30` on
one axis for detail). Per level, every loop:

- `OUT` (outer boundary) or `HOLE` (cavity/opening inside an OUT loop);
- `c=(x,y,z)` centre, `hw a x b` half-widths (full widths = 2 x hw), `ang` direction of the
  first one, `dev` distance from that ellipse (~0: an ellipse, a circle if a ~ b; large:
  free-form or merged with a branch), `A` area;
- `drift (dx,dy,dz)`: centre motion per unit of height. A loop of constant `A` with constant
  drift is a straight feature along `axis + drift` (drift (+2.1,0,0) along z = direction (2.1,0,1)).

branch.py: each branch that stands apart from the body (handle, arm, tube, boss), with its
section size and its centre line as ordered world points. `CURVED`: its `PATH` is the path for
a `tube`, as printed: the centre points where it is free of the body plus one point at each end
carried along the branch's own direction into the body wall. `STRAIGHT`: its direction and the
`branch_loft` that builds it from its own sections. What it finds is kept in `/app/.branches.json`:
build-features' `m.save` checks that every measured branch is in the model.

How to read it:

- Mean wall `2V/A` far below the part size: thin-walled; an `OUT` loop with a `HOLE` of the
  same shape inside is a hollow body (wall = difference of half-widths).
- Where a branch joins the body, the body's `OUT` loop swallows it (`hw`, `dev`, centre
  jump): take the body from levels where it is alone, the branch from its own loops.
- Where a `HOLE` first appears is a cavity floor (a cut starts there, never lower: below it
  the cut goes through the floor); where an `OUT` loop ends, a feature's top.
- HOLE loops that show only in cuts along another axis, beside a branch, are the opening
  between a handle and the body, not holes to cut.
- `HOLE series`: each cavity or pocket along that axis, with where it starts and a point in
  it (for `pick=`); each is its own cut.
- `STEP at z=...`: the body ends there and only a branch continues beyond. The body's sections
  stop at that level (its top section there); never loft the body on through the branch. A body
  height parameter is that level, not the bounding-box height.
- Main axis: the `MAIN AXIS hint` line (the axis whose cuts show the cavity's HOLE loops;
  cuts along other axes show an open cavity as one U-shaped OUT loop with large dev, which
  is not an ellipse). The part need not be aligned with x, y or z (principal axes as `AXIS`).

## 2. How far a straight feature reaches

```bash
cd /app && MESH=/app/reference.obj ORIGIN=x,y,z DIR=dx,dy,dz freecadcmd /agent/skills/measure-mesh/extent.py 2>&1 | grep -v '%)'
```

From a point on the feature's axis, along its direction: `ahead` and `behind` distances to
its ends (behind runs on into the body where it joins one).

## 3. Exact outlines

Free-form outlines need no export: `m.section_loft(...)` and `m.mesh_section(...)` in build-features cut the mesh and
draws the loop in place.
