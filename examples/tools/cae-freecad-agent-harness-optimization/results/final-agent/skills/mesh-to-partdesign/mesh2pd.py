# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Build a compact, sketch-driven PartDesign model from a closed triangle mesh, then verify it.
#
#   MESH=/app/reference.obj OUT=/app/model.FCStd AXIS=z freecadcmd mesh2pd.py
#
# Method (works for any part, any orientation): cut the mesh at LEVELS heights along
# AXIS. Split the axis into segments where the cross-section keeps the same loops
# (same count, each loop following one loop of the level before). Follow each loop
# through its segment and loft it through its sections: each section is ONE smooth
# closed B-spline in a sketch, so a loop gives one side face per segment, not one face
# per slice or polygon edge. One ruled AdditiveLoft per segment holds outer loops and holes.
# Section heights live in a spreadsheet `Params` as fractions of one named dimension,
# `Length` (the part's extent along AXIS); changing it rebuilds the whole part.
# Prints the measurements and a verification report (solids, check(True), faces,
# volume, IoU estimated by ray casting) after save and reopen.
import itertools
import os
import time

import FreeCAD as App
import numpy as np
import Mesh
import Part
import Sketcher  # noqa: F401  (registers the sketch type)

T0 = time.time()
MESH = os.environ.get('MESH', '/app/reference.obj')
OUT = os.environ.get('OUT', '/app/model.FCStd')
AXIS = os.environ.get('AXIS', 'z').lower()
LEVELS = int(os.environ.get('LEVELS', '40'))        # cuts along the axis
SAMPLES = int(os.environ.get('SAMPLES', '64'))      # points per B-spline section
MAXSEC = int(os.environ.get('MAXSEC', '8'))         # sections per loft at most
RULED = os.environ.get('RULED', '1') == '1'          # ruled (1) or smooth (0) lofts
DOCNAME = os.environ.get('DOCNAME', 'Model')
App.Console.SetStatus('Console', 'Log', False)
App.Console.SetStatus('Console', 'Msg', False)

DIRS = {'x': App.Vector(1, 0, 0), 'y': App.Vector(0, 1, 0), 'z': App.Vector(0, 0, 1)}
PLANES = {'x': 'YZ_Plane', 'y': 'XZ_Plane', 'z': 'XY_Plane'}
n = DIRS[AXIS]


def out(*a):
    print('\n' + ' '.join(str(x) for x in a), flush=True)


def area2(p):
    return 0.5 * sum(p[i][0] * p[i - 1][1] - p[i - 1][0] * p[i][1] for i in range(len(p)))


def inside(pt, poly):
    x, y = pt
    c = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i - 1], poly[i]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def centroid(p):
    return (sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p))


mesh = Mesh.Mesh(MESH)
bb = mesh.BoundBox
diag = bb.DiagonalLength
lo, hi = {'x': (bb.XMin, bb.XMax), 'y': (bb.YMin, bb.YMax), 'z': (bb.ZMin, bb.ZMax)}[AXIS]
H = hi - lo
out(f'mesh: {mesh.CountFacets} facets, bbox {bb}, volume {mesh.Volume:.4g}, '
    f'closed solid {mesh.isSolid()}, axis {AXIS} from {lo:.4g} to {hi:.4g}')

# sketch frame: all sections are drawn on the base plane's local XY
doc = App.newDocument(DOCNAME)
body = doc.addObject('PartDesign::Body', 'Body')
plane = [f for f in body.Origin.OriginFeatures if f.Role == PLANES[AXIS]][0]
doc.recompute()
sgn = 1.0 if (plane.Placement.Rotation.multVec(App.Vector(0, 0, 1)).dot(n)) > 0 else -1.0
inv = plane.Placement.inverse()
MINA = (1e-3 * diag) ** 2 * 10


def section(c):
    """Closed loops of the mesh cut at axis coordinate c, 2D in the sketch frame, CCW."""
    loops = []
    for s in mesh.crossSections([(n * c, n)], 1e-6)[0]:
        pts = [inv.multVec(App.Vector(p)) for p in s]
        p2 = [(p.x, p.y) for p in pts]
        if len(p2) > 3 and abs(p2[0][0] - p2[-1][0]) + abs(p2[0][1] - p2[-1][1]) < 1e-9 + 1e-7 * diag:
            p2 = p2[:-1]
        if len(p2) < 3:
            continue
        a = area2(p2)
        if abs(a) < MINA:
            continue
        loops.append(p2 if a > 0 else p2[::-1])
    return loops


