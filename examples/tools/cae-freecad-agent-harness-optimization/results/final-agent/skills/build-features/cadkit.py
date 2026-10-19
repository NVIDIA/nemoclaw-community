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
        self._unbuilt = []
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
                     mesh='/app/reference.obj', level=None, smooth=True, npts=48, along=None, align_to=None, tol=None, profile=None, kmax=16, scale=None):
        """Sketch of one loop of the mesh's cut by the plane through world point `origin`
        (normal `normal`), drawn where the mesh is: kind 'OUT' (outer boundary) or 'HOLE';
        pick 'largest', 'smallest', or a world point (the loop whose centre is nearest).
        smooth=True: one closed B-spline (one face; for curved outlines): the mesh's facets
        are filtered out (a low-pass fit of the loop, within 0.3% of its size), so a
        faceted mesh gives a smooth outline; an outline with sharp corners keeps them.
        False: polygon (straight edges, sharp corners). level: an expression that moves the sketch along its
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
            if profile is not None and profile in self._rings:
                q = list(self._rings[profile])      # the same measured profile, placed here
            else:
                q = _smooth_ring(q, area, npts, tol=0.003 if tol is None else max(0.003, tol / math.sqrt(max(area, 1e-12))), kmax=kmax) \
                    or _resample(q, npts)
            if align_to is not None and align_to in self._rings and len(self._rings[align_to]) == len(q):
                q = _align(q, self._rings[align_to])
            self._rings[sk.Name] = q
            if scale is not None and scale != 1:
                c_ = sum(q, V()) * (1.0 / len(q))
                q = [c_ + (p - c_) * float(scale) for p in q]
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

    def section_loft(self, name, start, end, n=12, normal=(0, 0, 1), through=None, kind='OUT',
                     pick='largest', bottom=None, top=None, cut=False, mesh='/app/reference.obj', along=None,
                     ruled=None, skip_merged=True, place=None):
        """One feature: a ruled loft through n of the mesh's own loops, cut at n levels from
        `start` to `end` along `normal` (levels = world coordinate along the normal; the plane
        passes through `through`, default the origin shifted to each level). kind 'OUT' for a
        body, 'HOLE' for a cavity (cut=True); pick as in mesh_section ('largest', or a world
        point: the loop whose centre is nearest, at every level). bottom/top: expressions that
        move the first/last section (e.g. top='Height', or 'Height + 1' for a cavity cut that
        must open the rim, bottom='Floor'). along=(dx,dy,dz): a slanted feature's direction;
        bottom/top then move those sections along it. Levels with no such loop are skipped.
        Where the loop changes fast next to an end (a rounded floor or rim), extra levels are
        added there automatically.
        ruled: False (default for a body) = one smooth surface through the sections (no seam at
        each section; falls back to ruled if it breaks the part); True (default for cut=True:
        a smooth cut bulges between sections and can cut through a thin wall). skip_merged=True: an OUT
        section is not taken where another feature (a branch root) merges into the outline:
        such a loop has a local bump that would put that feature's stub into the body (creases,
        excess material); the nearest clean level is used instead."""
        if isinstance(start, str):          # an expression: also drives the first section
            bottom = bottom or start
        if isinstance(end, str):
            top = top or end
        start, end = self.value(start), self.value(end)
        nn = _vec(normal).normalize()
        base = _vec(through) if through is not None else V(0, 0, 0)
        b0 = base.dot(nn)
        if ruled is None:
            ruled = bool(cut)   # a smooth cut overshoots between sections and thins walls; a body loft is smooth
        step = (end - start) / (n - 1)
        tries = [(0.0, 0.0, ruled), (0.0, 0.0, True), (0.3, 0.3, True)] if not ruled else [(0.0, 0.0, True), (0.3, 0.3, True)]
        lv = [start + step * i for i in range(n)]
        dirty = []
        import os as _os
        place = place or _os.environ.get('CADKIT_PLACE', 'even')
        if n > 2:
            # scan the loop densely, then place the sections where the outline changes most
            # (fewer, better-placed sections), never at a level where a branch merges in
            dense = []
            dirty = _merged_levels(mesh, base, nn, b0, start, end, pick, 8 * n, kind=kind, areas=dense)
            if not (skip_merged and kind == 'OUT'):
                dirty = []
            tol_h = 0.5 * abs(end - start) / (8 * n)
            cand = [(h, math.sqrt(a)) for h, a in dense if not any(abs(h - d_) < tol_h for d_ in dirty)]
            if place == 'even' and dirty:
                new_lv = [start]
                for h in lv[1:-1]:
                    near_ = [c for c, _ in cand if c not in new_lv and abs(c - h) < step]
                    if near_:
                        new_lv.append(min(near_, key=lambda c: abs(c - h)))
                lv = sorted(new_lv) + [end]
                n = len(lv)
            if place != 'even' and len(cand) >= n:
                H_ = np.array([c[0] for c in cand])
                R_ = np.array([c[1] for c in cand])
                sel = [0, len(cand) - 1]
                while len(sel) < n - 2 + 2:
                    ss = sorted(sel)
                    err = np.abs(R_ - np.interp(H_, H_[ss], R_[ss]))
                    err[ss] = -1
                    # keep sections apart: not closer than a third of the even spacing
                    for j in range(len(H_)):
                        if min(abs(H_[j] - H_[k_]) for k_ in ss) < abs(step) / 3:
                            err[j] = -1
                    j = int(np.argmax(err))
                    if err[j] < 0:
                        break
                    sel.append(j)
                mids_h = sorted(float(H_[j]) for j in sel[2:])
                lv = [start] + mids_h + [end]
                n = len(lv)
            if dirty:
                _say(f'  {name}: outline merged with another feature (a branch root) at levels '
                     f'{", ".join(f"{d:.2f}" for d in dirty)}: no section there')

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
                                           level=lev2 if j else lev, along=along, align_to=ref,
                                           tol=0.008 * math.sqrt(amax[0]) if amax[0] else None)
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
        for k, (a0, a1, rl) in enumerate(tries):
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
            ar = [self._areas.get(x.Name, 0) for x in sks]
            if not rl and min(ar) < 0.05 * max(ar):
                rl = True     # a near-degenerate section (a pocket tapering to a point): smooth skinning hangs
            f = self.loft(name if k == 0 else f'{name}_{k}', sks, cut=cut, ruled=rl, _report=False)
            quick = f.isValid()
            if quick and not rl:
                # a smooth loft bulges past the sections where the outline changes abruptly (a
                # rim, a flange): keep it only if its volume matches the sections' own
                try:
                    hs_ = [x.Placement.Base.dot(nn) for x in sks]
                    est = sum((ar[i] + ar[i + 1] + math.sqrt(ar[i] * ar[i + 1])) / 3 * abs(hs_[i + 1] - hs_[i])
                              for i in range(len(sks) - 1))
                    dv_ = abs(f.AddSubShape.Volume - est) / est
                    if dv_ > 0.01:
                        quick = False
                        _say(f'  {name}: the smooth loft differs {100 * dv_:.1f}% in volume from its sections (it bulges between them)')
                except Exception:  # noqa: BLE001
                    quick = False
            if quick:
                try:
                    f.AddSubShape.check(True)
                except Exception:  # noqa: BLE001
                    quick = False
            n_before = len(self._broken)
            if (quick or k == len(tries) - 1) and (rl or quick):
                self._quiet = False
                areas = ', '.join(f'{self._areas.get(x.Name, 0):.4g}' for x in sks)
                _say(f'  {name}: {len(sks)} sections from {lv[0]:.3f} to {lv[-1]:.3f} along {tuple(round(c, 3) for c in nn)}, '
                     f'{"ruled" if rl else "smooth"}, loop areas {areas}')
                self._done(f)
                if self.status()[0] or k == len(tries) - 1:
                    return f
                if quick and len(self.body.Shape.Solids) > 1:
                    return f          # a clean loft that does not reach the part: moving its ends will not help
                del self._broken[n_before:]
                self._quiet = True
            # the loft broke the part: a smooth loft that overshoots, or an end section cut where
            # the outline changes abruptly (a junction or a tapering end): retry ruled, then with
            # the end sections moved inward
            _say(f'  {name}: retrying ' + (f'with the end sections moved inward ({tries[k + 1][0]:.2f}, {tries[k + 1][1]:.2f} of a step)'
                                         if tries[k + 1][0] else 'as a ruled loft'))
            for o in [f, first, last]:
                if o is not None:
                    self.body.removeObject(o)
                    self.doc.removeObject(o.Name)
            self.doc.recompute()

    def branch_loft(self, name, start, direction, length, n=5, root=None, mesh='/app/reference.obj', ruled=False, joint=True, _plan=None):
        """One feature: a straight branch (arm, boss, spout) lofted through its OWN cross-sections,
        cut normal to its axis. start: a world point on its centre line near where it leaves the
        body; direction: toward its free end; length: reach from start to the free end (number or
        expression, e.g. 'BranchLength': it moves the end). The block measures where the branch is
        free of the body (sections there only, never a loop merged with the body). Where the
        branch leaves the body through a flat face (a rim, an end face), it starts ON that face:
        its first section is its own profile carried along its axis onto the face (one exact
        shared plane, so the fuse never has to intersect two nearly tangent free-form surfaces).
        Otherwise that clean section is carried back into the body as the root (`root` deep).
        The free end is closed by a smooth tip feature through the mesh's own tip sections (or
        the end section shrunk to their areas). If no way of joining it leaves one clean solid,
        the branch is left out (NOT BUILT, with what to retry) and the part goes on without it."""
        p0, d = _vec(start), _vec(direction).normalize()
        L0 = self.value(length)

        def scan(p0, d):
            rows, cens = [], {}
            for t in np.linspace(-0.4 * L0, 1.3 * L0, 69):
                o = p0 + d * float(t)
                loops = _cut(mesh, o, d, 'OUT')
                if not loops:
                    rows.append((float(t), 0.0, 1e9))
                    continue
                P, A, c = min(loops, key=lambda q: (q[2] - o).Length)
                c = _area_centroid(P, o, d) or c
                cens[float(t)] = c
                rows.append((float(t), A, (c - o).Length))
            mid = [A for t, A, e in rows if 0.25 * L0 <= t <= 0.75 * L0 and A > 0]
            if not mid:
                raise ValueError(f'{name}: no branch section between 25% and 75% of its length from {tuple(start)} along {tuple(direction)}')
            Am = float(np.median(mid))
            free = [t for t, A, e in rows if abs(A - Am) <= 0.15 * Am and e <= 0.35 * math.sqrt(Am)]
            ta_, tb_ = min(free), max(free)
            # the free part ends where the section starts to change abruptly (a tip, a joint):
            # from the middle outward, stop at a step of more than 2% of the section
            R_ = [(t, A) for t, A, e in rows if ta_ <= t <= tb_]
            im = min(range(len(R_)), key=lambda i: abs(R_[i][0] - 0.5 * (ta_ + tb_)))
            j = im
            while j + 1 < len(R_) and abs(R_[j + 1][1] - R_[j][1]) <= 0.02 * Am:
                j += 1
            tb_ = R_[j][0]
            j = im
            while j > 0 and abs(R_[j - 1][1] - R_[j][1]) <= 0.02 * Am:
                j -= 1
            ta_ = R_[j][0]
            return rows, cens, Am, ta_, tb_
        rows, cens, Am, t_a, t_b = scan(p0, d)
        # the branch's own axis: the line through the centres of its free sections (the
        # direction given may be off by a degree, which shifts the far end by a millimetre)
        C = np.array([[cens[t].x, cens[t].y, cens[t].z] for t, A, e in rows if t_a <= t <= t_b and t in cens])
        if len(C) >= 4:
            mu = C.mean(0)
            dn = np.linalg.svd(C - mu)[2][0]
            dn = V(*[float(x) for x in dn]).normalize()
            if dn.dot(d) < 0:
                dn = dn * -1
            if dn.dot(d) > math.cos(math.radians(10)):
                mu = V(*[float(x) for x in mu])
                p0 = mu + dn * dn.dot(p0 - mu)
                d = dn
                rows, cens, Am, t_a, t_b = scan(p0, d)
        u, v, _ = _frame(d)
        # the free end: the farthest mesh point near the axis
        import Mesh
        if mesh not in _MESHES:
            _MESHES[mesh] = Mesh.Mesh(mesh)
        Pm = np.array([[q.x, q.y, q.z] for q in _MESHES[mesh].Points])
        dv = np.array([d.x, d.y, d.z])
        tv = (Pm - np.array([p0.x, p0.y, p0.z])) @ dv
        rv = np.linalg.norm(Pm - np.array([p0.x, p0.y, p0.z]) - np.outer(tv, dv), axis=1)
        reach = 1.5 * math.sqrt(Am) + max((e for t, A, e in rows if t_a <= t <= t_b), default=0)
        width = 2 * float(np.percentile(rv[(tv > t_a) & (tv < t_b) & (rv < 4 * math.sqrt(Am))], 95)) if ((tv > t_a) & (tv < t_b)).any() else math.sqrt(Am)
        sel = (rv <= max(width, reach)) & (tv > t_b)
        t_e = float(tv[sel].max()) if sel.any() else t_b
        if root is None:
            root = math.sqrt(Am) + 0.5 * max(width, math.sqrt(Am))
        p0d = p0.dot(d)
        driven = isinstance(length, str)
        if abs(t_e - L0) > 0.03 * L0:
            _say(f'  NOTE {name}: the mesh\'s free end is {t_e:.3f} from start along the axis, the length given is {L0:.3f}: '
                 f'set the length parameter to {t_e:.3f}')
        # where the branch's axis leaves the part built so far: if through a flat face (a rim,
        # an end face), the branch starts ON that face: its first section is its own profile
        # carried along its axis onto the face (an exact shared plane, no surface crossing)
        joint = self._exit_face(p0, d, t_a - 2 * root, t_b) if joint else None
        t1 = None
        if joint is not None:
            X, nP = joint
            marg = 0.05 * math.sqrt(Am)
            for t in [t for t, A, e in rows if t_a <= t <= t_b]:
                lp = _cut(mesh, p0 + d * float(t), d, 'OUT')
                if not lp:
                    continue
                ring = min(lp, key=lambda q: (q[2] - (p0 + d * float(t))).Length)[0]
                if min((p_ - X).dot(nP) for p_ in ring) >= marg:
                    t1 = float(t)
                    break
            if t1 is None:
                joint = None
        lo_ = t1 if t1 is not None else t_a
        fa = [A for t, A, e in rows if lo_ <= t <= t_b]
        const = max(fa) - min(fa) <= 0.06 * Am      # a constant section: one profile, extruded
        t_mid = min((t for t, A, e in rows if lo_ <= t <= t_b), key=lambda t: abs(t - (lo_ + t_b) / 2))
        if const and f'{name}Profile' not in self._rings:
            om = p0 + d * float(t_mid)
            ref_ = self.mesh_section(f'{name}Profile', (om.x, om.y, om.z), (d.x, d.y, d.z), 'OUT', (om.x, om.y, om.z), mesh=mesh,
                                     npts=48)
            self.body.removeObject(ref_)
            self.doc.removeObject(ref_.Name)

        def build(tag, rdepth, rl, on_face=False, own=False):
            if on_face:
                # a constant section: the root on the face and the last full section make an
                # exact prism (one face, no ripples); otherwise the sections from t1 on
                levels = list(np.linspace(t1, t_b, max(n, 2)))
            else:
                levels = [t_a - rdepth] + list(np.linspace(t_a, t_b, max(n, 2)))
            sks, prev = [], None
            self._quiet = True
            for i, t in enumerate(levels):
                tt = t_a if i == 0 and not on_face else t
                o = p0 + d * float(tt)
                lev = None
                if i == 0 and not on_face:
                    lev = p0d + t                       # the root: the first clean section, moved into the body
                elif driven and t >= t_b - 1e-9:
                    lev = f'{p0d + t - L0:.6g} + ({length})'
                prof = f'{name}Profile' if const and t <= t_b + 1e-9 and not own else None
                try:
                    sk = self.mesh_section(f'{name}{tag}S{i}', (o.x, o.y, o.z), (d.x, d.y, d.z), 'OUT', (o.x, o.y, o.z), mesh=mesh,
                                           level=lev, align_to=prev.Name if prev is not None else None, profile=prof)
                except ValueError:
                    continue
                if i > 0 and self._areas.get(sk.Name, 0) < 0.25 * Am:
                    self.body.removeObject(sk)
                    self.doc.removeObject(sk.Name)
                    continue
                sks.append(sk)
                prev = sk
            self._quiet = False
            if len(sks) < (1 if on_face else 2):
                raise ValueError(f'{name}: fewer than 2 clean sections')
            if on_face:
                # the root: the first section's own points carried along the axis onto the face
                # (the same curve mapped by that projection: same knots, projected poles, so the
                # loft between them is an exact prism, without twist)
                X, nP = joint
                self.doc.recompute()
                if own:
                    o_, u_, v_, _ = self._frames[sks[0].Name]
                    ring = [o_ + u_ * q_.x + v_ * q_.y for q_ in self._rings[sks[0].Name]]
                    ring = [p_ - d * ((p_ - X).dot(nP) / d.dot(nP)) for p_ in ring]
                    sks.insert(0, self._ring_sketch(f'{name}{tag}Root', ring, X, nP))
                else:
                    c_ = sks[0].Shape.Edges[0].Curve
                    poles = [p_ - d * ((p_ - X).dot(nP) / d.dot(nP)) for p_ in c_.getPoles()]
                    rk = self._sketch(f'{name}{tag}Root', (X.x, X.y, X.z), (nP.x, nP.y, nP.z))
                    bs = Part.BSplineCurve()
                    bs.buildFromPolesMultsKnots([self._local(rk, p_) for p_ in poles], c_.getMultiplicities(), c_.getKnots(),
                                                c_.isPeriodic(), c_.Degree)
                    rk.addGeometry(bs, False)
                    self.doc.recompute()
                    self._areas[rk.Name] = Part.Face(rk.Shape.Wires[0]).Area
                    sks.insert(0, rk)
            _say(f'  {name}: free of the body from {t_a:.3f} to {t_b:.3f} along its axis (section area {Am:.4g}{", constant: one profile" if const else ""}), '
                 + (f'starts on the flat face it leaves at ({joint[0].x:.3f}, {joint[0].y:.3f}, {joint[0].z:.3f}), '
                    if on_face else f'root {rdepth:.3f} into the body, ')
                 + f'free end at {t_e:.3f}; {len(sks)} sections, {"ruled" if rl else "smooth"}')
            return self.loft(f'{name}{tag}' if tag else name, sks, ruled=rl), sks

        def clear(objs):
            for o in objs:
                try:
                    if o is not None and self.doc.getObject(o.Name) is not None:
                        self.body.removeObject(o)
                        self.doc.removeObject(o.Name)
                except Exception:  # noqa: BLE001
                    pass

        def describe(p_):
            return ('starting on the flat face it leaves' if p_[3] else f'its root {p_[1]:.3f} into the body') + \
                (', ruled' if p_[2] else ', smooth')

        plan = []
        if joint is not None:
            plan += [('', 0.0, True, True, True), ('_0', 0.0, True, True, False)]
        plan += [('_1', root, ruled, False)] + ([('_2', root, True, False)] if not ruled else []) + \
            [('_3', 0.5 * root, True, False), ('_4', 1.6 * root, True, False)]
        plan = [p_ if len(p_) == 5 else p_ + (False,) for p_ in plan]
        if _plan is not None:
            plan = [(t_, root * f_, r_, False, False) for t_, f_, r_ in _plan]
        tipargs = (d, t_b, t_e, Am, mesh, length, driven, p0, p0d, L0)
        for k, (tag, rd, rl, onf, own) in enumerate(plan):
            nb = len(self._broken)
            f, sks = None, []
            try:
                f, sks = build(tag, rd, rl, on_face=onf, own=own)
            except Exception as e:  # noqa: BLE001  (a fuse that leaves a void shape)
                _say(f'  {name}: {str(e)[:120]}')
                f = self.doc.getObject(f'{name}{tag}' if tag else name)
                sks = [o for o in self.body.Group if o.Name.startswith(f'{name}{tag}S') or o.Name == f'{name}{tag}Root']
                if f is not None and f.Name not in self._broken[nb:]:
                    self._broken.append(f.Name)
            if f is not None and len(self._broken) == nb and self.status()[0]:
                self._branch_tip(name, sks[-1], *tipargs)
                return f
            if f is not None and rl and not onf and self._unsmooth(f):
                del self._broken[nb:]
                self._branch_tip(name, sks[-1], *tipargs)
                return f
            # it broke the part: take it out so the features after it build on a clean part
            del self._broken[nb:]
            clear([f] + sks)
            self.doc.recompute()
            if k < len(plan) - 1:
                _say(f'  {name}: it broke the part; retrying with ' + describe(plan[k + 1]))
        cuts_before = [o.Name for o in self.body.Group if o.TypeId in ('PartDesign::SubtractiveLoft', 'PartDesign::Pocket',
                                                                       'PartDesign::Groove', 'PartDesign::SubtractivePipe')]
        self._unbuilt.append(name)
        _say(f'  -> {name} NOT BUILT: no way of joining it to the part gave one clean solid; the part goes on without it. '
             + (f'Move it before the cuts {cuts_before} in build.py (body, branches, then cuts) and run again.' if cuts_before else
                f'Retry it once with start= a point on its centre line about one section width further toward its free end '
                f'(or root= half the default).'))
        return None

    def _branch_tip(self, name, end_sk, d, t_b, t_e, Am, mesh, length, driven, p0, p0d, L0):
        """Close a branch's free end like the mesh does (a rounded or tapered tip): a smooth loft
        from its last full section through the mesh's own tip sections (or, if that does not
        fuse, that section shrunk to their areas). Kept only if the part stays one clean solid;
        otherwise the end stays flat."""
        if t_e - t_b < 0.1 * math.sqrt(Am) or end_sk is None or end_sk.Name not in self._rings:
            return None
        a0 = self._areas.get(end_sk.Name) or Am
        for mode in ('own', 'shrunk'):
            sks = []
            self._quiet = True
            try:
                for j, f_ in enumerate((0.0, 0.35, 0.65, 0.88)):
                    t = t_b + f_ * (t_e - t_b)
                    o = p0 + d * float(t)
                    lev = f'{p0d + t - L0:.6g} + ({length})' if driven else None
                    tag = f'{name}Tip{mode[0].upper()}S{j}'
                    if f_ > 0 and mode == 'own':
                        sk = self.mesh_section(tag, (o.x, o.y, o.z), (d.x, d.y, d.z), 'OUT', (o.x, o.y, o.z), mesh=mesh,
                                               level=lev, align_to=sks[-1].Name)
                        if self._areas.get(sk.Name, 0) < 0.04 * a0:
                            self.body.removeObject(sk)
                            self.doc.removeObject(sk.Name)
                            break
                    else:
                        sc = 1.0
                        if f_ > 0:
                            lp = _cut(mesh, o, d, 'OUT')
                            at = min(lp, key=lambda q: (q[2] - o).Length)[1] if lp else 0.0
                            sc = math.sqrt(at / a0) if at > 0 else math.sqrt(max(1 - f_ ** 2, 0.04))
                            sc = min(max(sc, 0.2), 1.0)
                        sk = self.mesh_section(tag, (o.x, o.y, o.z), (d.x, d.y, d.z), 'OUT', (o.x, o.y, o.z),
                                               mesh=mesh, level=lev, profile=end_sk.Name, scale=sc)
                    sks.append(sk)
            except ValueError:
                pass
            self._quiet = False
            if len(sks) >= 3:
                for rl in (False, True):
                    nb = len(self._broken)
                    f = self.loft(f'{name}Tip' + ('_1' if rl else '') + ('' if mode == 'own' else 'S'), sks, ruled=rl, _report=False)
                    ok = f.isValid()
                    if ok:
                        try:
                            f.AddSubShape.check(True)
                        except Exception:  # noqa: BLE001
                            ok = False
                    if ok:
                        self._quiet = True
                        self._done(f)
                        self._quiet = False
                        if len(self._broken) == nb and self.status()[0]:
                            _say(f'  {name}: tip closed by {"its own tip sections" if mode == "own" else "its end section shrunk"}'
                                 f' ({len(sks)} sections, {"ruled" if rl else "smooth"}) | {f.Name}: faces {len(self.body.Shape.Faces)} volume {self.body.Shape.Volume:.5g}')
                            return f
                    del self._broken[nb:]
                    self.body.removeObject(f)
                    self.doc.removeObject(f.Name)
                    self.doc.recompute()
            for o in sks:
                self.body.removeObject(o)
                self.doc.removeObject(o.Name)
            self.doc.recompute()
        _say(f'  {name}: its tip did not fuse; the branch ends flat at its last full section')
        return None

    def _exit_face(self, p0, d, t0, t1, k=80):
        """(point, outward normal) where the axis p0 + t d last leaves the part built so far,
        when it leaves through a flat face at a fair angle; else None."""
        # against the material the part's additive features put there (a cavity cut before the
        # branch does not change where the branch meets the body's outer faces)
        shapes = []
        for o in self.body.Group:
            if o.TypeId in ('PartDesign::AdditiveLoft', 'PartDesign::Pad', 'PartDesign::AdditivePipe',
                            'PartDesign::Revolution') and o.isValid():
                try:
                    if not o.AddSubShape.isNull() and o.AddSubShape.Solids:
                        shapes.append(o.AddSubShape)
                except Exception:  # noqa: BLE001
                    pass
        ts = np.linspace(t0, t1, k)
        best = None
        for sh in shapes:
            ins = [sh.isInside(p0 + d * float(t), 1e-4, True) for t in ts]
            last = max((i for i, x in enumerate(ins) if x), default=None)
            if last is None or last == k - 1:
                continue
            if best is None or last > best[1]:
                best = (sh, last)
        if best is None:
            return None
        sh, last = best
        a, b = float(ts[last]), float(ts[last + 1])
        for _ in range(40):
            c = 0.5 * (a + b)
            if sh.isInside(p0 + d * c, 1e-4, True):
                a = c
            else:
                b = c
        X = p0 + d * b
        vx = Part.Vertex(X)
        fc = min(sh.Faces, key=lambda f_: f_.distToShape(vx)[0])
        if fc.distToShape(vx)[0] > 1e-2:
            return None
        pl = fc.findPlane() if hasattr(fc, 'findPlane') else None
        if pl is None and not isinstance(fc.Surface, Part.Plane):
            return None
        nP = (pl.Axis if pl is not None else fc.Surface.Axis)
        nP = V(nP.x, nP.y, nP.z).normalize()
        if nP.dot(d) < 0:
            nP = nP * -1
        if nP.dot(d) < 0.25:          # grazing: the branch runs along the face
            return None
        X = X - nP * nP.dot(X - (pl.Position if pl is not None else fc.Surface.Position))
        return X, nP

    def _ring_sketch(self, name, pts, origin, normal):
        """Sketch of one closed smooth curve through world points (in one plane)."""
        sk = self._sketch(name, (origin.x, origin.y, origin.z), (normal.x, normal.y, normal.z))
        q = [self._local(sk, p) for p in pts]
        self._rings[sk.Name] = q
        bs = Part.BSplineCurve()
        bs.interpolate(q, PeriodicFlag=True)
        sk.addGeometry(bs, False)
        a = np.array([[p.x, p.y] for p in q])
        self._areas[sk.Name] = abs(0.5 * float(np.sum(a[:, 0] * np.roll(a[:, 1], -1) - np.roll(a[:, 0], -1) * a[:, 1])))
        return sk

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
        The path is checked first: a point that doubles back or kinks the path at an end is
        dropped, and an end outside the part is carried along the path's own direction into
        the body wall (a tube must start and end inside the material it joins). If the sweep
        still breaks the part, it is retried with a round profile of the same area, then along
        the branch's measured centre line (measure-mesh's PATH). It is never dropped silently:
        if no try joins the part, save() reports it MISSING."""
        dval = self.value(d)
        P0 = [_vec(p) for p in pts]
        P = P0 if cut else self._clean_path(name, P0, dval)
        tries = [(P, d, h, 'your path' + (' (checked)' if P is not P0 else ''))]
        if h is not None:
            tries.append((P, f'sqrt(({d}) * ({h}))' if isinstance(d, str) or isinstance(h, str)
                          else math.sqrt(float(d) * float(h)), None, 'a round profile of the same area'))
        if not cut:
            mp = self._measured_path(P, dval)
            if mp is not None:
                tries.append((mp, d, h, "the branch's measured centre line (measure-mesh PATH)"))
                if h is not None:
                    tries.append((mp, tries[1][1], None, "the measured centre line with a round profile"))
        for k, (p_, d_, h_, what) in enumerate(tries):
            nb = len(self._broken)
            v_before = self.body.Shape.Volume if not self.body.Shape.isNull() else 0.0
            if k:
                _say(f'  {name}: retrying with {what}', flush=True)
            f = self._tube_once(name if k == 0 else f'{name}_{k}', p_, d_, h_, cut)
            if len(self._broken) == nb and not cut:
                # a sweep can fuse into fragments that pass the shape check (spikes where the
                # tube should be): its added volume must be a fair part of the tube's own
                try:
                    own = f.AddSubShape.Volume
                    gain = self.body.Shape.Volume - v_before
                    e_ = f.Spine[0].Shape.Edges[0] if isinstance(f.Spine, tuple) else f.Spine.Shape.Edges[0]
                    dd_, hh_ = self.value(d_), self.value(h_ if h_ is not None else d_)
                    expect = math.pi / 4 * dd_ * hh_ * e_.Length
                    sh_ = self.body.Shape
                    ps_ = [e_.valueAt(e_.FirstParameter + (e_.LastParameter - e_.FirstParameter) * (i_ + 0.5) / 12) for i_ in range(12)]
                    inside_ = sum(sh_.isInside(q_, 1e-4, True) for q_ in ps_) / 12.0
                    if inside_ < 0.8:
                        _say(f'  {name}: only {100 * inside_:.0f}% of its centre line is inside the part (a broken sweep)')
                    if own < 0.5 * expect or gain < 0.1 * expect or inside_ < 0.8:
                        _say(f'  {name}: the sweep added only {gain:.4g} of its {own:.4g} volume (a broken fuse)')
                        self._broken.append(f.Name)
                except Exception:  # noqa: BLE001
                    pass
            if len(self._broken) > nb and not cut and self._unsmooth(f):
                del self._broken[nb:]
            if len(self._broken) == nb:
                if k:
                    _say(f'  {name}: built as {f.Name} with {what}', flush=True)
                return f
            if k == len(tries) - 1:
                if not cut:
                    del self._broken[nb:]
                    self._remove_tube(f)
                    self._unbuilt.append(name)
                    _say(f'  -> {name} NOT BUILT: no path joined the part as one clean solid. Retry with the PATH '
                         f'measure-mesh printed for this branch, as printed (its ends are already in the body wall), '
                         f'and build the tube before the cavity cuts', flush=True)
                return f
            self._quiet = False
            del self._broken[nb:]
            self._remove_tube(f)

    def _remove_tube(self, f):
        for o in [f, f.Profile[0] if isinstance(f.Profile, tuple) else f.Profile, f.Spine[0] if isinstance(f.Spine, tuple) else f.Spine]:
            try:
                self.body.removeObject(o)
                self.doc.removeObject(o.Name)
            except Exception:  # noqa: BLE001
                pass
        self.doc.recompute()

    def _clean_path(self, name, P, dval):
        """drop repeated points, points that double back or kink the path, and carry ends that
        lie outside the part into the body wall along the path's own direction"""
        notes = []
        Q = [P[0]]
        for p in P[1:]:
            if (p - Q[-1]).Length > 0.15 * dval:
                Q.append(p)

        def turn(a, b, c):
            u, v = b - a, c - b
            if u.Length < 1e-12 or v.Length < 1e-12:
                return 0.0
            return math.degrees(u.getAngle(v))
        for end in (-1, 0):                     # an end point that turns sharply away
            for _ in range(2):
                if len(Q) < 4:
                    break
                a, b, c = (Q[-3], Q[-2], Q[-1]) if end == -1 else (Q[2], Q[1], Q[0])
                t_ = turn(a, b, c)
                if t_ <= 60:
                    break
                notes.append(f'dropped the {"last" if end == -1 else "first"} point {_fmt(c)} (it turns the path by {t_:.0f} deg)')
                Q.pop(end)
        k = 1
        while k < len(Q) - 1 and len(Q) >= 4:   # spikes inside the path
            t_ = turn(Q[k - 1], Q[k], Q[k + 1])
            if t_ > 100:
                notes.append(f'dropped point {_fmt(Q[k])} (the path doubles back there by {t_:.0f} deg)')
                Q.pop(k)
                continue
            k += 1
        sh = self.body.Shape
        if not sh.isNull() and sh.Solids and len(Q) >= 2:
            for end in (0, -1):
                e, nb_ = (Q[0], Q[1]) if end == 0 else (Q[-1], Q[-2])
                if sh.isInside(e, 1e-4, True):
                    if not sh.isInside(nb_, 1e-4, True):   # an end pushed deep into the body: keep it in the wall
                        seg = e - nb_
                        L_ = seg.Length
                        s_in = next((L_ * i_ / 40 for i_ in range(1, 41) if sh.isInside(nb_ + seg * (i_ / 40), 1e-4, True)), None)
                        if s_in is not None and L_ - s_in > 1.0 * dval:
                            q = nb_ + seg * ((s_in + 0.5 * dval) / L_)
                            notes.append(f'moved the {"first" if end == 0 else "last"} end from {_fmt(e)} ({L_ - s_in:.2f} deep '
                                         f'in the body) to {_fmt(q)}, half a diameter into the wall')
                            Q[0 if end == 0 else -1] = q
                    continue
                q = self._carry(sh, e, nb_, dval)
                if q is None:
                    notes.append(f'the {"first" if end == 0 else "last"} point {_fmt(e)} is outside the part and its direction does not reach it')
                    continue
                notes.append(f'carried the {"first" if end == 0 else "last"} end from {_fmt(e)} (outside the part) into the wall at {_fmt(q)}')
                if end == 0:
                    Q.insert(0, q)
                else:
                    Q.append(q)
        if notes:
            _say(f'  {name}: path checked: ' + '; '.join(notes), flush=True)
        return Q

    def _carry(self, sh, e, nb_, dval):
        t = e - nb_
        if t.Length < 1e-12:
            return None
        t.normalize()
        bb = sh.BoundBox
        c = V(bb.Center.x, bb.Center.y, bb.Center.z) - e
        c.normalize()
        for dv in (t, t + c * 0.5, t + c, c):
            dv = V(dv)
            dv.normalize()
            s_in, last = None, None
            for i_ in range(1, 26):
                s_ = 0.1 * i_ * dval
                q = e + dv * s_
                if sh.isInside(q, 1e-4, True):
                    if s_in is None:
                        s_in = s_
                    last = q
                    if s_ - s_in >= 0.5 * dval:
                        break
                elif s_in is not None:
                    break
            if last is not None:
                return last
        return None

    def _measured_path(self, P, dval, mesh='/app/reference.obj'):
        """the measured centre line (branch.py) of the branch nearest to these points, its ends
        carried into the body as it is now; None if measure-mesh found none"""
        import json
        import os
        fn = os.path.join(os.path.dirname(os.path.abspath(mesh)), '.branches.json')
        try:
            found = [b for b in json.load(open(fn)) if b.get('kind') == 'CURVED']
        except Exception:  # noqa: BLE001
            return None
        if not found:
            return None
        cen = sum(P, V()) * (1.0 / len(P))
        b = min(found, key=lambda b_: (V(*np.mean(b_['free'], 0)) - cen).Length)
        Q = [V(*q) for q in b['free']]
        if len(Q) < 2:
            return None
        sh = self.body.Shape
        if not sh.isNull() and sh.Solids:
            q0 = self._carry(sh, Q[0], Q[1], dval)
            q1 = self._carry(sh, Q[-1], Q[-2], dval)
            Q = ([q0] if q0 is not None else []) + Q + ([q1] if q1 is not None else [])
        else:
            Q = [V(*q) for q in b['path']]
        return Q

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

    def _unsmooth(self, f):
        """A feature fused onto a smooth loft can fail where a ruled one fuses cleanly: make the
        earlier smooth lofts ruled and keep f if the part is then one clean solid."""
        smooth = [o for o in self.body.Group if o.TypeId == 'PartDesign::AdditiveLoft' and not o.Ruled and o is not f]
        if not smooth:
            return False
        for o in smooth:
            o.Ruled = True
        self.doc.recompute()
        if self.status()[0]:
            _say(f'  {f.Name}: it did not fuse with the smooth loft {[o.Name for o in smooth]}; that loft is now ruled '
                 f'and the part is one clean solid (faces {len(self.body.Shape.Faces)})')
            return True
        for o in smooth:
            o.Ruled = False
        self.doc.recompute()
        return False

    # ---------- status and save ----------
    def _done(self, f):
        self.doc.recompute()
        s = self.body.Shape
        ok = self._check(s)
        state = '' if f.isValid() else f' INVALID FEATURE: {f.getStatusString()}'
        try:
            bb = s.optimalBoundingBox() if not s.isNull() else None
        except Exception:  # noqa: BLE001  (a broken boolean: an empty or void shape)
            bb = None
            ok = 'FAILED (empty or void shape)'
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
        if self._unbuilt:
            _say(f'NOT BUILT {self._unbuilt}: these branches could not be joined to the part and are missing from the '
                 f'model (see their lines above for what to retry)', flush=True)
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
        missing = self._structure(mesh)
        lm = where.LAST.get('largest_missing', 0.0)
        complete = not missing and lm <= where.MISSING_MAX and not self._unbuilt
        score = path + '.iou'
        prev, prev_complete = None, False
        if os.path.exists(path) and os.path.exists(score):
            t_ = open(score).read().split()
            prev = float(t_[0])
            prev_complete = len(t_) > 1 and t_[1] == 'complete'
        why = ''
        if not valid or self.body.Shape.isNull():
            why = f'not one valid solid (solids {ns})'
        elif prev is not None and prev_complete and not complete:
            why = 'it is INCOMPLETE (a feature is missing) and the saved model is complete'
        elif prev is not None and iou < prev - 0.005 and not (complete and not prev_complete):
            why = f'IoU estimate {iou:.3f} is below the saved model\'s {prev:.3f}'
        if why:
            _say(f'NOT SAVED over {path}: {why}; saved to /app/rejected.FCStd, the previous model'
                 + (f' (IoU estimate {prev:.3f}) stays' if prev is not None else ' stays'), flush=True)
            path, score = '/app/rejected.FCStd', None
        tmp = path[:-6] + '.tmp.FCStd' if path.endswith('.FCStd') else path + '.tmp'
        self.doc.saveAs(tmp)
        os.replace(tmp, path)
        if score:
            open(score, 'w').write(f'{iou:.4f} {"complete" if complete else "incomplete"}')
            try:
                import json
                json.dump(dict(complete=complete, iou=iou, missing=missing, largest_missing=lm,
                               unbuilt=list(self._unbuilt), features=feats), open('/app/.model_status.json', 'w'))
            except OSError:
                pass
        d2 = App.openDocument(path)
        d2.recompute()
        bad = [o.Name for o in d2.Objects if not o.isValid()]
        _say(f'SAVED {path}: one valid solid {valid} (solids {ns}) faces {nf} volume {vol:.5g} '
             f'IoU estimate {iou:.3f} | features {feats} | reopened: invalid objects {bad} | parameters {list(self.params)} | '
             + ('COMPLETE' if complete else 'INCOMPLETE (see below)'), flush=True)
        App.closeDocument(d2.Name)
        if complete:
            _say(f'COMPLETE: every measured branch is in the model and the largest missing piece is {100 * lm:.1f}% '
                 f'(<= {100 * where.MISSING_MAX:.1f}%)', flush=True)
        else:
            why_ = missing + ([f'NOT BUILT {self._unbuilt}'] if self._unbuilt else []) + (
                [f'a missing piece of {100 * lm:.1f}% of the mesh volume (over {100 * where.MISSING_MAX:.1f}%: a feature left out)']
                if lm > where.MISSING_MAX else [])
            _say('INCOMPLETE - this model is NOT done, whatever its IoU: ' + '; '.join(why_), flush=True)
        if valid and iou >= 0.85:
            self._dims()
        return valid

    def _structure(self, mesh):
        """compare the branches measure-mesh found (.branches.json beside the mesh) with the
        model: a branch is there when most of its measured free centre points are inside the
        part. Returns one line per missing branch, saying how to build it."""
        import json
        import os
        fn = os.path.join(os.path.dirname(os.path.abspath(mesh)), '.branches.json')
        try:
            found = json.load(open(fn))
        except Exception:  # noqa: BLE001
            return []
        sh = self.body.Shape
        lines, out = [], []
        for i, b in enumerate(found, 1):
            pts = b.get('free') or []
            if not pts:
                continue
            n_in = 0
            near = 0.5 * float(b.get('deq') or b.get('d') or 0)   # an open or hollow branch: its centre is beside its material
            for q in pts:
                try:
                    if sh.isInside(V(*q), 1e-3, True) or Part.Vertex(V(*q)).distToShape(sh)[0] <= near:
                        n_in += 1
                except Exception:  # noqa: BLE001
                    pass
            ok = n_in >= 0.6 * len(pts)
            lines.append(f'branch {i} ({b["kind"]}) {"in the model" if ok else "MISSING"} ({n_in} of {len(pts)} measured '
                         f'centre points in or next to the model)')
            if not ok:
                if b['kind'] == 'CURVED':
                    how = (f"m.tube('Branch{i}', {[tuple(round(c, 3) for c in p_) for p_ in b['path']]}, "
                           f"'BranchDiameter', {b['h']:.3f}) with BranchDiameter {b['d']:.3f}, before the cavity cuts")
                else:
                    st_, dd_ = b['start'], b['direction']
                    how = (f"m.branch_loft('Branch{i}', ({st_[0]:.3f}, {st_[1]:.3f}, {st_[2]:.3f}), "
                           f"({dd_[0]:.4g}, {dd_[1]:.4g}, {dd_[2]:.4g}), 'BranchLength') with BranchLength {b['reach']:.3f}")
                out.append(f'measured branch {i} is MISSING -> build it: {how}')
        if lines:
            _say(f'STRUCTURE check: the mesh has {len(lines)} branch(es); ' + '; '.join(lines), flush=True)
        return out

    def _dims(self):
        """How each named dimension moves the part (+10%, volume and bounding box; no shape
        check): the part needs two that move it in different ways, one of them its bounding box."""
        def resp():
            sh = self.body.Shape
            b = sh.optimalBoundingBox()
            return np.array([sh.Volume, b.XLength, b.YLength, b.ZLength])
        self.doc.recompute()
        base = resp()
        R = {}
        lines = []
        for nm in self.params:
            v0 = float(self.sheet.get(nm))
            clean = True
            try:
                for fac in (0.9, 1.1):     # a designer changes a dimension both ways; the part must stay one clean solid
                    self.sheet.set(nm, f'{(v0 * fac if v0 else fac - 0.9):.6g}')
                    self.doc.recompute()
                    sh_ = self.body.Shape
                    clean = clean and len(sh_.Solids) == 1 and self._check(sh_) == 'ok' and \
                        not [o for o in self.body.Group if hasattr(o, 'isValid') and not o.isValid()]
                plus = resp()
            except Exception:  # noqa: BLE001
                plus = None
            finally:
                self.sheet.set(nm, f'{v0:.6g}')
                self.doc.recompute()
            try:
                b0 = resp()      # against the part rebuilt at the value itself (a rebuild can differ from the first build)
                r = None if plus is None else (plus - b0) / np.maximum(np.abs(b0), 1e-9)
            except Exception:  # noqa: BLE001
                r = None
            if r is None or not np.isfinite(r).all() or not clean:
                lines.append(f'{nm}: BREAKS the part at -10% or +10% (not one clean solid: it does not count; a feature placed '
                             f'at a fixed number sits on what it moves - build branches before the cuts, or drive another dimension)')
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
        _say('DIMENSIONS (+10% each; -10% and +10% must keep one clean solid): ' + '; '.join(lines) + f' | two that move it differently {pair}, '
             f'one moves the bounding box {box}' + ('' if pair and box else
             ' -> bind another dimension a designer would change (a branch length or diameter, a wall) to its feature'),
             flush=True)


