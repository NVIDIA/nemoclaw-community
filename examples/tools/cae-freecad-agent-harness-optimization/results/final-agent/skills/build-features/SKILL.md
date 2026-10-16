---
name: build-features
description: Write your own FreeCAD build script from feature-level building blocks in WORLD coordinates (cadkit.py - sketches from measured ellipses, circles, polygons or mesh cuts; a loft through the mesh's own sections of a region; loft, pad, pipe, revolve, hole; named dimensions in a spreadsheet; a save that keeps the last valid model). Read before writing FreeCAD code.
---
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Build the model feature by feature

You decide the features, their positions and the named dimensions; `cadkit.py` does the
FreeCAD API. Every point is a WORLD point (x, y, z): the numbers measure-mesh prints, as
they are. Any coordinate or size can be an expression string over named dimensions
(`'Height'`, `'Height + 1'`, `'OuterWidth - 2*Wall'`): that is what makes it drive the model.

```python
import sys; sys.path.insert(0, '/agent/skills/build-features'); from cadkit import *
m = Model()
m.param('Height', 13.4)                                   # named dimension (a word, not 'D1')
# sketches (each returns a sketch); normal defaults to (0, 0, 1)
s = m.ellipse(name, center, w, h, angle=0, normal=(0,0,1))  # w, h = full widths (2 x hw), w along +x rotated by angle
s = m.circle(name, center, d, normal=(0,0,1))
s = m.polygon(name, [p1, p2, ...])                         # coplanar world points, sharp corners
s = m.mesh_section(name, origin, normal=(0,0,1), kind='OUT'|'HOLE', pick='largest'|'smallest'|(x,y,z),
                   level=None, smooth=True)                # the mesh's own loop cut at that plane
# features (each prints: solids, check, faces, volume, exact bbox)
m.section_loft(name, start, end, n=8, normal=(0,0,1), kind='OUT'|'HOLE', pick='largest'|(x,y,z),
               bottom=None, top=None, along=None, cut=False)  # ruled loft through the mesh's own loops
                                                           # at n levels start..end along normal (world coordinate)
m.loft(name, [s0, s1, ...], cut=False)                     # ruled loft through sketches you made, in order
m.pad(name, s, length, length2=0, direction=None, cut=False)  # along the sketch normal (+ back by length2);
                                                           # direction=(dx,dy,dz): slanted, lengths along the normal
m.tube(name, [p0, p1, ...], d, h=None, cut=False)          # circle d (or ellipse d x h) swept along a smooth path
m.revolve(name, s, axis_point, axis_dir, angle=360, cut=False)  # s = polygon on one side of the axis, in its plane
m.hole(name, center, normal, d, depth=None)                # round hole into the face, through all if no depth
m.save('/app/model.FCStd')                                 # drops a feature that broke the part, hides helpers,
                                                           # saves, reopens; prints WHERE and SAVED ... IoU estimate
```

`start`/`end` of `section_loft` may be expressions (`end='Height'`): the end section is then
driven by that parameter. An end past the mesh (`end='Height + 1'` for a cut through an open
top) uses the nearest loop inside, moved there.

Mesh outlines are fixed shapes; drive them by where they sit: `top=`/`bottom=` of
`section_loft` (or `level=` of `mesh_section`) move that end section along the normal to the
expression's value (body `top='Height'`; cavity `bottom='Floor'`, `top='Height + 1'` to open
the rim; a slanted branch `top='X0 + BranchLength', along=direction`).

## Choosing features from measure-mesh

| The measurements show | Feature |
| --- | --- |
| Ellipse/circle loops (`dev` ~0) whose size changes along an axis | `loft` of `ellipse`/`circle` sketches at the measured levels |
| A free-form outline (large `dev`) that changes along an axis | `section_loft` of OUT loops, n 8-12, from the bottom end to the top (the `STEP` level if a branch continues) |
| The same loop all along (prismatic) | `pad` of one sketch (`polygon` for straight edges, `mesh_section` otherwise) |
| A straight branch (branch.py: STRAIGHT) | the `section_loft` branch.py prints (its own sections, along its direction) |
| A curved branch (branch.py: CURVED) | `tube` through branch.py's points as printed, plus one point at each end about one diameter inside the body wall |
| HOLE loops (cavity) | `section_loft(..., kind='HOLE', cut=True)` from the floor to the top, or a `loft(cut=True)` of HOLE ellipses; a second, smaller HOLE series: its own cut with `pick=` a point in it |
| A round hole or bore | `hole`, or `pad(..., cut=True)` |
| Round about one axis (circles on one centre) | `revolve` of the half profile, or a `loft` of circles |

