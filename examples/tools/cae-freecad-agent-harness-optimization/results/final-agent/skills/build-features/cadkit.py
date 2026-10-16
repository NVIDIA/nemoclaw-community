# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Feature-level building blocks for PartDesign in headless FreeCAD 1.1, in WORLD coordinates.

    import sys; sys.path.insert(0, '/agent/skills/build-features'); from cadkit import *
    m = Model()                                  # new document, Body, spreadsheet Params
    m.param('Height', 13.4)                      # a named dimension (spreadsheet alias)

Every point is a world point (x, y, z), the same numbers measure-mesh prints. Any number
of a point or size may instead be an expression over parameters, as a string ('Height',
'OuterWidth - 2*Wall'): the feature is then driven by those parameters. Each block makes
ONE sketch or ONE feature, recomputes, and prints one status line; you decide which
features, where, and which dimensions drive them.
"""
import math
import re

import FreeCAD as App
import numpy as np
import Part
import Sketcher

V = App.Vector


def _say(*a, **k):
    """print on a fresh line (FreeCAD's progress output ends lines with \\r)"""
    k.pop('flush', None)
    print('\n' + ' '.join(str(x) for x in a), flush=True, **k)
App.Console.SetStatus('Console', 'Log', False)


def _vec(p):
    return V(*[float(c) for c in p])


def _frame(normal, xdir=None):
    n = _vec(normal).normalize()
    if xdir is None:
        xdir = (1, 0, 0) if abs(n.x) < 0.9 else (0, 1, 0)
    u = _vec(xdir)
    u = (u - n * u.dot(n)).normalize()
    return u, n.cross(u), n


class Model:
    """One document 'Model' with one PartDesign Body and a spreadsheet 'Params'."""

    def __init__(self, name='Model'):
        self.doc = App.newDocument(name)
        self.body = self.doc.addObject('PartDesign::Body', 'Body')
        self.sheet = self.doc.addObject('Spreadsheet::Sheet', 'Params')
        self.params = {}
        self._frames = {}
        self._rings = {}
        self._quiet = False
        self._areas = {}
        self._checks = {}
        self._broken = []
        self._xy = [f for f in self.body.Origin.OriginFeatures if f.Role == 'XY_Plane'][0]

    # ---------- named dimensions ----------
    def param(self, name, value):
        """Named dimension (mm) in the spreadsheet. Use its name in expressions."""
        if re.fullmatch(r'[A-Za-z]{1,3}[0-9]+', name) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError(f'parameter name {name!r}: use a word such as OuterDiameter (not a cell name like D1)')
        row = self.params.get(name) or len(self.params) + 1
        self.params[name] = row
        self.sheet.set(f'A{row}', name)
        self.sheet.set(f'B{row}', f'{float(value):.6g}')
        self.sheet.setAlias(f'B{row}', name)
        self.doc.recompute()
        return name

    def value(self, expr):
        """Current numeric value of a number or an expression over parameters."""
        if not isinstance(expr, str):
            return float(expr)
        env = {k: float(self.sheet.get(k)) for k in self.params}
        env.update(math.__dict__)
        return float(eval(expr, {'__builtins__': {}}, env))

    def _expr(self, s):
        """'Height - 2*Wall' -> 'Params.Height - 2*Params.Wall'"""
        try:
            return f'{float(s):.6g}'
        except ValueError:
            pass
        for k in self.params:
            if k not in s:
                continue
            s = re.sub(rf'(?<![\w.]){k}(?!\w)', f'Params.{k}', s)
        if 'Params.' not in s:
            raise ValueError(f'expression {s!r} names no parameter; parameters: {list(self.params)} (pass plain numbers as numbers)')
        return s

    def _bind(self, obj, prop, val):
        """Set obj.prop to a number, or bind it to an expression string."""
        if isinstance(val, str):
            obj.setExpression(prop, self._expr(val))
        else:
            setattr(obj, prop.lstrip('.'), float(val))

    # ---------- sketches (world coordinates) ----------
    def _sketch(self, name, origin, normal=(0, 0, 1), xdir=None):
        """Sketch whose plane passes through world point `origin` with the given normal;
        any coordinate of origin may be an expression (moves the sketch with it)."""
        u, v, n = _frame(normal, xdir)
        o = [self.value(c) for c in origin]
        sk = self.body.newObject('Sketcher::SketchObject', name)
        sk.AttachmentSupport = [(self._xy, '')]
        sk.MapMode = 'FlatFace'
        sk.AttachmentOffset = App.Placement(V(*o), App.Rotation(u, v, n, 'ZXY'))
        for c, axis in zip(origin, 'xyz'):
            if isinstance(c, str):
                sk.setExpression(f'.AttachmentOffset.Base.{axis}', self._expr(c))
        self._frames[sk.Name] = (V(*o), u, v, n)
        return sk

    def circle(self, name, center, d, normal=(0, 0, 1)):
        """Sketch of one circle: world centre, diameter d (number or expression)."""
        sk = self._sketch(name, center, normal)
        g = sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), self.value(d) / 2), False)
        sk.addConstraint(Sketcher.Constraint('Coincident', g, 3, -1, 1))
        c = sk.addConstraint(Sketcher.Constraint('Diameter', g, self.value(d)))
        if isinstance(d, str):
            sk.setExpression(f'Constraints[{c}]', self._expr(d))
        return sk

    def ellipse(self, name, center, w, h, angle=0.0, normal=(0, 0, 1), xdir=None):
        """Sketch of one ellipse: world centre, full width w along the plane's x direction
        rotated by `angle` degrees, full height h across it (numbers or expressions).
        For normal (0,0,1) the plane's x is world +x: w and h are measure-mesh's 2*hw
        at its `ang`. A circle when w == h (use circle() for round parts)."""
        sk = self._sketch(name, center, normal, xdir)
        a, b = self.value(w) / 2, self.value(h) / 2
        t = math.radians(angle)
        swap = a < b
        if swap:
            a, b, t = b, a, t + math.pi / 2
        major = V(a * math.cos(t), a * math.sin(t), 0)
        minor = V(-b * math.sin(t), b * math.cos(t), 0)
        g = sk.addGeometry(Part.Ellipse(major, minor, V(0, 0, 0)), False)
        n0 = sk.GeometryCount
        sk.exposeInternalGeometry(g)
        lines = sorted((i for i in range(n0, sk.GeometryCount) if isinstance(sk.Geometry[i], Part.LineSegment)),
                       key=lambda i: -sk.Geometry[i].length())
        sk.addConstraint(Sketcher.Constraint('Coincident', g, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint('Angle', lines[0], t))
        c1 = sk.addConstraint(Sketcher.Constraint('Distance', lines[0], 2 * a))
        c2 = sk.addConstraint(Sketcher.Constraint('Distance', lines[1], 2 * b))
        big, small = (h, w) if swap else (w, h)
        for c, e in ((c1, big), (c2, small)):
            if isinstance(e, str):
                sk.setExpression(f'Constraints[{c}]', self._expr(e))
        return sk

    def polygon(self, name, pts, normal=None):
        """Sketch of one closed polygon through world points (all in one plane; the
        normal is fitted if not given). One face per edge: for few straight edges only."""
        P = [_vec(p) for p in pts]
        o = sum(P, V()) * (1.0 / len(P))
        n = _vec(normal) if normal else _fit_normal(P)
        sk = self._sketch(name, o, n, P[0] - o if (P[0] - o).Length > 1e-9 else None)
        q = [self._local(sk, p) for p in P]
        k = len(q)
        ids = [sk.addGeometry(Part.LineSegment(q[i], q[(i + 1) % k]), False) for i in range(k)]
        for i in range(k):
            sk.addConstraint(Sketcher.Constraint('Coincident', ids[i], 2, ids[(i + 1) % k], 1))
        return sk

    def mesh_section(self, name, origin, normal=(0, 0, 1), kind='OUT', pick='largest', xdir=None,
                     mesh='/app/reference.obj', level=None, smooth=True, npts=48, along=None, align_to=None):
        """Sketch of one loop of the mesh's cut by the plane through world point `origin`
        (normal `normal`), drawn where the mesh is: kind 'OUT' (outer boundary) or 'HOLE';
        pick 'largest', 'smallest', or a world point (the loop whose centre is nearest).
        smooth=True: one closed B-spline (one face; for curved outlines); False: polygon
        (keeps sharp corners). level: an expression that moves the sketch along its
        normal, e.g. 'Height' (its value must equal origin's coordinate along the normal).
        For loft sections cut every level with the same normal and xdir."""
        loops = _cut(mesh, _vec(origin), _vec(normal), kind)
        if not loops:
            raise ValueError(f'{name}: no {kind} loop at {tuple(origin)} normal {tuple(normal)}')
        if pick == 'largest':
            L = max(loops, key=lambda q: q[1])
        elif pick == 'smallest':
            L = min(loops, key=lambda q: q[1])
        else:
            L = min(loops, key=lambda q: (q[2] - _vec(pick)).Length)
        pts, area, cen = L
        org = list(origin)
        n = _vec(normal).normalize()
        if level is not None:
            # origin moves with the expression: along the normal, or along `along` (a slanted
            # feature) so that its coordinate along the normal equals the level
            s0 = _vec(origin).dot(n)
            a = n if along is None else _vec(along) * (1.0 / _vec(along).dot(n))
            driven = isinstance(level, str) and any(re.search(rf'(?<![\w.]){k}(?!\w)', level) for k in self.params)
            if driven:
                org = [f'{origin[i]:.6g} + {a[i]:.6g} * (({level}) - {s0:.6g})' if abs(a[i]) > 1e-9 else origin[i]
                       for i in range(3)]
            else:
                org = [origin[i] + a[i] * (self.value(level) - s0) for i in range(3)]
        sk = self._sketch(name, org, normal, xdir)
        q = [self._local(sk, p) for p in pts]
        if smooth:
            q = _resample(q, npts)
            if align_to is not None and align_to in self._rings and len(self._rings[align_to]) == len(q):
                q = _align(q, self._rings[align_to])
            self._rings[sk.Name] = q
            bs = Part.BSplineCurve()
            bs.interpolate(q, PeriodicFlag=True)
            sk.addGeometry(bs, False)
        else:
            q = _simplify(q, 0.02 * math.sqrt(area))
            k = len(q)
            ids = [sk.addGeometry(Part.LineSegment(q[i], q[(i + 1) % k]), False) for i in range(k)]
            for i in range(k):
                sk.addConstraint(Sketcher.Constraint('Coincident', ids[i], 2, ids[(i + 1) % k], 1))
        self._areas[sk.Name] = area
        if not self._quiet:
            _say(f'  {name}: {kind} loop area {area:.4g} centre ({cen.x:.3f}, {cen.y:.3f}, {cen.z:.3f}) '
                  f'of {len(loops)} {kind} loop(s)', flush=True)
        return sk

    def _local(self, sk, p):
        o, u, v, n = self._frames[sk.Name]
        d = _vec(p) - o
        return V(d.dot(u), d.dot(v), 0)

    def section_loft(self, name, start, end, n=8, normal=(0, 0, 1), through=None, kind='OUT',
                     pick='largest', bottom=None, top=None, cut=False, mesh='/app/reference.obj', along=None):
        """One feature: a ruled loft through n of the mesh's own loops, cut at n levels from
        `start` to `end` along `normal` (levels = world coordinate along the normal; the plane
        passes through `through`, default the origin shifted to each level). kind 'OUT' for a
        body, 'HOLE' for a cavity (cut=True); pick as in mesh_section ('largest', or a world
        point: the loop whose centre is nearest, at every level). bottom/top: expressions that
        move the first/last section (e.g. top='Height', or 'Height + 1' for a cavity cut that
        must open the rim, bottom='Floor'). along=(dx,dy,dz): a slanted feature's direction;
        bottom/top then move those sections along it. Levels with no such loop are skipped.
        Where the loop changes fast next to an end (a rounded floor or rim), extra levels are
        added there automatically."""
        if isinstance(start, str):          # an expression: also drives the first section
            bottom = bottom or start
        if isinstance(end, str):
            top = top or end
        start, end = self.value(start), self.value(end)
        nn = _vec(normal).normalize()
        base = _vec(through) if through is not None else V(0, 0, 0)
        b0 = base.dot(nn)
        step = (end - start) / (n - 1)
        tries = [(0.0, 0.0), (0.3, 0.3)]
        lv = [start + step * i for i in range(n)]

        def sec(i, h, ref=None, follow=None):
            org = base + nn * (h - b0)
            lev = bottom if i == 0 else top if i == n - 1 else None
            if i < 0:
                extra[0] += 1
                i = 1000 + extra[0]
                if isinstance(follow, str):   # an added level next to a driven end moves with it
                    lev = f'({follow}) + {h - self.value(follow):.6g}'
            if lev is not None and k == 0 and abs(self.value(lev) - h) > 0.02 * abs(end - start):
                # the end section is moved by an expression: say if it leaves the mesh's loops there
                o3 = base + nn * (self.value(lev) - b0 + (0.02 if i == 0 else -0.02) * step)
                if not _cut(mesh, o3, nn, kind):
                    _say(f'  NOTE {name}: its {"bottom" if i == 0 else "top"} moves from {h:.3f} to {self.value(lev):.3f}, '
                         f'where the mesh has no {kind} loop: '
                         + ('the cut opens that end (right only for an open face, e.g. a rim; '
                            'below a floor it cuts through the floor)' if cut else
                            'the feature goes past the mesh there'), flush=True)
            # an end section past the mesh (e.g. a cut 1 mm above the rim): take the nearest
            # loop inside and move it to the end level
            inward = (1 if i == 0 else -1) * step
            for j in range(9 if i in (0, n - 1) else 1):
                o2 = org + nn * (inward * 0.25 * j)
                lev2 = lev if lev is not None or j == 0 else f'{h:.6g}'
                try:
                    sk = self.mesh_section(f'{name}{i}_{k}_{j}' if i in (0, n - 1) else f'{name}{i}',
                                           (o2.x, o2.y, o2.z), normal, kind, pick, mesh=mesh,
                                           level=lev2 if j else lev, along=along, align_to=ref)
                    if i in (0, n - 1) and amax[0] and self._areas.get(sk.Name, 0) < 0.03 * amax[0] and j < 8:
                        # a vanishing end loop (a pocket or a tip tapering to a point) makes a
                        # degenerate loft: take the first loop of real size, moved to the end level
                        self.body.removeObject(sk)
                        self.doc.removeObject(sk.Name)
                        err = ValueError('end loop too small')
                        continue
                    return sk
                except ValueError as e:
                    err = e
            _say(f'  {name}{i}: skipped ({err})')
            return None
        k = 0
        amax = [0.0]
        extra = [0]
        self._quiet = True
        mids = []
        for i in range(1, n - 1):
            prev = next((x for x in reversed(mids) if x is not None), None)
            mids.append(sec(i, lv[i], prev.Name if prev is not None else None))
        live = [x for x in mids if x is not None]
        amax[0] = max([self._areas.get(x.Name, 0) for x in live] or [0])
        for k, (a0, a1) in enumerate(tries):
            first = sec(0, lv[0] + step * max(a0, 0.002 * (n - 1)), live[0].Name if live else None)
            last = sec(n - 1, lv[-1] - step * max(a1, 0.002 * (n - 1)), live[-1].Name if live else None)
            if k == 0 and live:
                # an end loop much smaller or larger than its neighbour (a rounded floor, a
                # flaring rim): add levels between them so the ruled loft follows the curve
                for end_sk, h_end, nb, sign in ((first, lv[0], live[0], 1), (last, lv[-1], live[-1], -1)):
                    if end_sk is None:
                        continue
                    a_e, a_n = self._areas.get(end_sk.Name, 0), self._areas.get(nb.Name, 0)
                    if a_n and not 0.6 < a_e / a_n < 1.6:
                        hs_ = [h_end + sign * step * f_ for f_ in (0.15, 0.4)]
                        new = [sec(-1, h_, nb.Name, bottom if sign > 0 else top) for h_ in hs_]
                        new = [x for x in new if x is not None]
                        if sign > 0:
                            mids[:0] = new
                        else:
                            mids.extend(reversed(new))
            sks = [x for x in [first] + mids + [last] if x is not None]
            if len(sks) < 2:
                raise ValueError(f'{name}: fewer than 2 sections with a {kind} loop between {start} and {end}')
            f = self.loft(name if k == 0 else f'{name}_{k}', sks, cut=cut, _report=False)
            quick = f.isValid()
            if quick:
                try:
                    f.AddSubShape.check(True)
                except Exception:  # noqa: BLE001
                    quick = False
            n_before = len(self._broken)
            if quick or k == len(tries) - 1:
                self._quiet = False
                areas = ', '.join(f'{self._areas.get(x.Name, 0):.4g}' for x in sks)
                _say(f'  {name}: {len(sks)} sections from {lv[0]:.3f} to {lv[-1]:.3f} along {tuple(round(c, 3) for c in nn)}, '
                     f'loop areas {areas}')
                self._done(f)
                if self.status()[0] or k == len(tries) - 1:
                    return f
                if quick and len(self.body.Shape.Solids) > 1:
                    return f          # a clean loft that does not reach the part: moving its ends will not help
                del self._broken[n_before:]
                self._quiet = True
            # the loft broke the part: usually an end section cut where the outline changes
            # abruptly (a junction or a tapering end); move the end sections inward and retry
            _say(f'  {name}: retrying with the end sections moved inward ({tries[k + 1][0]:.2f}, {tries[k + 1][1]:.2f} of a step)')
            for o in [f, first, last]:
                if o is not None:
                    self.body.removeObject(o)
                    self.doc.removeObject(o.Name)
            self.doc.recompute()

    def prism(self, name, origin, normal, direction, forward, back=0, kind='OUT', pick='largest',
              mesh='/app/reference.obj', cut=False):
        """One feature: the mesh's own loop cut by the plane through world point `origin` with
        `normal`, padded `forward` along the normal and `back` against it (lengths measured
        along the normal), in the world `direction` (a straight, possibly slanted branch).
        forward/back: numbers or expressions."""
        sk = self.mesh_section(name + 'Section', origin, normal, kind, pick, mesh=mesh, smooth=True)
        return self.pad(name, sk, forward, back, direction=direction, cut=cut)

    # ---------- features ----------
    def pad(self, name, sketch, length, length2=0, direction=None, cut=False):
        """Pad (cut=True: Pocket) the sketch along its normal by `length`, and back by
        `length2` (two-sided). direction=(dx,dy,dz): along that world direction instead
        (a slanted bar); lengths are then measured along the sketch normal.
        Lengths: numbers or expressions."""
        f = self.body.newObject('PartDesign::Pocket' if cut else 'PartDesign::Pad', name)
        f.Profile = sketch
        self._bind(f, 'Length', length)
        if length2:
            f.SideType = 'Two sides'
            self._bind(f, 'Length2', length2)
        if direction is not None:
            f.UseCustomVector = True
            f.Direction = _vec(direction)
            f.AlongSketchNormal = True
        return self._done(f)

    def loft(self, name, sketches, cut=False, ruled=True, _report=True):
        """Loft (cut=True: subtractive) through sketches in order. Ruled (straight
        between sections) follows measured sections; smooth lofts overshoot."""
        f = self.body.newObject('PartDesign::SubtractiveLoft' if cut else 'PartDesign::AdditiveLoft', name)
        f.Profile = sketches[0]
        f.Sections = list(sketches[1:])
        f.Ruled = ruled
        if not _report:
            self.doc.recompute()
            return f
        return self._done(f)

    def revolve(self, name, sketch, axis_point, axis_dir, angle=360, cut=False):
        """Revolve (cut=True: Groove) a profile sketch about the world axis through
        axis_point along axis_dir. The profile must lie in a plane containing the axis
        and on one side of it (draw it with polygon())."""
        ln = self.body.newObject('PartDesign::Line', name + 'Axis')
        ln.MapMode = 'Deactivated'
        ln.Placement = App.Placement(_vec(axis_point), App.Rotation(V(0, 0, 1), _vec(axis_dir)))
        ln.Visibility = False
        f = self.body.newObject('PartDesign::Groove' if cut else 'PartDesign::Revolution', name)
        f.Profile = sketch
        f.ReferenceAxis = (ln, [''])
        self._bind(f, 'Angle', angle)
        return self._done(f)

    def tube(self, name, pts, d, h=None, cut=False):
        """Sweep (cut=True: subtractive) a circle of diameter d (or an ellipse d x h, d in
        the path's plane) along a smooth path through world points `pts` (in order, in
        one plane). Makes the path and profile sketches. d, h: numbers or expressions.
        If the sweep breaks the part, it is retried with a round profile of the same area,
        then without the first and last points (the path then ends where those were)."""
        tries = [(pts, d, h)]
        if h is not None:
            tries.append((pts, f'sqrt(({d}) * ({h}))' if isinstance(d, str) or isinstance(h, str)
                          else math.sqrt(float(d) * float(h)), None))
        if len(pts) > 4:
            tries.append((pts[1:-1], d, h))
        for k, (p_, d_, h_) in enumerate(tries):
            nb = len(self._broken)
            f = self._tube_once(name if k == 0 else f'{name}_{k}', p_, d_, h_, cut)
            if len(self._broken) == nb or k == len(tries) - 1:
                return f
            self._quiet = False
            nxt = tries[k + 1]
            what = 'a round profile of the same area' if nxt[2] is None and h is not None and nxt[0] is pts \
                else 'the path without its first and last points'
            _say(f'  {name}: retrying with {what}', flush=True)
            del self._broken[nb:]
            for o in [f, f.Profile[0] if isinstance(f.Profile, tuple) else f.Profile, f.Spine[0] if isinstance(f.Spine, tuple) else f.Spine]:
                try:
                    self.body.removeObject(o)
                    self.doc.removeObject(o.Name)
                except Exception:  # noqa: BLE001
                    pass
            self.doc.recompute()

    def _tube_once(self, name, pts, d, h=None, cut=False):
        P = [_vec(p) for p in pts]
        n = _fit_normal(P)
        o = sum(P, V()) * (1.0 / len(P))
        path = self._sketch(name + 'Path', o, n, P[-1] - P[0])
        bs = Part.BSplineCurve()
        bs.interpolate([self._local(path, p) for p in P])
        path.addGeometry(bs, False)
        self.doc.recompute()
        e = path.Shape.Edges[0]
        p0, t0 = e.valueAt(e.FirstParameter), e.tangentAt(e.FirstParameter)
        side = n.cross(t0)   # in the path plane, normal to the tangent
        if h is None:
            prof = self.circle(name + 'Profile', (p0.x, p0.y, p0.z), d, normal=t0)
        else:
            prof = self.ellipse(name + 'Profile', (p0.x, p0.y, p0.z), d, h, normal=t0, xdir=side)
        f = self.body.newObject('PartDesign::SubtractivePipe' if cut else 'PartDesign::AdditivePipe', name)
        f.Profile = prof
        f.Spine = (path, ['Edge1'])
        return self._done(f)

    def hole(self, name, center, normal, d, depth=None):
        """Round hole of diameter d from world point `center` into the part along -normal
        (normal points out of the face), `depth` deep, or through all if None."""
        sk = self.circle(name + 'Sketch', center, d, normal=normal)
        f = self.body.newObject('PartDesign::Pocket', name)
        f.Profile = sk
        if depth is None:
            f.Type = 'ThroughAll'
        else:
            self._bind(f, 'Length', depth)
        return self._done(f)

    # ---------- status and save ----------
    def _done(self, f):
        self.doc.recompute()
        s = self.body.Shape
        ok = self._check(s)
        state = '' if f.isValid() else f' INVALID FEATURE: {f.getStatusString()}'
        bb = s.optimalBoundingBox() if not s.isNull() else None
        _say(f'{f.Name}: solids {len(s.Solids)} check {ok} faces {len(s.Faces)} volume {s.Volume:.5g} '
              + (f'bbox x {bb.XMin:.2f}..{bb.XMax:.2f} y {bb.YMin:.2f}..{bb.YMax:.2f} z {bb.ZMin:.2f}..{bb.ZMax:.2f}' if bb else '')
              + state, flush=True)
        if state or ok != 'ok' or len(s.Solids) != 1:
            why = 'it does not touch the part (start it inside the body)' if ok == 'ok' and not state and len(s.Solids) > 1 \
                else 'the part is no longer one clean solid'
            _say(f'  -> {f.Name} broke the part: {why}; change this feature (the ones before it were fine). '
                 f'm.save drops it and saves the rest', flush=True)
            self._broken.append(f.Name)
        return f

    def _check(self, s):
        """'ok' or 'FAILED (...)' for FreeCAD's full shape check, cached per shape state."""
        if s.isNull():
            return 'FAILED (empty shape)'
        key = (round(s.Volume, 6), len(s.Faces), len(s.Edges), len(s.Solids))
        if key not in self._checks:
            try:
                s.check(True)
                self._checks[key] = 'ok'
            except Exception as e:  # noqa: BLE001
                self._checks[key] = f'FAILED ({str(e)[:80]})'
        return self._checks[key]

    def status(self):
        """(valid, solids, faces, volume) of the body now."""
        s = self.body.Shape
        ok = self._check(s) == 'ok'
        bad = [o.Name for o in self.doc.Objects if not o.isValid()]
        return ok and not bad and len(s.Solids) == 1, len(s.Solids), len(s.Faces), s.Volume

    def _drop(self, name):
        """remove one feature and the sketches only it used; the body relinks the rest"""
        f = self.doc.getObject(name)
        if f is None:
            return
        sks = [f.Profile[0] if isinstance(f.Profile, tuple) else f.Profile] if hasattr(f, 'Profile') and f.Profile else []
        sks += list(getattr(f, 'Sections', []) or [])
        sp = getattr(f, 'Spine', None)
        if sp:
            sks.append(sp[0] if isinstance(sp, tuple) else sp)
        self.body.removeObject(f)
        self.doc.removeObject(name)
        for sk in sks:
            try:
                if sk is not None and not [o for o in sk.InList if o not in (self.body,)]:
                    self.body.removeObject(sk)
                    self.doc.removeObject(sk.Name)
            except Exception:  # noqa: BLE001
                pass
        self.doc.recompute()

    def save(self, path='/app/model.FCStd', mesh='/app/reference.obj'):
        """Hide everything but the Body, save, reopen and recompute the file, and print an
        IoU estimate and WHERE the model differs from the mesh (regions of missing or extra
        material, the feature each comes from). A feature that broke the part is dropped
        first (the rest is saved). /app/model.FCStd is replaced only by a valid single solid
        whose IoU estimate is not below the saved one's (0.005 slack); otherwise the model goes
        to /app/rejected.FCStd and the previous model stays."""
        import os
        import sys
        import Mesh
        sys.path.insert(0, '/agent/skills/verify-model')
        import where
        valid = self.status()[0]
        dropped = []
        if not valid:
            for name in list(self._broken):
                self._drop(name)
                dropped.append(name)
                if self.status()[0]:
                    break
            if not self.status()[0]:   # still broken: keep the features up to the last good one
                feats = [o for o in self.body.Group if o.TypeId.startswith('PartDesign::') and hasattr(o, 'AddSubShape')]
                while feats and not self.status()[0]:
                    f = feats.pop()
                    dropped.append(f.Name)
                    self._drop(f.Name)
            if dropped:
                _say(f'DROPPED {dropped}: they broke the part; the model without them is checked and saved below. '
                     f'Fix those features (see their status lines above) and run again', flush=True)
        for o in self.doc.Objects:
            if hasattr(o, 'Visibility'):
                o.Visibility = False
        self.body.Visibility = True
        if self.body.Tip is not None:
            self.body.Tip.Visibility = True
        self.doc.recompute()
        valid, ns, nf, vol = self.status()
        feats = [o.Name for o in self.body.Group if o.TypeId.startswith('PartDesign::') and hasattr(o, 'AddSubShape')]
        iou = 0.0
        if not self.body.Shape.isNull() and os.path.exists(mesh):
            me = Mesh.Mesh(mesh)
            ta = np.array([[list(p) for p in f.Points] for f in me.Facets])
            iou = where.report(ta, self.body.Shape, where.features_of(self.body), me.Volume)
        score = path + '.iou'
        prev = float(open(score).read()) if os.path.exists(path) and os.path.exists(score) else None
        why = ''
        if not valid or self.body.Shape.isNull():
            why = f'not one valid solid (solids {ns})'
        elif prev is not None and iou < prev - 0.005:
            why = f'IoU estimate {iou:.3f} is below the saved model\'s {prev:.3f}'
        if why:
            _say(f'NOT SAVED over {path}: {why}; saved to /app/rejected.FCStd, the previous model'
                 + (f' (IoU estimate {prev:.3f}) stays' if prev is not None else ' stays'), flush=True)
            path, score = '/app/rejected.FCStd', None
        tmp = path[:-6] + '.tmp.FCStd' if path.endswith('.FCStd') else path + '.tmp'
        self.doc.saveAs(tmp)
        os.replace(tmp, path)
        if score:
            open(score, 'w').write(f'{iou:.4f}')
        d2 = App.openDocument(path)
        d2.recompute()
        bad = [o.Name for o in d2.Objects if not o.isValid()]
        _say(f'SAVED {path}: one valid solid {valid} (solids {ns}) faces {nf} volume {vol:.5g} '
             f'IoU estimate {iou:.3f} | features {feats} | reopened: invalid objects {bad} | parameters {list(self.params)}', flush=True)
        App.closeDocument(d2.Name)
        if valid and iou >= 0.85:
            self._dims()
        return valid

    def _dims(self):
        """How each named dimension moves the part (+10%, volume and bounding box; no shape
        check): the part needs two that move it in different ways, one of them its bounding box."""
        def resp():
            sh = self.body.Shape
            b = sh.optimalBoundingBox()
            return np.array([sh.Volume, b.XLength, b.YLength, b.ZLength])
        base = resp()
        R = {}
        lines = []
        for nm in self.params:
            v0 = float(self.sheet.get(nm))
            try:
                self.sheet.set(nm, f'{(v0 * 1.1 if v0 else 1.0):.6g}')
                self.doc.recompute()
                r = (resp() - base) / np.maximum(np.abs(base), 1e-9)
            except Exception:  # noqa: BLE001
                r = None
            finally:
                self.sheet.set(nm, f'{v0:.6g}')
                self.doc.recompute()
            if r is None or not np.isfinite(r).all():
                lines.append(f'{nm}: breaks the part')
                continue
            mv = float(np.max(np.abs(r)))
            tag = 'moves the bounding box' if np.max(np.abs(r[1:])) >= 0.01 else 'moves the part' if mv >= 0.005 \
                else ('drives nothing' if mv < 1e-6 else f'moves it only {100 * mv:.1f} percent, too little')
            lines.append(f'{nm}: dV {r[0]:+.3f} dX {r[1]:+.3f} dY {r[2]:+.3f} dZ {r[3]:+.3f} ({tag})')
            if mv >= 0.005:
                R[nm] = r
        pair = any(float(R[a] @ R[b] / (np.linalg.norm(R[a]) * np.linalg.norm(R[b]))) < 0.9
                   for i, a in enumerate(R) for b in list(R)[i + 1:])
        box = any(np.max(np.abs(r[1:])) >= 0.01 for r in R.values())
        _say('DIMENSIONS (+10% each): ' + '; '.join(lines) + f' | two that move it differently {pair}, '
             f'one moves the bounding box {box}' + ('' if pair and box else
             ' -> bind another dimension a designer would change (a branch length or diameter, a wall) to its feature'),
             flush=True)


# ---------- geometry helpers ----------
def _fit_normal(P):
    import numpy as np
    A = np.array([[p.x, p.y, p.z] for p in P])
    A = A - A.mean(0)
    n = np.linalg.svd(A)[2][2]
    return V(*n)


_MESHES = {}


def _cut(mesh, o, n, kind):
    """Loops of the mesh cut: list of (world points, area, world centre) of the kind asked."""
    import Mesh
    if mesh not in _MESHES:
        _MESHES[mesh] = Mesh.Mesh(mesh)
    m = _MESHES[mesh]
    n = V(n).normalize()
    u, v, _ = _frame(n)
    raw = []
    for s in m.crossSections([(o, n)], 1e-6)[0]:
        P = [V(p) for p in s]
        if len(P) > 3 and (P[0] - P[-1]).Length < 1e-9:
            P = P[:-1]
        q = np.array([[(p - o).dot(u), (p - o).dot(v)] for p in P])
        if len(q) < 3:
            continue
        a = 0.5 * float(np.sum(q[:, 0] * np.roll(q[:, 1], 1) - np.roll(q[:, 0], 1) * q[:, 1]))
        if abs(a) < 1e-6:
            continue
        raw.append((P, q, abs(a)))

    def inside(pt, poly):
        x, y = pt
        c = False
        for i in range(len(poly)):
            (x1, y1), (x2, y2) = poly[i - 1], poly[i]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                c = not c
        return c
    out = []
    for i, (P, q, a) in enumerate(raw):
        depth = sum(inside(q[0], raw[j][1]) for j in range(len(raw)) if j != i)
        k = 'HOLE' if depth % 2 else 'OUT'
        if k == kind:
            out.append((P, a, sum(P, V()) * (1.0 / len(P))))
    return out


def _resample(q, k):
    """k points evenly spaced along the closed loop q, counter-clockwise, starting on the
    +x side of its centre (so sections of a loft correspond point by point)."""
    import numpy as np
    a = np.array([[p.x, p.y] for p in q])
    ar = 0.5 * np.sum(a[:, 0] * np.roll(a[:, 1], -1) - np.roll(a[:, 0], -1) * a[:, 1])
    if ar < 0:
        a = a[::-1]
    c = a.mean(0)
    ang = np.abs(np.arctan2(a[:, 1] - c[1], a[:, 0] - c[0]))
    i0 = int(np.argmin(ang + (a[:, 0] < c[0]) * 10))
    a = np.roll(a, -i0, axis=0)
    ac = np.vstack([a, a[:1]])
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(ac, axis=0), axis=1))])
    t = np.linspace(0, s[-1], k + 1)[:-1]
    return [V(x, y, 0) for x, y in zip(np.interp(t, s, ac[:, 0]), np.interp(t, s, ac[:, 1]))]


