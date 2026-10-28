# Side features: arms, loops, ribs, bosses, tabs, hole patterns

Read this only after `/app/model.FCStd` holds a valid body (+ cavity). That save is your
safety net; each feature below is one more edit of the same build script and one more save.

1. **Measure (1 call, ~1 s):** `python3 /agent/skills/cad-toolkit/sides.py --axis <the survey's
   most regular axis>`. It finds the material outside the body and measures each feature on its
   own: its sketch plane and mid-plane offset, its thickness, and either `CURVED` or `STRAIGHT`.
   It prints nothing to build when the part has no side material: then you are done here.
2. **Build each feature** with the printed numbers, in the build script **after the body
   feature and before the cavity cut**, so the cut trims anything that reaches inside:
   - `CURVED arm/loop` (arc centre, centre-line radius R, span, section `circle d=` / ellipse /
     rect): `s = K.sketch_at(body, origin, xdir, ydir)` exactly as printed (origin = arc centre,
     so the sketch V_Axis is the arc's axis); draw the section at u = R, v = 0
     (`K.circle(s, R, 0, d)`); `K.revolve(body, s, span + 2 * overlap, symmetric=True)` with
     overlap in deg ~ `d / R * 180 / pi`, so both ends run into the wall.
   - `STRAIGHT (rib/boss/tab)` (outline corners): `sk = K.sketch(body, plane, offset)` as
     printed, `K.polygon(sk, corners)` with the corners that touch the body moved onto the body
     face and a little into it (the tool sees only material outside the body), then
     `K.pad(body, sk, thickness, symmetric=True)`.
   - **Holes** through a plate or wall (the survey's small `hole` loops on the axis across that
     wall): one sketch on that plane, one `K.circle` per hole, all bound to one Params diameter,
     `K.pocket(body, sk)` (through all), after the pads.
3. **One feature per run of the script:** add it, re-run, save with `K.finish`. Check that
   `volume` moved by about the feature's size (`volume model/mesh` closer to 1). If it failed or
   gave two solids, remove it again and re-save the previous model before trying a fix.
4. **Time:** do not start a new feature with less than about 60 s left on the [status] line;
   verify and report the last valid save instead.

```python
a = K.sketch_at(body, origin, xdir, ydir)  # any plane, local coords; V_Axis through origin
K.revolve(body, a, 240, symmetric=True)    # turns 120 deg each way about a's V_Axis
```