- First and last sections at the true ends (`bottom end` / `top end` / `STEP` levels, the
  floor where a HOLE starts), not at a mid level.
- The body ends at measure.py's `STEP` level when a branch continues beyond it. Build the body only from levels where it is alone (where a branch merges, the loop jumps:
  skip those levels); the branch is its own feature.
- Order: body, then branches, then cuts last (a cavity cut also clears branch material
  poking into it). A cut's sketches hold only the HOLE loops; extend it 1 mm past an open face.
- Sections across the MAIN AXIS that measure.py names (where the cavity's HOLE loops are).
- Every section of one loft: same kind of sketch (all ellipses, or all mesh outlines).
- More sections follow the mesh more closely but add faces; n = 8-12 is usually enough
  (section_loft adds levels by itself where the loop changes fast next to an end).
- A cut starts at its cavity's floor (STRUCTURE / HOLE series start): `bottom='Floor'` with
  Floor = that level. Floor = 0 or the part's bottom cuts through the floor.

## Named dimensions with design intent

2-4 parameters a designer would change, each driving its own feature: an overall height
(top section `z`), a floor thickness (first cavity level), a wall (`'W - 2*Wall'` sizes), a
branch diameter (`tube` d), a branch length (`pad` length), a hole size. At least two must
change the part in different ways and one must move the bounding box (verify-model checks).
A number you pass is frozen; only an expression string is driven. Easy, robust choices:
`top=`/`bottom=` on body and cavity (Height, Floor: both change only the volume, so add one
more), a branch length (`top=` of its section_loft, or a `pad` length) or a `tube` diameter
(these move the bounding box), `'... - 2*Wall'` on ellipse cavity sizes.

## Work incrementally (the run is 5 minutes; every tool result shows the clock)

1. `/app/build.py` with the main body feature (and its cavity cut) and two parameters; run it
   (`cd /app && timeout 100 freecadcmd /app/build.py 2>&1 | grep -v '%)'`): it saves
   `/app/model.FCStd`. Now you have a valid model.
2. Read the output from the end:
   - `SAVED ... IoU estimate ... features [...]`: what /app/model.FCStd now holds (or `NOT SAVED`:
     the previous, better model stays; your change made it worse). Every feature of your plan
     must be in that list: a missing one (DROPPED, or never built) is the first thing to fix,
     even when the IoU estimate looks good (a small handle costs little IoU but is part of the part).
   - `DIMENSIONS` (once the IoU estimate is >= 0.85): how each named dimension moves the part;
     you need two that move it differently and one that moves the bounding box.
   - `WHERE`: the regions where the model is wrong, largest first: `MISSING` / `EXTRA`, how
     much, where (world box), which feature (`added by Body001` = your 'Body' feature) and the
     IoU if fixed. Typical causes: EXTRA added by the body above or beyond where the mesh ends
     = its end level is wrong (a STEP, not the bounding box); MISSING removed by a cut = the
     cut starts too low or is too big (a floor cut through); MISSING with no feature = a
     branch or feature not built yet, or one that stops short.
   - `NOTE` lines (an end moved where the mesh has no loop) and `-> X broke the part`:
     m.save drops the broken feature (`DROPPED`) and saves the rest; fix that feature.
3. Fix the region with the largest `IoU if fixed`, or add the next feature: ONE change per
   run. A model replaces /app/model.FCStd only if it is one valid solid and its IoU estimate
   is not lower, so the best valid model always stays.
4. Done when every planned feature is in the saved model, the IoU estimate is >= 0.92, no
   region is over 3% and DIMENSIONS is satisfied: report (verify-model is optional: it repeats
   these checks on the reopened file, 15-50 s).

Keep ONE `m.save(...)` as the last line of build.py; each run rebuilds the whole model
(about 5-15 s per feature).

Worked example on a made-up part: `/agent/skills/build-features/example.py`.

## Gotchas

- A Python error still exits 0: look for `Exception while processing file` in the output.
- Do not mix up a part's local frame with world: cadkit never needs one. Pass world points.
- Names: letters, digits and `_`, unique per object.
