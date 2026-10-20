# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Verify a saved model the way a designer would receive it: reopen the file, recompute,
# check the solid, compare it with the mesh, and test every named dimension.
#
#   MODEL=/app/model.FCStd MESH=/app/reference.obj freecadcmd verify.py 2>&1 | grep -v '%)'
#
# Prints: invalid objects after reopen, solids, check(True), faces, visible objects, volume
# ratio, an IoU estimate (ray casting, independent of any grader), WHERE model and mesh
# differ (regions of missing / extra material and the feature each comes from), and for each named
# dimension (spreadsheet alias, or named sketch constraint without an expression) what
# a +10% change does: still one clean solid? relative change of volume, X, Y, Z. Then the
# cosine between every pair of those responses: two dimensions are independent when
# each moves the part (>= 0.5%) and their cosine is below 0.9. The file is not modified.
import itertools
import math
import os

import FreeCAD as App
import Mesh
import numpy as np

App.Console.SetStatus('Console', 'Log', False)
App.Console.SetStatus('Console', 'Msg', False)
MODEL = os.environ.get('MODEL', '/app/model.FCStd')
MESH = os.environ.get('MESH', '/app/reference.obj')
def solid_of(doc):
    bodies = [o for o in doc.Objects if o.TypeId == 'PartDesign::Body']
    return bodies[0] if bodies else None


def clean(shape):
    if shape.isNull() or len(shape.Solids) != 1:
        return False
    try:
        shape.check(True)
        return True
    except Exception:  # noqa: BLE001
        return False


def resp(s0, s1):
    b0, b1 = s0.optimalBoundingBox(), s1.optimalBoundingBox()
    return [(s1.Volume - s0.Volume) / s0.Volume, (b1.XLength - b0.XLength) / b0.XLength,
            (b1.YLength - b0.YLength) / b0.YLength, (b1.ZLength - b0.ZLength) / b0.ZLength]


doc = App.openDocument(MODEL)
doc.recompute()
bad = [o.Name for o in doc.Objects if not o.isValid()]
body = solid_of(doc)
shp = body.Shape.copy() if body else None
print(f'\nreopen+recompute: invalid objects {bad}')
if shp is None or shp.isNull():
    print('VERDICT no body / empty shape')
    raise SystemExit
ok = clean(shp)
vis = [o.Name for o in doc.Objects if getattr(o, 'Visibility', False) and o.TypeId not in
       ('App::Origin', 'App::Line', 'App::Plane', 'App::Point', 'Spreadsheet::Sheet')
       and not (body and o in (body, body.Tip))]
print(f'solids {len(shp.Solids)}  check(True) {"ok" if ok else "FAILED"}  faces {len(shp.Faces)}  '
      f'features {sum(1 for o in body.Group if o.TypeId.startswith("PartDesign::"))}  '
      f'body visible {body.Visibility}  other visible objects {vis} (must be [])')
mesh = Mesh.Mesh(MESH)
print(f'volume model {shp.Volume:.5g} mesh {mesh.Volume:.5g} ratio {shp.Volume / mesh.Volume:.3f}')
mb, sb = mesh.BoundBox, shp.optimalBoundingBox()
print(f'bbox model x {sb.XMin:.2f}..{sb.XMax:.2f} y {sb.YMin:.2f}..{sb.YMax:.2f} z {sb.ZMin:.2f}..{sb.ZMax:.2f}')
print(f'bbox mesh  x {mb.XMin:.2f}..{mb.XMax:.2f} y {mb.YMin:.2f}..{mb.YMax:.2f} z {mb.ZMin:.2f}..{mb.ZMax:.2f}')
ta = np.array([[list(p) for p in f.Points] for f in mesh.Facets])
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import where
iou = where.report(ta, shp, where.features_of(body), mesh.Volume)

# named dimensions
drivers = []
for o in doc.Objects:
    if o.TypeId == 'Spreadsheet::Sheet':
        for cell in o.getUsedCells():
            al = o.getAlias(cell)
            if al:
                drivers.append(('sheet', o, al))
    if o.TypeId == 'Sketcher::SketchObject':
        exprs = {e[0] for e in o.ExpressionEngine}
        for i, c in enumerate(o.Constraints):
            if c.Name and c.Driving and c.Type in ('Distance', 'DistanceX', 'DistanceY', 'Radius',
                                                   'Diameter', 'Angle') \
                    and f'Constraints.{c.Name}' not in exprs and f'.Constraints.{c.Name}' not in exprs:
                drivers.append(('sk', o, c.Name))
R = {}
for kind, o, nm in drivers:
    label = f'{o.Name}.{nm}'
    try:
        if kind == 'sheet':
            v0 = float(o.get(nm))
            o.set(nm, f'{v0:.6g}')
            o.touch()
            doc.recompute()
            base = body.Shape.copy()
            o.set(nm, f'{v0 * 1.1:.6g}')
        else:
            q0 = o.getDatum(nm)
            v0 = q0.Value
            o.touch()
            doc.recompute()
            base = body.Shape.copy()
            o.setDatum(nm, q0 * 1.1)
        doc.recompute()
        s1 = body.Shape
        good = clean(s1) and not [x.Name for x in doc.Objects if not x.isValid()]
        r = resp(base, s1) if good else None
    except Exception as e:  # noqa: BLE001
        good, r = False, None
        print(f'  {label}: error {str(e)[:120]}')
    finally:
        try:
            if kind == 'sheet':
                o.set(nm, f'{v0:.6g}')
            else:
                o.setDatum(nm, q0)
            doc.recompute()
        except Exception:  # noqa: BLE001
            pass
    moves = r is not None and max(abs(x) for x in r) >= 0.005
    print(f'  dimension {label} = {v0:.4g}: +10% -> one clean solid {good}'
          + (f', dV {r[0]:+.3f} dX {r[1]:+.3f} dY {r[2]:+.3f} dZ {r[3]:+.3f}, moves the part {moves}' if r else ''))
    if moves:
        R[label] = r
pairs = []
for a, b in itertools.combinations(R, 2):
    va, vb = np.array(R[a]), np.array(R[b])
    cos = float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb)))
    pairs.append((cos, a, b))
for cos, a, b in sorted(pairs)[:6]:
    print(f'  cos({a}, {b}) = {cos:+.2f}  {"independent" if cos < 0.9 else "same effect"}')
indep = any(c < 0.9 for c, _, _ in pairs)
bbox_dim = [k for k, r in R.items() if max(abs(x) for x in r[1:]) >= 0.01]
print(f'dimensions that change a bounding-box length by >= 1%: {bbox_dim} (need at least one)')
if len(shp.Faces) > 60:
    print(f'faces {len(shp.Faces)}: too many for a designer model; curved outlines as ellipse/circle or one'
          ' spline_loop (ring) each, not polygons of many edges')
print(f'\nVERDICT reopen {"ok" if not bad else "FAILED"} | one clean solid {len(shp.Solids) == 1 and ok} | '
      f'faces {len(shp.Faces)} | other visible {vis} | IoU est {iou:.3f} | dimensions that move it {len(R)} | '
      f'two independent dimensions {indep} | bbox-moving dimension {bool(bbox_dim)}')
App.closeDocument(doc.Name)