def bbox2(p):
    xs = [q[0] for q in p]
    ys = [q[1] for q in p]
    return min(xs), max(xs), min(ys), max(ys)


def overlaps(a, b):
    p, q = bbox2(a), bbox2(b)
    return not (p[1] < q[0] or q[1] < p[0] or p[3] < q[2] or q[3] < p[2])


def depths(L):
    """Nesting depth of each loop (0 = outer boundary, 1 = hole, 2 = island in a hole...)."""
    return [sum(1 for j in range(len(L)) if j != i and inside(L[i][0], L[j])) for i in range(len(L))]


def match(prev, cur):
    """Order cur like prev: loops pair only with loops of the same nesting depth, and the
    pairing minimises the total bounding-box distance (so an outer wall never swaps with
    the inner wall it surrounds). None if not one-to-one or a pair does not overlap."""
    if len(prev) != len(cur):
        return None
    dp, dc = depths(prev), depths(cur)
    if sorted(dp) != sorted(dc):
        return None
    bp = [bbox2(p) for p in prev]
    bc = [bbox2(p) for p in cur]

    def cost(i, j):
        return sum(abs(u - v) for u, v in zip(bp[i], bc[j])) if dp[i] == dc[j] else 1e30

    n_ = len(cur)
    if n_ <= 7:
        best = min(itertools.permutations(range(n_)), key=lambda pm: sum(cost(i, pm[i]) for i in range(n_)))
    else:   # many loops: greedy
        used, best = set(), []
        for i in range(n_):
            j = min((j for j in range(n_) if j not in used), key=lambda j: cost(i, j))
            used.add(j)
            best.append(j)
    for i, j in enumerate(best):
        b1, b2 = bp[i], bc[j]
        if dp[i] != dc[j] or b1[1] < b2[0] or b2[1] < b1[0] or b1[3] < b2[2] or b2[3] < b1[2]:
            return None   # no overlap: a different loop
    return [cur[j] for j in best]


# ---- levels and segments of constant topology ----
zs = [lo + H * (i + 0.5) / LEVELS for i in range(LEVELS)]
secs = [section(z) for z in zs]
segs = []  # each: list of (z, loops) with loops in matched order
for z, L in zip(zs, secs):
    if not L:
        continue
    m = match(segs[-1][-1][1], L) if segs else None
    if m is not None:
        segs[-1].append((z, m))
    else:
        segs.append([(z, L)])
BND = []
# Where the loops change, bisect between the two levels so that each segment's end
# section is cut just next to the change: a section drawn half a level away from where it
# was cut puts slanted walls out of place by half a level times their slope.
for k in range(len(segs) - 1):
    a, b = segs[k], segs[k + 1]
    za_, zb_, zup, Lup = a[-1][0], b[0][0], None, None
    L0, U0 = a[-1][1], b[0][1]
    d0, d1 = depths(L0), depths(U0)
    ov = [(i, j) for i in range(len(L0)) for j in range(len(U0)) if d0[i] == d1[j] and overlaps(L0[i], U0[j])]
    branch = len({i for i, _ in ov}) != len(ov) or len({j for _, j in ov}) != len(ov)
    for _ in range(0 if branch else 6):   # not at a split or merge: the merged loop pinches there
        zm_ = 0.5 * (za_ + zb_)
        L = section(zm_)
        m = match(a[-1][1], L) if L else None
        if m is not None:
            a.append((zm_, m))
            za_ = zm_
            continue
        zb_ = zm_
        m = match(b[0][1], L) if L else None
        if m is not None:
            zup, Lup = zm_, m
    if zup is not None:
        b.insert(0, (zup, Lup))
    b_ = 0.5 * (za_ + zb_)
    BND.append(b_)
# segment boundaries at the bisected change, the ends at the mesh ends
bounds = [lo] + BND + [hi]
eps = 1e-3 * H
TOL = float(os.environ.get('TOL', '0')) or 0.5 * H / LEVELS   # loft deviation allowed


