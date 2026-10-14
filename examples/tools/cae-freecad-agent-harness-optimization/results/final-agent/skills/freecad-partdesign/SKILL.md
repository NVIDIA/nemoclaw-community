---
name: freecad-partdesign
description: Verified FreeCAD 1.1 Python recipes for measuring a reference mesh and building a parametric PartDesign body (spreadsheet parameters, sketches, Revolution, Pad, Pocket, Groove, AdditivePipe), editing it and checking it. Use for any FreeCAD modelling or mesh-reconstruction task.
---

# FreeCAD PartDesign recipes (FreeCAD 1.1, verified)

Every snippet below was run in FreeCAD 1.1 and works as written. Copy them and
change only the numbers and names. Do not guess other API names: most failures in
past runs came from invented calls. If something you need is not here, check it
with `dir(obj)` once, in a call that creates nothing.

## API facts that past runs got wrong

| Wrong (does not exist) | Right |
| --- | --- |
| `FreeCAD.createDocument(n)`, `FreeCAD.deleteDocument(n)` | `FreeCAD.newDocument(n)`, `FreeCAD.closeDocument(n)`; existing: `FreeCAD.listDocuments()` (dict) |
| `FreeCAD.activeDocument(n)` (takes no argument); `FreeCAD.activeDocument()` can be another document | `doc = FreeCAD.getDocument(n)` with the task's document name; `body = doc.getObject('Body')`; `ss = doc.getObject('Params')` |
| `mesh.getBoundingBox()`, `mesh.boundBox`, `bb[0]`, `bb.Min` | `bb = mesh.BoundBox`; `bb.XMin bb.XMax bb.YMin ... bb.ZMax bb.XLength ...` |
| `mesh.getNumberOfFacets()`, `mesh.points` | `mesh.CountFacets`, `mesh.CountPoints`, `mesh.Points` (list of points with `.x .y .z`), `mesh.Volume` |
| `'PartDesign::Revolve'`, `'PartDesign::Shaft'` | `'PartDesign::Revolution'` (additive), `'PartDesign::Groove'` (subtractive) |
| `'Sketcher::Sketch'`, `doc.addObject` for features | `body.newObject('Sketcher::SketchObject', name)`, `body.newObject('PartDesign::Pad', name)` |
| `sk.Support`, `MapMode='Sandbox'/'Part'` | `sk.AttachmentSupport = [(plane, '')]`, `sk.MapMode = 'FlatFace'` |
| `face.revolve(base, axis_as_int)` / `Part.revolve` | Do not build Part shapes; use PartDesign features (below). |
| `pad.Midplane = True` (deprecated) | `pad.SideType = 'Symmetric'` |
| `shape.isSolid()` | `len(shape.Solids) == 1` and `shape.isValid()` |

Never pass a Mesh to Part (`Part.Shape(mesh)` crashes FreeCAD). Never create test or
probe objects in the task's document; deleting them later leaves dangling
references ("Cannot access attribute 'Name' of deleted object").

## 1. Measure the mesh (one call)

```python
import Mesh, numpy as np
from FreeCAD import Vector as V
m = Mesh.Mesh(MESH_PATH)
bb = m.BoundBox
P = np.array([[p.x, p.y, p.z] for p in m.Points])        # (N, 3) array
print('bbox', bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)
print('volume', m.Volume, 'solid', m.isSolid(), 'points', P.shape)
```

