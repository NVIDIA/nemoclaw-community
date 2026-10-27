# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Small PartDesign/Sketcher building blocks, tested headless in FreeCAD 1.1.3.

Use from your own build script, run with `python3 build.py` (or freecadcmd build.py):

    import sys; sys.path.insert(0, '/agent/skills/cad-toolkit')
    import sketchkit as K
    doc, body, P = K.new_model('Model', frame='/app/frame.json')   # body posed in the part frame
    K.param(P, 'Height', 40.0)
    sk = K.sketch(body, 'XY')                      # local XY plane, normal +local z
    c = K.polygon(sk, [(0,0),(30,0),(30,20),(0,20)])   # closed, fully constrained by vertex coords
    K.bind(sk, c['x1'], 'Params.Length')           # named dimension drives vertex 1's x
    pad = K.pad(body, sk, 'Params.Height')
    K.finish(doc, '/app/model.FCStd')              # recompute, check, one visible object, save

Every dimension is a constraint you can bind to a Params alias with an expression; reuse one
alias in several places to keep features linked (e.g. 'Params.Width - Params.Wall').
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fc  # noqa: E402,F401
import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import Sketcher  # noqa: E402

V = App.Vector


def new_model(name='Model', frame=None):
    """New document with a PartDesign Body and a spreadsheet 'Params'. Pose the body in the
    measured frame (frame.json) so you model in local coordinates."""
    doc = App.newDocument(name)
    body = doc.addObject('PartDesign::Body', 'Body')
    sheet = doc.addObject('Spreadsheet::Sheet', 'Params')
    if frame:
        pose_body(body, frame)
    doc.recompute()
    return doc, body, sheet


def pose_body(body, frame='/app/frame.json'):
    fr = json.load(open(frame)) if isinstance(frame, str) else frame
    R, o = fr['R'], fr['origin']
    m = App.Matrix(R[0][0], R[1][0], R[2][0], o[0],
                   R[0][1], R[1][1], R[2][1], o[1],
                   R[0][2], R[1][2], R[2][2], o[2],
                   0, 0, 0, 1)
    body.Placement = App.Placement(m)


def param(sheet, name, value):
    """Named dimension in the Params sheet; reference it as 'Params.<name>'."""
    if hasattr(sheet, 'isValidAlias') and not sheet.isValidAlias(name):
        raise ValueError(f'alias {name!r} is invalid: use a word like OuterDiameter, not a '
                         'cell-like name (H, D1, R2) or a unit name (mm, deg)')
    row = None
    for r in range(1, 500):  # reuse the row if the alias exists, else the first empty row
        cur = sheet.getContents(f'A{r}')
        if cur == name or cur == '':
            row = r
            break
    sheet.set(f'A{row}', name)
    sheet.set(f'B{row}', str(float(value)))
    sheet.setAlias(f'B{row}', name)
    sheet.recompute()
    return f'Params.{name}'


def plane(body, which):
    """'XY' -> sketch (u,v) = local (x,y), normal +z; 'XZ' -> (u,v) = (x,z), normal -y;
    'YZ' -> (u,v) = (y,z), normal +x."""
    role = {'XY': 'XY_Plane', 'XZ': 'XZ_Plane', 'YZ': 'YZ_Plane'}[which]
    for f in body.Origin.OriginFeatures:
        if f.Role == role:
            return f
    raise ValueError(which)


def sketch(body, which='XY', offset=0.0, name=None):
    """Sketch on a body origin plane, shifted `offset` along the plane normal.
    offset may be a number or an expression string ('Params.Height')."""
    sk = body.newObject('Sketcher::SketchObject', name or 'Sketch')
    sk.AttachmentSupport = [(plane(body, which), '')]
    sk.MapMode = 'FlatFace'
    if isinstance(offset, str):
        sk.setExpression('.AttachmentOffset.Base.z', offset)
    elif offset:
        sk.AttachmentOffset = App.Placement(V(0, 0, offset), App.Rotation())
    return sk