def _align(q, ref):
    """cyclic shift of ring q (same point count as ref) that best matches ref point by point
    (centres removed), so a ruled loft between them does not twist"""
    a = np.array([[p.x, p.y] for p in q])
    b = np.array([[p.x, p.y] for p in ref])
    a0, b0 = a - a.mean(0), b - b.mean(0)
    best = min(range(len(a)), key=lambda k: float(np.sum((np.roll(a0, -k, axis=0) - b0) ** 2)))
    return list(q[best:]) + list(q[:best])


def _simplify(q, tol):
    import numpy as np
    a = np.array([[p.x, p.y] for p in q])

    def dp(b):
        if len(b) < 3:
            return list(b)
        s, e = b[0], b[-1]
        d = e - s
        L = np.linalg.norm(d)
        dist = np.linalg.norm(b - s, axis=1) if L < 1e-12 else np.abs(d[0] * (b[:, 1] - s[1]) - d[1] * (b[:, 0] - s[0])) / L
        i = int(np.argmax(dist))
        if dist[i] <= tol:
            return [s, e]
        return dp(b[:i + 1])[:-1] + dp(b[i:])
    far = int(np.argmax(np.linalg.norm(a - a[0], axis=1)))
    r = dp(a[:far + 1])[:-1] + dp(np.vstack([a[far:], a[:1]]))[:-1]
    return [V(x, y, 0) for x, y in r]
