---
name: cad-toolkit
description: Use for every mesh-to-FreeCAD task. Tested one-call tools to find the part's frame on a posed mesh (measure.py), survey its sections with shape fits, cavities and side features (sections.py all), build PartDesign sketches/features with named dimensions (sketchkit.py), measure a round body's revolve profile with its cavity (profile.py), verify a saved model (verify.py), look at it beside the mesh (look.py, an image you read), measure and build features off the body - arms, ribs, bosses, hole patterns - after the first save (SIDES.md, sides.py), plus the workflow that saves a valid model within the 5-minute limit.
---

# CAD toolkit: mesh -> parametric PartDesign model, headless FreeCAD 1.1

The run is stopped after **5 minutes**. A run without `/app/model.FCStd` scores zero, however
good its measurements. So: measure with the tools below (one call each), **save a first valid
model by about minute 2**, verify it, then improve it while time remains. Every save must
leave a valid model on disk.

All tools run with plain `python3` (they find FreeCAD themselves) and take seconds.
Write your build code to a file and run `python3 build.py` (or `freecadcmd build.py`).
Do not use `freecadcmd -c "..."` with multi-line code: it crashes ("Application unexpectedly
terminated") and the shell still reports exit code 0. Read the output for `Error`/`Traceback`.
The sketchkit card below is the whole API: do not read the tool sources, and do not write your
own renderer (look.py is the one renderer; it is for after the first save).

## Workflow (one pass, in this order)

1. **Measure + frame (1 call).** `python3 /agent/skills/cad-toolkit/measure.py /app/reference.obj`
   Meshes are posed: the world axes mean nothing. It prints volume, the frame kind
   (`round` = revolved about local z; `flat` = flat faces along local x/y/z; `pca` = free-form,
   z = normal of the largest flat face), the local bounding box, the distinct vertex levels per
   local axis, and for round parts the `(t, r)` rings: each `t` level with the radii found there.
   It writes `/app/frame.json`. Work in local coordinates from now on.
2. **Survey (1 call), then decide the features.** `python3 /agent/skills/cad-toolkit/sections.py all`
   cuts the part across each local axis and fits every loop: `circle d=`, `ellipse A x B (full
   axes)`, `rect A x B corner radius r` or `polygon k corners (u,v) ...` (the outline's corner
   points). Per axis it prints the main loop per level, the `hole` inside it with the `wall` to
   it, `other loop`s beside it, `change at` = the exact level where a hole or a loop starts or
   stops, and a summary; at the end the most regular axis. Decide from these numbers:
   - **Main body** = the most regular axis's main loop. Copy its fitted shape, not points:
     **round body** (frame `round`, or `circle`/`hole` loops on one centre; arm/handle allowed) ->
     `python3 /agent/skills/cad-toolkit/profile.py --write`: axis fitted, frame.json rewritten, and
     `PROFILE = [...]`, the measured half-section with its cavity and floor: copy it unrounded into
     `K.polygon(K.sketch(body,'XZ'), PROFILE)` + `K.revolve` (it prints its volume vs the mesh);
     `NOT ROUND` -> use the loop fits below;
     same shape and size at every level (`constant section`) -> one pad of that loop
     (`polygon` corners -> `K.polygon`, `ellipse` -> `K.ellipse`, `circle` -> `K.circle`);
     `changing section` -> `K.loft` through that shape at 2 levels (`linear: 2 sections, Ruled`)
     or 3-5 levels (`curved`), placed where the taper starts and stops (a constant part beyond
     it is a pad, not part of the loft). Sketch on the plane across that axis:
     axis z -> `'XY'` offset = level; axis x -> `'YZ'` offset = level; axis y -> `'XZ'` offset =
     **-level** (its normal is -y); the printed loop coords are then the sketch (u, v).
     A circle is never a rect, an ellipse never a polygon.
   - **Hollow** (`hole` inside the main loop; a round body's PROFILE already has it): a shell. Build
     the outer body solid, then cut the cavity with the same kind of feature from the hole fits:
     `pocket` of the hole loop (constant hole) or `K.loft(..., subtractive=True)` through hole
     shapes at the same levels, each hole size bound as `outer - 2 * Params.Wall` (Wall = the
     printed `wall`). Its extent is the `change at` levels: where the hole stops is the floor
     (floor = that level to the body's end); a hole that reaches an end is the opening: start the cut there.
   - **Side features** (`other loop`s beside the main loop, a main loop that turns into a polygon at
     a few levels, small `hole`s through a wall): note them now; build them in step 5.
   - Volume sanity check: the planned body and cavity should give about the mesh volume.
3. **Build body + cavity (1 script), run it, save it with `K.finish(doc)`** by about minute 2.
   If the cavity feature fails, save the body alone first, then add the cavity and save again.
   The save guard (the [status] line) checks every save and rolls a failing one back.
4. **Look once (1 call + read_file)** when the [status] line says the model is valid and there
   is time: `look.py`, then list the features in the mesh row that the model row lacks and name
   the first difference. See "Looking" below.
5. **Side features, holes and fixes, one at a time, only after step 3's save.** If the survey or
   the look showed any, read `/agent/skills/cad-toolkit/SIDES.md` (short) and follow it: one
   sides.py call, then add each feature to the same script, re-run, save. Every feature of the
   part is built; a model without one fails even at high IoU.
6. **Verify (1 call).** `python3 /agent/skills/cad-toolkit/verify.py` (defaults
   `/app/model.FCStd /app/reference.obj`): reopens, recomputes, checks one valid solid with
   `check(True)`, one visible object, sketches fully constrained, volume ratio, an IoU estimate
   (aim >= 0.9) and where material is missing/extra (local coords), and whether each named
   dimension changes the model. `sections.py z --model /app/model.FCStd` compares areas per level.
7. **Report** the verify numbers. Stop improving at about minute 4 and make sure the last saved
   model passed verify.

`sections.py z --n 9 --points 12` lists one axis in detail; `--levels a,b,c` picks levels.

## Looking: look.py renders what the numbers cannot name

`python3 /agent/skills/cad-toolkit/look.py` (~5 s) writes `/app/look.png`: top row the mesh
(blue, the target), bottom row your saved model (orange), in the local frame, five views (iso,
front, right, top, bottom); `read_file /app/look.png` shows it. It also prints both bounding
boxes and `volume model/mesh` (near 1). `--cut y --views front,iso` cuts both in half to show
inside (a model solid where the mesh is hollow is obvious). Never render view by view.

When to look (a look plus its fix takes about 100 s): not before the first valid save (it does
nothing then), once right after it (step 4), and at most once more after a fix when verify IoU is
still < 0.9. look.py refuses when too little time is left: then verify.py and report.

Compare the two rows column by column and name the FIRST difference:

| You see (model vs mesh) | Likely cause | Next build change |
| --- | --- | --- |
| a feature in the mesh row only (arm, hole, cavity, boss) | not modelled, or its feature failed | step 5: read SIDES.md and run sides.py; do not guess its outline |
| model filled where the mesh is open, or open on the other side | cavity missing or on the wrong end | add/flip the pocket or subtractive loft (offset/reverse) |
| a hole or gap through a wall the mesh does not have | cavity too big or too long | shrink the inner sections by the wall, stop the cut before the floor |
| same shape but turned, mirrored or shifted in a view | sketch on the wrong plane/side, pad reversed, wrong axis | change plane (`XY`/`XZ`/`YZ`), `reverse=True`, or the offset |
| wrong outline (square vs round/oval, straight vs tapered) | wrong profile type | use the survey's fit (circle/ellipse/rect/polygon) and its taper levels |
| facets/polygon where the mesh is smooth | profile drawn as a polygon of samples | use a circle/ellipse/few-point profile instead of many points |
| lumps, waves or creases on a smooth surface | loft through noisy or too many sections | fewer sections (3-5), sizes from loop extents, `Ruled=False` |
| a fragment or sliver of the part | a feature only partly built (partial revolve angle, short pad) | full 360 revolve, pad length from the measured extent |
| too thick / too thin wall or floor | wrong wall or floor value | re-measure it with sections.py and change that one parameter |

Make ONE change for the difference you named, rebuild, save, then verify.py: the numbers decide
whether it is fixed, never the picture alone. If the rows look the same and IoU is still low, use
the numbers (missing/extra material location, `sections.py --model`), not another look.

## sketchkit.py: building blocks (tested headless in 1.1.3)

```python
import sys; sys.path.insert(0, '/agent/skills/cad-toolkit')
import sketchkit as K
doc, body, P = K.new_model('Model', frame='/app/frame.json')  # Body posed in the part frame
K.param(P, 'OuterDiameter', 52.0)          # alias = a word (not 'H', 'D1', 'mm')
sk = K.sketch(body, 'XZ')                  # 'XY' (u,v)=(x,y) | 'XZ' (x,z) | 'YZ' (y,z)
c = K.polygon(sk, [(r0,t0), (r1,t1), ...]) # closed, fully constrained: c['x3'], c['y3'] = vertex 3
K.bind(sk, c['x1'], 'Params.OuterDiameter / 2', 'OuterRadius')   # named, driven dimension
print(K.dof(sk))                           # (0, True) = solved and fully constrained
K.revolve(body, sk)                        # about the sketch V_Axis (= local z on 'XZ')
s2 = K.sketch(body, 'XY', offset='Params.Height')   # offset along the plane normal (number or expr)
h = K.circle(s2, cu, cv, d); K.bind(s2, h['d'], 'Params.HoleDiameter', 'HoleDiameter')
K.pocket(body, s2)                         # through all; K.pocket(body, s2, 'Params.Depth')
K.pad(body, sk, 'Params.Thickness', symmetric=False, reverse=False)
e = K.ellipse(sk, cu, cv, a, b, angle=0)   # semi-axes along u, v (turned by angle deg); e['a'], e['b'] = full-axis constraints
K.loft(body, [sk1, sk2, sk3])              # first sketch -> Profile, rest -> Sections
K.loft(body, [i1, i2, i3], subtractive=True)
K.finish(doc, '/app/model.FCStd')          # recompute, check(True), only Body visible, save
```

- The sketch planes are the Body's local planes; the Body carries the measured pose, so
  every number is a local measurement. `XZ` has normal -y: a pad on `XZ` goes toward -y
  unless `reverse=True`.
- Draw revolve profiles on one side of the axis (u >= 0), closed, not crossing the axis.
- Features must touch or overlap the existing solid, or the Body gets two solids.
- Bind the dimensions a designer would change (diameters, heights, wall thickness, hole size)
  and reuse an alias where the same size recurs, e.g. `'Params.Width - Params.Wall'`. Leave
  other vertex coordinates as plain numbers: the sketch stays fully constrained.

## FreeCAD API facts (when writing your own sketch code)

- Radius/Diameter take three arguments: `Sketcher.Constraint('Diameter', geo, value)`.
  The four-argument form failed or crashed FreeCAD in earlier runs.
- Coordinates of a point: `Sketcher.Constraint('DistanceX', -1, 1, geo, pos, value)` (also
  `DistanceY`; signed). Point pos: 1 start, 2 end, 3 centre. `-1` is the sketch origin/axis.
- Loft: `loft.Profile = first_sketch`, `loft.Sections = [others]`. Without Profile the
  loft fails with "Failed to get shape of Profile".
- Named dimension: `sk.renameConstraint(i, 'Name')`, `sk.setExpression(f'Constraints[{i}]', 'Params.Name')`;
  feature lengths: `pad.setExpression('Length', 'Params.Height')`.
- `PartDesign` has no Python feature functions: create features with
  `body.newObject('PartDesign::Pad', 'Pad')` etc. Do not use `Part.makeLoft`/booleans for
  the deliverable: it must be a sketch-based PartDesign tree.