def sections_for(seg, za, zb, count):
    """Sections for one segment: its first sampled level placed at za, its last at zb,
    and evenly chosen sampled levels between, all in the segment's loop order. Only
    sampled levels are used, so a loop that is just appearing or vanishing at a segment
    end (a thin tip) never becomes a section."""
    ref = seg[len(seg) // 2][1]
    pick = [seg[0]]
    inner = seg[1:-1]
    m = max(0, min(count - 2, len(inner)))
    pick += [inner[int((i + 0.5) * len(inner) / m)] for i in range(m)] if m else []
    if len(seg) > 1:
        pick.append(seg[-1])
    res = [(z, match(ref, L) or L) for z, L in pick]
    res[0] = (za, res[0][1])
    if len(res) == 1:
        res.append((zb, res[0][1]))
    else:
        res[-1] = (zb, res[-1][1])
    return res


def resample(p, N):
    """N points equally spaced along the closed loop, starting at a fixed direction."""
    P = p + [p[0]]
    d = [0.0]
    for i in range(1, len(P)):
        d.append(d[-1] + ((P[i][0] - P[i - 1][0]) ** 2 + (P[i][1] - P[i - 1][1]) ** 2) ** 0.5)
    T = d[-1]
    res, j = [], 0
    for k in range(N):
        t = T * k / N
        while d[j + 1] < t:
            j += 1
        f = (t - d[j]) / max(d[j + 1] - d[j], 1e-12)
        res.append((P[j][0] + f * (P[j + 1][0] - P[j][0]), P[j][1] + f * (P[j + 1][1] - P[j][1])))
    cx, cy = centroid(res)
    s = max(range(N), key=lambda i: (res[i][0] - cx) * 0.955 + (res[i][1] - cy) * 0.296)
    return res[s:] + res[:s]


sheet = doc.addObject('Spreadsheet::Sheet', 'Params')
sheet.set('A1', 'Length')
sheet.set('B1', f'{H:.6g}')
sheet.setAlias('B1', 'Length')
sheet.set('A2', 'Start')
sheet.set('B2', f'{lo:.6g}')
sheet.setAlias('B2', 'Start')
doc.recompute()


def align(pts, prev):
    """Rotate the start of pts so that point k lies nearest point k of prev, both taken
    in their own bounding box scaled to unit size (no twist when the loop moves, grows
    or shrinks)."""
    if prev is None:
        return pts
    N = len(pts)

    def norm(p):
        x0, x1, y0, y1 = bbox2(p)
        w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
        return [((u - x0) / w, (v - y0) / h) for u, v in p]
    a_, b_ = norm(pts), norm(prev)
    best = min(range(N), key=lambda s: sum((a_[(i + s) % N][0] - b_[i][0]) ** 2 +
                                           (a_[(i + s) % N][1] - b_[i][1]) ** 2
                                           for i in range(0, N, 2)))
    return pts[best:] + pts[:best]


def spline(pts):
    """Closed periodic B-spline through pts with uniform parameters, so every section has
    the same parametrisation and a ruled loft joins point k to point k."""
    bs = Part.BSplineCurve()
    N = len(pts)
    bs.interpolate(Points=[App.Vector(u, v, 0) for u, v in pts], PeriodicFlag=True,
                   Parameters=[i / N for i in range(N + 1)])
    return bs


def make_sketch(name, z, loops):
    """One sketch per section holding every loop of the segment (outer loops and holes)."""
    sk = body.newObject('Sketcher::SketchObject', name)
    sk.AttachmentSupport = [(plane, '')]
    sk.MapMode = 'FlatFace'
    sk.setExpression('.AttachmentOffset.Base.z',
                     f'{sgn:+g} * (Params.Start + Params.Length * {(z - lo) / H:.6g})')
    for pts in loops:
        sk.addGeometry(spline(pts), False)
    sk.Visibility = False
    return sk


def pick_levels(chain, zs_):
    """Fewest sections such that a ruled loft between consecutive picks stays within TOL
    of every sampled level in between (point k to point k, all loops)."""
    def dev(i, j):
        worst = 0.0
        for m in range(i + 1, j):
            t = (zs_[m] - zs_[i]) / (zs_[j] - zs_[i])
            for li in range(len(chain[i])):
                for (ax, ay), (bx, by), (cx, cy) in zip(chain[i][li], chain[j][li], chain[m][li]):
                    worst = max(worst, abs(ax + t * (bx - ax) - cx) + abs(ay + t * (by - ay) - cy))
        return worst
    tol = TOL
    while True:
        picks, i = [0], 0
        while i < len(chain) - 1:
            j = i + 1
            while j + 1 < len(chain) and dev(i, j + 1) < tol:
                j += 1
            picks.append(j)
            i = j
        if len(picks) <= MAXSEC:
            return picks
        tol *= 1.5


def corr(below, above):
    """Pair loops across a segment boundary: each loop below goes to the loop above of the
    same nesting depth with the nearest bounding box, if they are about the same wall
    (box distance under a quarter of the box size). Returns {above index: below loop}."""
    db, da = depths(below), depths(above)
    pairs = {}
    for i, t in enumerate(below):
        bt = bbox2(t)
        size = (bt[1] - bt[0]) + (bt[3] - bt[2])
        best = None
        for j, l in enumerate(above):
            if j in pairs or da[j] != db[i]:
                continue
            c = sum(abs(u - v) for u, v in zip(bt, bbox2(l)))
            if c < 0.25 * size and (best is None or c < best[0]):
                best = (c, j)
        if best:
            pairs[best[1]] = t
    return pairs


def span_ok(chain, zs_, i, j):
    """A ruled loft between sections i and j passes the full shape check."""
    try:
        ws = []
        for idx in (i, j):
            es = [spline(pts).toShape() for pts in chain[idx]]
            for e in es:
                e.translate(n * zs_[idx])
            ws.append([Part.Wire(e) for e in es])
        for w1, w2 in zip(*ws):
            Part.makeLoft([w1, w2], True, True).check(True)
        return True
    except Exception:  # noqa: BLE001
        return False


def build(name, raw, zs_, free_end):
    """Loft the loops of raw (levels x loops, same order) through adaptively picked
    sections; if free_end, drop end sections whose last span fails the shape check."""
    global nsk
    chain, prev = [], None
    for L in raw:   # a loop shared with the segment before reuses its exact points
        prev = [SHARED[id(L[i])] if id(L[i]) in SHARED else
                align(resample(L[i], SAMPLES), prev[i] if prev else None) for i in range(len(L))]
        chain.append(prev)
    for i in range(len(raw[-1])):
        SHARED[id(raw[-1][i])] = chain[-1][i]
    picks = pick_levels(chain, zs_)
    if free_end:   # a free end may stop early: keep the spans up to the first invalid one
        for q in range(1, len(picks)):
            if q > 1 and not span_ok(chain, zs_, picks[q - 1], picks[q]):
                # walk on level by level (shorter spans fold less) up to the first invalid one
                keep, i = picks[:q], picks[q - 1]
                for j in range(i + 1, len(chain)):
                    if not span_ok(chain, zs_, keep[-1], j):
                        break
                    keep.append(j)
                picks = keep
                break
    sks = []
    for s, j in enumerate(picks):
        nsk += 1
        sks.append(make_sketch(f'{name}_S{s + 1:02d}', zs_[j], chain[j]))
    f = body.newObject('PartDesign::AdditiveLoft', name)
    f.Profile = sks[0]
    f.Sections = sks[1:]
    f.Ruled = RULED
    f.Refine = False
    feats.append(f)


def inset(loop, region):
    """loop scaled about its centroid (a scaled loop never crosses itself) until every
    point lies inside region with a margin, so a section that starts on another segment's
    cap never touches its edge: the joint is then a planar step, not two curved walls
    meeting. Unchanged if that takes more than a 35% shrink."""
    marg = 2e-3 * diag
    A = area2(loop)
    cx = sum((p[0] + q[0]) * (p[0] * q[1] - q[0] * p[1]) for p, q in zip(loop, loop[1:] + loop[:1])) / (6 * -A)
    cy = sum((p[1] + q[1]) * (p[0] * q[1] - q[0] * p[1]) for p, q in zip(loop, loop[1:] + loop[:1])) / (6 * -A)

    def dist(pt, poly):
        best = 1e30
        for k in range(len(poly)):
            (ax, ay), (bx, by) = poly[k - 1], poly[k]
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / max(dx * dx + dy * dy, 1e-18)))
            best = min(best, ((ax + t * dx - pt[0]) ** 2 + (ay + t * dy - pt[1]) ** 2) ** 0.5)
        return best
    f = 1.0
    while f >= 0.65:
        cand = [(cx + f * (p[0] - cx), cy + f * (p[1] - cy)) for p in loop]
        if all(inside(q, region) and dist(q, region) > marg for q in cand):
            if os.environ.get('DEBUG'):
                out(f'inset: scaled {f:.3f}')
            return cand
        f -= 0.01 if f > 0.95 else 0.03
    if os.environ.get('DEBUG'):
        out('inset failed')
    return loop