def sketch_at(body, origin, xdir, ydir, name=None):
    """Sketch on any plane of the part (local coords): its origin at `origin`, sketch u along
    `xdir`, v along `ydir` (normal = xdir x ydir). For a side feature's own section, e.g. the
    section across a curved arm, with origin = the arc centre and xdir toward the arm, so the
    sketch V_Axis is the arc's axis (sides.py prints these numbers)."""
    import numpy as np
    x = np.array(xdir, float); x /= np.linalg.norm(x)
    y = np.array(ydir, float); y -= x * (x @ y); y /= np.linalg.norm(y)
    z = np.cross(x, y)
    m = App.Matrix(x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, 0, 0, 0, 1)
    sk = body.newObject('Sketcher::SketchObject', name or 'Sketch')
    sk.AttachmentSupport = [(plane(body, 'XY'), '')]
    sk.MapMode = 'FlatFace'
    sk.AttachmentOffset = App.Placement(V(*map(float, origin)), App.Rotation(m))
    return sk


def polygon(sk, pts):
    """Closed polyline through pts (sketch u,v). Constrains every vertex by its u and v from
    the sketch origin (DistanceX/DistanceY), so the profile is fully constrained and each
    coordinate is an editable dimension. Returns {'x0': idx, 'y0': idx, ..., 'lines': [...]}.
    Bind the ones a designer would change with bind(); leave the rest as numbers."""
    n = len(pts)
    g0 = sk.GeometryCount
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        sk.addGeometry(Part.LineSegment(V(a[0], a[1], 0), V(b[0], b[1], 0)), False)
    cons = []
    for i in range(n):
        cons.append(Sketcher.Constraint('Coincident', g0 + i, 2, g0 + (i + 1) % n, 1))
    sk.addConstraint(cons)
    out = {'lines': list(range(g0, g0 + n))}
    for i, (u, v) in enumerate(pts):
        out[f'x{i}'] = sk.addConstraint(Sketcher.Constraint('DistanceX', -1, 1, g0 + i, 1, float(u)))
        out[f'y{i}'] = sk.addConstraint(Sketcher.Constraint('DistanceY', -1, 1, g0 + i, 1, float(v)))
    return out


def circle(sk, cu, cv, d):
    """Circle centred at (cu, cv) with diameter d. Returns {'geo','cx','cy','d'} constraint ids.
    (A radius/diameter constraint takes 3 arguments: ('Diameter', geo, value).)"""
    g = sk.addGeometry(Part.Circle(V(cu, cv, 0), V(0, 0, 1), d / 2.0), False)
    return {'geo': g,
            'cx': sk.addConstraint(Sketcher.Constraint('DistanceX', -1, 1, g, 3, float(cu))),
            'cy': sk.addConstraint(Sketcher.Constraint('DistanceY', -1, 1, g, 3, float(cv))),
            'd': sk.addConstraint(Sketcher.Constraint('Diameter', g, float(d)))}


def ellipse(sk, cu, cv, a, b, angle=0.0):
    """Ellipse, centre (cu,cv), semi-axis a along u and b along v (either may be the larger),
    turned by `angle` degrees (as sections.py prints it: 'angle -22.3 deg'). Returns {'geo','cx','cy','a','b'}; 'a'/'b' constrain the FULL axis lengths
    along u and v (bind them to e.g. 'Params.Length' or 'Params.Length - 2 * Params.Wall')."""
    import math
    along_u = a >= b
    t = math.radians(angle)
    du, dv = V(math.cos(t), math.sin(t), 0), V(-math.sin(t), math.cos(t), 0)
    c0 = V(cu, cv, 0)
    maj, mnr = (c0 + du * a, c0 + dv * b) if along_u else (c0 + dv * b, c0 + du * a)
    g = sk.addGeometry(Part.Ellipse(maj, mnr, c0), False)
    sk.exposeInternalGeometry(g)
    # internal geometry (major line, minor line, foci) is appended after g
    ids = [i for i in range(g + 1, sk.GeometryCount)]
    lines = [i for i in ids if sk.Geometry[i].TypeId == 'Part::GeomLineSegment']
    major, minor = lines[0], lines[1]
    out = {'geo': g,
           'cx': sk.addConstraint(Sketcher.Constraint('DistanceX', -1, 1, g, 3, float(cu))),
           'cy': sk.addConstraint(Sketcher.Constraint('DistanceY', -1, 1, g, 3, float(cv)))}
    if angle:
        sk.addConstraint(Sketcher.Constraint('Angle', major, math.radians(angle if along_u else angle + 90)))
    else:
        sk.addConstraint(Sketcher.Constraint('Horizontal' if along_u else 'Vertical', major))
    lu, lv = (major, minor) if along_u else (minor, major)
    out['a'] = sk.addConstraint(Sketcher.Constraint('Distance', lu, float(2 * a)))
    out['b'] = sk.addConstraint(Sketcher.Constraint('Distance', lv, float(2 * b)))
    return out