Cross-section loops at several heights (here along Z; use another normal if the
part's axis is different). Each loop is a list of points. A loop's centre and
mean radius tell you the round parts; a loop far from the axis is a side feature.

```python
zs = np.linspace(bb.ZMin, bb.ZMax, 12)[1:-1]
planes = [(V(0, 0, float(z)), V(0, 0, 1)) for z in zs]
for z, loops in zip(zs, m.crossSections(planes, 1e-4)):
    out = []
    for pl in loops:
        a = np.array([[p.x, p.y] for p in pl])
        c = a.mean(axis=0); r = np.linalg.norm(a - c, axis=1)
        out.append((round(c[0], 2), round(c[1], 2), round(r.mean(), 2), round(r.min(), 2), round(r.max(), 2)))
    print('z=%.2f' % z, out)    # (centre x, centre y, mean r, min r, max r) per loop
```

Two concentric loops at one height mean an outer and an inner wall. Read the
profile you will draw (radius against height) from these numbers.

## 2. Document, parameters, body

```python
import FreeCAD, Part, Sketcher
from FreeCAD import Vector as V
NAME = 'DocName'
print('open documents:', list(FreeCAD.listDocuments()))
doc = FreeCAD.newDocument(NAME)     # only if NAME was not in that list
ss = doc.addObject('Spreadsheet::Sheet', 'Params')
for row, (alias, val) in enumerate([('height', 10), ('radius', 4), ('wall', 0.5)], start=1):
    ss.set('A%d' % row, alias); ss.set('B%d' % row, str(val)); ss.setAlias('B%d' % row, alias)
doc.recompute()
body = doc.addObject('PartDesign::Body', 'Body')
xz = [f for f in body.Origin.OriginFeatures if f.Role == 'XZ_Plane'][0]
# Roles available: X_Axis Y_Axis Z_Axis XY_Plane XZ_Plane YZ_Plane
```

Variables you define stay available in later execute_code calls of the same
session, but if a name is undefined, get the objects back by name:
`doc = FreeCAD.getDocument(NAME); body = doc.getObject('Body'); ss = doc.getObject('Params')`.
If an error message says what a function accepts (for example "takes exactly 0
arguments"), change that call; do not resend it.

On the XZ plane, sketch x is global X and sketch y is global Z, so a profile drawn
there and revolved about the sketch's vertical axis (`V_Axis`) turns about global Z.

## 3. Revolved profile with named, driven dimensions

A closed polygon of line segments in (radius, height). The example is a wall with a
floor, open at the top; replace the points with your measured profile (keep it
closed and on one side of the axis, x >= 0).

```python
sk = body.newObject('Sketcher::SketchObject', 'ProfileSketch')
sk.AttachmentSupport = [(xz, '')]; sk.MapMode = 'FlatFace'
R, H, W = 4.0, 10.0, 0.5
poly = [V(0,0,0), V(R,0,0), V(R,H,0), V(R-W,H,0), V(R-W,W,0), V(0,W,0)]
n = len(poly)
for i in range(n):
    sk.addGeometry(Part.LineSegment(poly[i], poly[(i+1) % n]), False)
for i in range(n):
    sk.addConstraint(Sketcher.Constraint('Coincident', i, 2, (i+1) % n, 1))
for i in range(n):   # only for segments that really are horizontal or vertical
    d = poly[(i+1) % n] - poly[i]
    if abs(d.y) < 1e-9: sk.addConstraint(Sketcher.Constraint('Horizontal', i))
    elif abs(d.x) < 1e-9: sk.addConstraint(Sketcher.Constraint('Vertical', i))
sk.addConstraint(Sketcher.Constraint('Coincident', 0, 1, -1, 1))   # first point at origin
named = {'Height': sk.addConstraint(Sketcher.Constraint('DistanceY', 1, 1, 1, 2, H)),
         'Radius': sk.addConstraint(Sketcher.Constraint('DistanceX', 0, 1, 0, 2, R)),
         'Wall':   sk.addConstraint(Sketcher.Constraint('DistanceX', 3, 2, 2, 1, W))}
for nm, idx in named.items():
    sk.renameConstraint(idx, nm)
sk.setExpression('Constraints.Height', 'Params.height')
sk.setExpression('Constraints.Radius', 'Params.radius')
sk.setExpression('Constraints.Wall', 'Params.wall')
rev = body.newObject('PartDesign::Revolution', 'Revolution')
rev.Profile = sk; rev.ReferenceAxis = (sk, ['V_Axis']); rev.Angle = 360
doc.recompute()
print(rev.isValid(), body.Shape.isValid(), len(body.Shape.Solids), body.Shape.Volume, body.Shape.BoundBox)
```

`DistanceX`/`DistanceY` take (geo, point, geo, point, value); point 1 is a segment's
start, 2 its end, and geo -1 point 1 is the sketch origin. A sloped side is fine:
add only the constraints that hold.

## 4. More features on the same body

Pad a closed sketch symmetrically about its plane (two nested circles give a ring):

```python
sk2 = body.newObject('Sketcher::SketchObject', 'LugSketch')
sk2.AttachmentSupport = [(xz, '')]; sk2.MapMode = 'FlatFace'
sk2.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 2.0), False)
sk2.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 1.4), False)
pad = body.newObject('PartDesign::Pad', 'Lug')
pad.Profile = sk2; pad.Length = 1.0; pad.SideType = 'Symmetric'
doc.recompute()
```

Pocket (cut) through everything: `pk = body.newObject('PartDesign::Pocket', 'Cut');
pk.Profile = sk3; pk.Type = 'ThroughAll'; pk.SideType = 'Symmetric'`.

Groove (subtractive revolution): same as Revolution with `'PartDesign::Groove'`,
`Profile`, `ReferenceAxis = (sk4, ['V_Axis'])`, `Angle = 360`.

Sweep a round section along a curved path (AdditivePipe). The path is an arc in the
XZ sketch; the section sketch is attached normal to the path at its start. Make both
path ends sink into the existing solid so the result stays one solid.

```python
import math
path = body.newObject('Sketcher::SketchObject', 'PathSketch')
path.AttachmentSupport = [(xz, '')]; path.MapMode = 'FlatFace'
path.addGeometry(Part.ArcOfCircle(Part.Circle(V(3.5, 5, 0), V(0, 0, 1), 3.0), -math.pi/2, math.pi/2), False)
doc.recompute()
prof = body.newObject('Sketcher::SketchObject', 'PipeProfile')
prof.AttachmentSupport = [(path, 'Edge1')]; prof.MapMode = 'NormalToEdge'; prof.MapPathParameter = 0.0
prof.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 0.6), False)
pipe = body.newObject('PartDesign::AdditivePipe', 'Sweep')
pipe.Profile = prof; pipe.Spine = (path, ['Edge1'])
doc.recompute()
```

After every feature, print `feature.isValid()`, `len(body.Shape.Solids)` and
`body.Shape.BoundBox`. If a feature is invalid, fix that feature's numbers; do not
delete and rebuild the body.

## 5. Prove a named dimension drives the model

```python
v0 = body.Shape.Volume
ss.set('height', '12'); doc.recompute()
print('edited', v0, '->', body.Shape.Volume, body.Shape.isValid())
ss.set('height', '10'); doc.recompute()      # restore the measured value
```

## 6. Compare with the mesh (your own measurement)

```python
s = body.Shape
print('volume ratio', s.Volume / m.Volume)
print('bbox model', s.BoundBox, 'mesh', m.BoundBox)
for z in zs:
    wires = s.slice(V(0, 0, 1), float(z))
    print('z=%.2f' % z, [round(w.BoundBox.XLength / 2, 2) for w in wires])
```

Compare these with the mesh loops from step 1 and adjust the parameters in the
spreadsheet, not by rebuilding.

## 7. Final checks

```python
for o in doc.Objects:
    if o.TypeId.startswith(('Sketcher::', 'Spreadsheet::')):
        o.Visibility = False
doc.recompute()
print([o.Name for o in doc.Objects if o.Visibility and o.TypeId.startswith('PartDesign::')])
```

Leave the document open. The finished model is the Body.