# ---------- geometry helpers ----------
def _fmt(p):
    return f'({p.x:.3f}, {p.y:.3f}, {p.z:.3f})'


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


def _smooth_ring(q, area, k=48, tol=0.003, kmax=16):
    """The loop q without the mesh's facets: a Fourier low-pass of the outline with the
    fewest harmonics that stay within tol (rms, relative to sqrt(area)) of it, sampled
    at k points (as _resample). None when the outline needs more harmonics (sharp corners)."""
    a = np.array([[p.x, p.y] for p in q])
    ac = np.vstack([a, a[:1]])
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(ac, axis=0), axis=1))])
    t = np.linspace(0, s[-1], 257)[:-1]
    z = np.interp(t, s, ac[:, 0]) + 1j * np.interp(t, s, ac[:, 1])
    F = np.fft.fft(z)
    size = math.sqrt(max(area, 1e-12))
    for K in range(2, kmax + 1):
        G = np.zeros_like(F)
        G[:K + 1] = F[:K + 1]
        G[-K:] = F[-K:]
        zz = np.fft.ifft(G)
        if np.sqrt(np.mean(np.abs(zz - z) ** 2)) <= tol * size:
            return _resample([V(c.real, c.imag, 0) for c in zz], k)
    return None


def _merged_levels(mesh, base, nn, b0, start, end, pick, m=40, nang=72, kind='OUT', areas=None):
    """Levels (along nn, between start and end) where the picked OUT loop has a local bump
    that its neighbours do not: another feature (a branch root) merged into the outline.
    Per direction around the body axis, the loop's reach is fitted along the levels with a
    low-order curve; a level whose reach exceeds that fit by > 8% in a few directions only
    (a local bump, not a flange all around) is merged."""
    u, v, _ = _frame(nn)
    hs = np.linspace(start, end, m)[1:-1]
    rows = []
    for h in hs:
        o = base + nn * (h - b0)
        loops = _cut(mesh, o, nn, kind)
        if not loops:
            rows.append(None)
            continue
        if pick == 'largest' or pick == 'smallest':
            L = (max if pick == 'largest' else min)(loops, key=lambda q: q[1])
        else:
            L = min(loops, key=lambda q: (q[2] - _vec(pick)).Length)
        q = np.array([[(p - o).dot(u), (p - o).dot(v)] for p in L[0]])
        rows.append(q)
        if areas is not None:
            areas.append((float(h), float(L[1])))
    ok = [i for i, q in enumerate(rows) if q is not None]
    if len(ok) < 6 or kind != 'OUT':
        return []
    # body axis: a robust line through the loop centres (a bump moves a centre a little)
    C = np.array([rows[i].mean(0) for i in ok])
    H = hs[ok]
    A = np.vstack([H, np.ones_like(H)]).T
    w = np.ones(len(H))
    for _ in range(3):
        cx = np.linalg.lstsq(A * w[:, None], C[:, 0] * w, rcond=None)[0]
        cy = np.linalg.lstsq(A * w[:, None], C[:, 1] * w, rcond=None)[0]
        res = np.hypot(C[:, 0] - A @ cx, C[:, 1] - A @ cy)
        w = (res <= 2.5 * np.median(res) + 1e-9).astype(float)
    R = np.full((len(ok), nang), np.nan)
    for r, i in enumerate(ok):
        q = rows[i]
        qc = np.vstack([q, q[:1]])
        seg = np.linalg.norm(np.diff(qc, axis=0), axis=1)
        sa = np.concatenate([[0], np.cumsum(seg)])
        t = np.linspace(0, sa[-1], 720, endpoint=False)
        pts = np.column_stack([np.interp(t, sa, qc[:, 0]), np.interp(t, sa, qc[:, 1])])
        d = pts - np.array([A[r] @ cx, A[r] @ cy])
        ang = ((np.arctan2(d[:, 1], d[:, 0]) + np.pi) / (2 * np.pi) * nang).astype(int) % nang
        rad = np.hypot(d[:, 0], d[:, 1])
        for j in range(nang):
            sel = rad[ang == j]
            if len(sel):
                R[r, j] = sel.max()
    bad = np.zeros(len(ok), int)
    deg = 3 if len(ok) >= 10 else 2
    for j in range(nang):
        y = R[:, j]
        good = ~np.isnan(y)
        if good.sum() < deg + 3:
            continue
        keep = good.copy()
        for _ in range(4):
            c = np.polyfit(H[keep], y[keep], deg)
            res = y - np.polyval(c, H)
            scale = np.nanmedian(y)
            new = good & (res < max(3 * np.median(np.abs(res[keep])), 0.04 * scale))
            if (new == keep).all():
                break
            keep = new
        bad += (good & (res > 0.08 * np.nanmedian(y))).astype(int)
    return [float(H[r]) for r in range(len(ok)) if 0 < bad[r] <= 0.4 * nang]


def _area_centroid(P, o, n):
    """area centroid (world) of a planar loop of world points P in the plane through o normal n"""
    u, v, _ = _frame(n)
    q = np.array([[(p - o).dot(u), (p - o).dot(v)] for p in P])
    x, y = q[:, 0], q[:, 1]
    cr = x * np.roll(y, -1) - np.roll(x, -1) * y
    a = 0.5 * cr.sum()
    if abs(a) < 1e-12:
        return None
    cx = ((x + np.roll(x, -1)) * cr).sum() / (6 * a)
    cy = ((y + np.roll(y, -1)) * cr).sum() / (6 * a)
    return o + u * float(cx) + v * float(cy)


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