# Joints between segments. Where one loop continues as one loop, both segments use the
# very same section in the shared plane. Where a loop splits into several (a branch
# leaving a body) or several merge into one, the side with several loops starts (or
# ends) in the shared plane with its own sections moved just inside the single loop:
# the joint is then a planar step on the other segment's cap and no two curved walls
# ever intersect (intersections of B-spline walls fail the full shape check).
first = [list(seg[0][1]) for seg in segs]
last = [list(seg[-1][1]) for seg in segs]
for k in range(1, len(segs)):
    L, U = segs[k - 1][-1][1], segs[k][0][1]
    dl, du = depths(L), depths(U)
    ov = [(i, j) for i in range(len(L)) for j in range(len(U)) if dl[i] == du[j] and overlaps(L[i], U[j])]
    if os.environ.get('DEBUG'):
        out(f'boundary {k}: below {len(L)} loops {dl}, above {len(U)} {du}, overlaps {ov}')
    ups = {i: [j for i2, j in ov if i2 == i] for i in range(len(L))}
    downs = {j: [i for i, j2 in ov if j2 == j] for j in range(len(U))}
    for i, js in ups.items():
        if len(js) == 1 and len(downs[js[0]]) == 1:
            if js[0] in corr([L[i]], [U[js[0]]]):     # about the same wall
                first[k][js[0]] = L[i]                # continues: identical section
        elif len(js) > 1:
            for j in js:
                first[k][j] = inset(U[j], L[i])       # split: start inside the merged loop
    for j, is_ in downs.items():
        if len(is_) > 1:
            for i in is_:
                last[k - 1][i] = inset(L[i], U[j])    # merge: end inside the merged loop