def bind(sk, idx, expr, name=None):
    """Drive constraint idx by an expression (e.g. 'Params.Height', 'Params.D / 2')."""
    if name:
        sk.renameConstraint(idx, name)
    sk.setExpression(f'Constraints[{idx}]', expr)


def dof(sk):
    """(solver result, fully constrained?). 0 and True = good; check before padding."""
    r = sk.solve()
    return r, sk.FullyConstrained


def _len(feat, prop, val):
    if isinstance(val, str):
        feat.setExpression(prop, val)
    else:
        setattr(feat, prop, float(val))


def pad(body, sk, length, symmetric=False, reverse=False, name='Pad'):
    f = body.newObject('PartDesign::Pad', name)
    f.Profile = sk
    _len(f, 'Length', length)
    if symmetric:
        f.SideType = 'Symmetric'
    f.Reversed = reverse
    return f


def pocket(body, sk, length=None, reverse=False, name='Pocket'):
    """length=None cuts through all (both directions)."""
    f = body.newObject('PartDesign::Pocket', name)
    f.Profile = sk
    if length is None:
        f.Type = 'ThroughAll'
        f.SideType = 'Symmetric'
    else:
        _len(f, 'Length', length)
    f.Reversed = reverse
    return f


def revolve(body, sk, angle=360.0, axis='V_Axis', name='Revolution', subtractive=False, symmetric=False):
    """Revolve a profile drawn on one side of the sketch axis (draw u >= 0 for V_Axis).
    symmetric=True turns it angle/2 each way from the sketch plane (a curved arm whose section
    is drawn at its middle)."""
    f = body.newObject('PartDesign::Groove' if subtractive else 'PartDesign::Revolution', name)
    f.Profile = sk
    f.ReferenceAxis = (sk, [axis])
    _len(f, 'Angle', angle)
    if symmetric:
        if 'SideType' in f.PropertiesList:
            f.SideType = 'Symmetric'
        else:
            f.Midplane = True
    return f


def loft(body, sketches, subtractive=False, ruled=False, closed=False, name=None):
    """Loft through >= 2 closed sketches: the FIRST goes in Profile, the rest in Sections."""
    f = body.newObject('PartDesign::SubtractiveLoft' if subtractive else 'PartDesign::AdditiveLoft',
                       name or ('Cut' if subtractive else 'Loft'))
    f.Profile = sketches[0]
    f.Sections = list(sketches[1:])
    f.Ruled = ruled
    f.Closed = closed
    return f


def status(doc):
    """Recompute; return a list of (object, problem) for anything invalid."""
    doc.recompute()
    bad = []
    for o in doc.Objects:
        st = list(o.State)
        if 'Invalid' in st or 'Error' in st or (hasattr(o, 'isValid') and not o.isValid()):
            bad.append((o.Name, st))
    return bad


def finish(doc, path='/app/model.FCStd'):
    """Recompute, report the body's solid, leave only the body visible, save. Returns a dict."""
    bad = status(doc)
    body = next(o for o in doc.Objects if o.TypeId == 'PartDesign::Body')
    s = body.Shape
    info = {'errors': bad, 'solids': len(s.Solids), 'valid': s.isValid(),
            'volume': s.Volume if not s.isNull() else 0.0, 'faces': len(s.Faces)}
    try:
        info['check'] = s.check(True) is None
    except Exception as e:  # check(True) raises with the reason
        info['check'] = f'FAILED: {str(e)[:200]}'
    for o in doc.Objects:
        if hasattr(o, 'Visibility'):
            o.Visibility = (o is body)
    doc.saveAs(path)
    print('finish:', info)
    return info