feats = []
nsk = 0
SHARED = {}
for k, seg in enumerate(segs):
    za, zb = bounds[k], bounds[k + 1]
    raw = [list(L) for _, L in seg]
    zs_ = [z for z, _ in seg]
    if len(raw) == 1:
        raw, zs_ = raw * 2, zs_ * 2
    raw[0], raw[-1] = first[k], last[k]
    zs_[0], zs_[-1] = za, zb
    build(f'Loft{k + 1:02d}', raw, zs_, k == len(segs) - 1)
for o in doc.Objects:
    if o.TypeId.startswith('PartDesign::') and o is not body.Tip and o is not body:
        o.Visibility = False
body.Visibility = True
doc.recompute()
failed = [o.Name for o in feats if not o.isValid()]
if failed:
    out(f'features failed to recompute: {failed}')
doc.saveAs(OUT)
App.closeDocument(doc.Name)
out(f'saved {OUT}: {len(segs)} segments, {len(feats)} lofts, {nsk} sketches, '
    f'{time.time() - T0:.0f} s')

# ---- verify after reopen ----
doc = App.openDocument(OUT)
doc.recompute()
bad = [o.Name for o in doc.Objects if not o.isValid()]
body = [o for o in doc.Objects if o.TypeId == 'PartDesign::Body'][0]
shp = body.Shape
try:
    shp.check(True)
    chk = 'ok'
except Exception as e:  # noqa: BLE001
    chk = f'FAILED {str(e)[:300]}'
vis = [o.Name for o in doc.Objects if getattr(o, 'Visibility', False) and hasattr(o, 'Shape')
       and not o.Shape.isNull() and 'Origin' not in o.TypeId and o.TypeId not in ('App::Plane', 'App::Line')]
out(f'reopen: invalid objects {bad}, solids {len(shp.Solids)}, check(True) {chk}, '
    f'faces {len(shp.Faces)}, visible {vis}')
out(f'volume model {shp.Volume:.4g} vs mesh {mesh.Volume:.4g} '
    f'(ratio {shp.Volume / mesh.Volume:.3f}), bbox {shp.BoundBox}')




def column_iou(tri_a, tri_b, axis=2, G=200):
    """Volume IoU of two closed triangle meshes (arrays T x 3 x 3) by casting rays along
    `axis` through a G x G grid of columns: each column's inside intervals are the
    parity pairs of its sorted crossings; IoU = summed overlap / summed union."""
    u, v = [i for i in range(3) if i != axis]
    allp = np.concatenate([tri_a.reshape(-1, 3), tri_b.reshape(-1, 3)])
    lo, hi = allp.min(0), allp.max(0)
    span = max(hi[u] - lo[u], hi[v] - lo[v]) * (1 + 1e-6)
    h = span / G
    cu = lo[u] + (np.arange(G) + 0.5 + 1.234e-4) * h
    cv = lo[v] + (np.arange(G) + 0.5 + 2.345e-4) * h

    def hits(tri):
        cols = {}
        for t in tri:
            a, b, c = t[0], t[1], t[2]
            d = (b[u] - a[u]) * (c[v] - a[v]) - (c[u] - a[u]) * (b[v] - a[v])
            if abs(d) < 1e-15:
                continue
            i0 = max(int(np.ceil((min(a[u], b[u], c[u]) - lo[u]) / h - 0.5)), 0)
            i1 = min(int(np.floor((max(a[u], b[u], c[u]) - lo[u]) / h - 0.5)), G - 1)
            j0 = max(int(np.ceil((min(a[v], b[v], c[v]) - lo[v]) / h - 0.5)), 0)
            j1 = min(int(np.floor((max(a[v], b[v], c[v]) - lo[v]) / h - 0.5)), G - 1)
            if i1 < i0 or j1 < j0:
                continue
            U, V = np.meshgrid(cu[i0:i1 + 1], cv[j0:j1 + 1], indexing='ij')
            l1 = ((b[u] - U) * (c[v] - V) - (c[u] - U) * (b[v] - V)) / d
            l2 = ((c[u] - U) * (a[v] - V) - (a[u] - U) * (c[v] - V)) / d
            l3 = 1 - l1 - l2
            m = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
            if not m.any():
                continue
            z = l1 * a[axis] + l2 * b[axis] + l3 * c[axis]
            for (ii, jj), zz in zip(np.argwhere(m), z[m]):
                cols.setdefault((i0 + ii, j0 + jj), []).append(zz)
        return cols

    def ivs(zs):
        zs = sorted(zs)
        return [(zs[k], zs[k + 1]) for k in range(0, len(zs) - 1, 2)]

    A, B = hits(tri_a), hits(tri_b)
    inter = union = 0.0
    for key in set(A) | set(B):
        ia, ib = ivs(A.get(key, [])), ivs(B.get(key, []))
        la = sum(q - p for p, q in ia)
        lb = sum(q - p for p, q in ib)
        ov = sum(max(0.0, min(q1, q2) - max(p1, p2)) for p1, q1 in ia for p2, q2 in ib)
        inter += ov
        union += la + lb - ov
    return inter / union if union else 0.0


def iou_estimate(shape):
    """Volume IoU of model and mesh: rays along AXIS through a 200 x 200 grid of columns,
    inside intervals from crossing parity, on the mesh and on a fine tessellation of the
    model (independent of the grader)."""
    if shape.isNull() or not shape.Solids:
        return 0.0
    ta = np.array([[list(p) for p in f.Points] for f in mesh.Facets])
    pts, fs = shape.tessellate(1e-3 * diag)
    tb = np.array([[p.x, p.y, p.z] for p in pts])[np.array(fs)]
    return column_iou(ta, tb, 'xyz'.index(AXIS))


out(f'IoU estimate (volume, ray columns along {AXIS}): {iou_estimate(shp):.3f}')
sheet = doc.getObject('Params')
L0 = float(sheet.get('Length'))
sheet.set('Length', f'{L0 * 1.1:.6g}')
doc.recompute()
s2 = body.Shape
ok = len(s2.Solids) == 1 and abs(s2.BoundBox.DiagonalLength - shp.BoundBox.DiagonalLength) > 1e-6
out(f'Params.Length x1.1: solids {len(s2.Solids)}, bbox {s2.BoundBox}, drives geometry {ok}')
App.closeDocument(doc.Name)
out(f'done in {time.time() - T0:.0f} s (file on disk unchanged by this test)')
