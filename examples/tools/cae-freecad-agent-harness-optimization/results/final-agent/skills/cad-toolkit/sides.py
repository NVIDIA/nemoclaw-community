# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Find the features that stick out of the main body (side loops, arms, ribs, bosses, tabs)
and measure each one on its own: its plane, thickness, outline or centre-line path, and the
cross-section cut across it. One call, a few seconds.

    python3 /agent/skills/cad-toolkit/sides.py --axis z      # z = the survey's most regular axis

How: the mesh is cut at many levels across the body axis. Levels whose main loop follows the
body's regular section are 'clean'; the body outline at every level is taken from the nearest
clean level. Surface points of the mesh that lie OUTSIDE that body outline are side-feature
material; they are grouped into connected features and each is measured:

- plane: the feature's thin direction (normal) and its mid-plane, given as the sketch plane to
  use ('XY' / 'XZ' / 'YZ' with its offset) when the normal is a local axis;
- curved (an arm or loop following an arc): arc centre, centre-line radius, start/stop angles
  in that sketch's (u, v), and the section cut ACROSS the arm at its middle (circle/ellipse/
  rect fit). Build it as a revolve of that section about the arc's axis (see SIDES.md);
- straight (rib, boss, tab, gusset): its outline in its mid-plane (corner points, sketch u,v)
  and its thickness. Build it as a symmetric pad of that outline.

Holes through walls are not side features: the survey (sections.py all) lists them as `hole`
loops with their fits and the levels where they start and stop.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fc  # noqa: E402,F401
import FreeCAD as App  # noqa: E402
import Mesh  # noqa: E402
from sections import fit_loop, inside, mesh_loops, shoelace, corners  # noqa: E402

AX = 'xyz'
PLANE = {0: ('YZ', 1, 2, 1.0), 1: ('XZ', 0, 2, -1.0), 2: ('XY', 0, 1, 1.0)}  # normal axis -> sketch


def seg_dist(P, poly):
    """Distance of 2D points P to the closed polygon boundary."""
    a = poly
    b = np.roll(poly, -1, axis=0)
    d = b - a
    L2 = np.maximum((d ** 2).sum(1), 1e-30)
    best = np.full(len(P), np.inf)
    for i0 in range(0, len(P), 2000):
        p = P[i0:i0 + 2000][:, None, :]
        t = np.clip(((p - a[None]) * d[None]).sum(2) / L2[None], 0, 1)
        q = a[None] + t[..., None] * d[None]
        best[i0:i0 + 2000] = np.sqrt(((p - q) ** 2).sum(2)).min(1)
    return best


def inside_many(P, poly):
    x, y = P[:, 0][:, None], P[:, 1][:, None]
    xs, ys = poly[:, 0][None], poly[:, 1][None]
    x2, y2 = np.roll(xs, -1, axis=1), np.roll(ys, -1, axis=1)
    den = np.where(y2 - ys == 0, 1e-30, y2 - ys)
    c = ((ys > y) != (y2 > y)) & (x < (x2 - xs) * (y - ys) / den + xs)
    return c.sum(1) % 2 == 1


def surface_points(V, F, n, rng):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    idx = rng.choice(len(F), n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    return (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]


def components(P, h, min_pts):
    keys = np.floor(P / h).astype(int)
    cells = {}
    for i, k in enumerate(map(tuple, keys)):
        cells.setdefault(k, []).append(i)
    seen, comps = set(), []
    nb = [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)]
    for c0 in cells:
        if c0 in seen:
            continue
        stack, comp = [c0], []
        seen.add(c0)
        while stack:
            c = stack.pop()
            comp.extend(cells[c])
            for d in nb:
                q = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                if q in cells and q not in seen:
                    seen.add(q)
                    stack.append(q)
        if len(comp) >= min_pts:
            comps.append(np.array(comp))
    return sorted(comps, key=len, reverse=True)


def circle_fit(q):
    A = np.c_[2 * q, np.ones(len(q))]
    sol, *_ = np.linalg.lstsq(A, (q ** 2).sum(1), rcond=None)
    c = sol[:2]
    return c, float(np.sqrt(max(sol[2] + c @ c, 1e-30)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--axis', default='z', choices=list(AX), help="the body's axis (survey: most regular axis)")
    ap.add_argument('--frame', default='/app/frame.json')
    ap.add_argument('--n', type=int, default=48, help='levels cut across the body axis')
    ap.add_argument('--tol', type=float, default=0.0, help='outside-the-body margin (default 1.5%% of the section size)')
    a = ap.parse_args()
    fr = json.load(open(a.frame))
    R, origin = np.array(fr['R']), np.array(fr['origin'])
    mesh = Mesh.Mesh(fr['mesh'])
    pts, fac = mesh.Topology
    V = (np.array([[p.x, p.y, p.z] for p in pts]) - origin) @ R.T
    F = np.array(fac, dtype=int)
    ax = AX.index(a.axis)
    oth = [i for i in range(3) if i != ax]
    lo, hi = fr['local_min'][ax], fr['local_max'][ax]
    span = hi - lo
    lv = np.linspace(lo + 0.006 * span, hi - 0.005 * span, a.n)
    mains, nloops, kinds = [], [], []
    for L in lv:
        loops, _ = mesh_loops(mesh, R, origin, ax, float(L))
        if loops is None:
            loops, _ = mesh_loops(mesh, R, origin, ax, float(L) + 1e-3 * span)
        loops = [P[:, oth] for P in (loops or [])]
        items = sorted(((abs(shoelace(p)), p) for p in loops), key=lambda t: -t[0])
        items = [t for t in items if t[0] > 1e-9]
        if not items:
            mains.append(None)
            nloops.append(0)
            kinds.append(None)
            continue
        m = items[0]
        others = [t for t in items[1:] if not inside(t[1].mean(0) if inside(t[1].mean(0), t[1]) else t[1][0], m[1])]
        mains.append(m)
        nloops.append(len(others))
        f = fit_loop(m[1])
        kinds.append(f['kind'] if f['kind'] != 'polygon' else 'polygon' + f['text'].split()[1])
    ok = [i for i, m in enumerate(mains) if m is not None]
    if len(ok) < 3:
        print('too few sections across', a.axis)
        return
    t = lv[ok]
    A = np.array([mains[i][0] for i in ok])
    ks = [kinds[i] for i in ok]
    mode = max(set(ks), key=ks.count)  # the body's own section shape (a merged feature changes it)
    base = np.array([nloops[i] == 0 and kinds[i] == mode for i in ok])
    clean = base.copy()
    for _ in range(3):  # area trend along the axis from the clean levels (body section)
        sel = clean if clean.sum() >= 3 else np.ones(len(ok), bool)
        deg = 2 if sel.sum() >= 6 else 1
        c = np.polyfit(t[sel], A[sel], deg)
        dev = np.abs(A / np.polyval(c, t) - 1)
        clean = clean & (dev < 0.03)
        if clean.sum() < 3:
            clean = base & (dev < np.median(dev[base]) * 1.5 + 1e-3) if base.sum() >= 3 else base
    cidx = [ok[j] for j in range(len(ok)) if clean[j]]
    if not cidx:
        print('no clean body section found along', a.axis, '- try another --axis')
        return
    size = max(float(np.max(mains[i][1].max(0) - mains[i][1].min(0))) for i in cidx)
    tol = a.tol or 0.015 * size
    print(f'body along local {a.axis}: {len(cidx)}/{len(ok)} levels follow the body section; '
          f'feature levels: ' + (', '.join(f'{lv[i]:.2f}' for i in ok if i not in cidx) or 'none'))

    def ref(i):  # body outline at level i: nearest clean level, scaled to the trend area
        j = min(cidx, key=lambda k: abs(lv[k] - lv[i]))
        p = mains[j][1]
        cen = (p.min(0) + p.max(0)) / 2
        s = np.sqrt(max(np.polyval(c, lv[i]), 1e-12) / max(np.polyval(c, lv[j]), 1e-12))
        return cen + (p - cen) * s

    rng = np.random.default_rng(0)
    P = surface_points(V, F, 40000, rng)
    lvl = np.clip(np.searchsorted((lv[1:] + lv[:-1]) / 2, P[:, ax]), 0, len(lv) - 1)
    feat = np.zeros(len(P), bool)
    for i in np.unique(lvl):
        m = lvl == i
        poly = ref(i)
        q = P[m][:, oth]
        out = ~inside_many(q, poly)
        far = seg_dist(q, poly) > tol
        feat[np.where(m)[0]] = out & far
    Q = P[feat]
    if len(Q) < 30:
        print('no side features: every surface point lies on or inside the body outline')
        return
    diag = float(np.linalg.norm(np.array(fr['local_max']) - np.array(fr['local_min'])))
    comps = components(Q, 0.03 * diag, max(30, int(0.02 * len(Q))))
    print(f'{len(comps)} side feature(s) outside the body (coords local; sketch (u,v) as kit planes)')
    for k, ci in enumerate(comps, 1):
        C = Q[ci]
        mu = C.mean(0)
        w, E = np.linalg.eigh(np.cov((C - mu).T))
        n = E[:, 0]
        ext = np.percentile(C, 99, axis=0) - np.percentile(C, 1, axis=0)
        j = int(np.argmin(ext))  # thin direction: designed features sit along the part's axes
        lo3, hi3 = C.min(0), C.max(0)
        print(f'\n[{k}] {len(ci)} pts, local box x[{lo3[0]:.2f},{hi3[0]:.2f}] y[{lo3[1]:.2f},{hi3[1]:.2f}] '
              f'z[{lo3[2]:.2f},{hi3[2]:.2f}]')
        if abs(n[j]) < 0.985 and float(np.ptp((C - mu) @ n)) < 0.8 * float(ext[j]):
            print(f'    note: its thinnest direction {np.round(n, 3).tolist()} is not a local axis '
                  '(a tilted feature): sketch it with K.sketch_at on that plane')
        pl, iu, iv, sgn = PLANE[j]
        tn = np.percentile(C[:, j], [1, 99])
        mid, thick = float(tn.mean()), float(tn[1] - tn[0])
        q2 = C[:, [iu, iv]]
        print(f'    plane: thin along local {AX[j]}: thickness {thick:.3f}, mid-plane {AX[j]}={mid:.3f} '
              f"-> sketch K.sketch(body, '{pl}', offset={sgn * mid:.3f}) (u,v)=({AX[iu]},{AX[iv]})")
        cc, r = circle_fit(q2)
        rr = np.linalg.norm(q2 - cc, axis=1)
        r_lo, r_hi = np.percentile(rr, [10, 90])
        ang = np.degrees(np.arctan2(q2[:, 1] - cc[1], q2[:, 0] - cc[0]))
        hist = np.histogram(ang, bins=72, range=(-180, 180))[0] > 0
        gap = 0
        if hist.all():
            a0, a1 = -180.0, 180.0
        else:  # the arc = the circle minus its largest empty angular gap
            h2 = np.r_[hist, hist]
            best, bi, run = 0, 0, 0
            for i in range(len(h2)):
                run = run + 1 if not h2[i] else 0
                if run > best:
                    best, bi = run, i
            best = min(best, 72)
            a0 = -180 + 5 * ((bi + 1) % 72)
            a1 = a0 + 5 * (72 - best)
            gap = best
        arc = a1 - a0
        bw = r_hi - r_lo
        # an arm/loop leaves the arc's centre empty (a rib or boss fills its outline)
        curved = arc >= 90 and r_lo > 0.45 * r and bw < r and r < 2 * float(np.max(hi3 - lo3))
        if curved and arc >= 355 and j == ax:
            print(f'    RING all around the body (d {2 * r:.3f}, band {bw:.3f}): part of the body profile '
                  '(a lip, flange or the end of the body), not a separate feature: compare the body ends/profile')
            continue
        if curved:
            rm = (r_lo + r_hi) / 2
            am = np.radians((a0 + a1) / 2)
            d2 = np.array([np.cos(am), np.sin(am)])
            pm2 = cc + rm * d2
            p3 = np.zeros(3)
            p3[iu], p3[iv], p3[j] = pm2[0], pm2[1], mid
            tg = np.zeros(3)
            tg[iu], tg[iv] = -d2[1], d2[0]
            o3 = np.zeros(3)
            o3[iu], o3[iv], o3[j] = cc[0], cc[1], mid
            x3 = np.zeros(3)
            x3[iu], x3[iv] = d2[0], d2[1]
            y3 = np.zeros(3)
            y3[j] = 1.0
            sec = ''
            try:
                res = mesh.crossSections([(App.Vector(*(origin + p3 @ R)), App.Vector(*(tg @ R)))], 1e-4)
                best_l, bd = None, 1e30
                for pl_ in res[0]:
                    L3 = (np.array([[v.x, v.y, v.z] for v in pl_]) - origin) @ R.T
                    if len(L3) < 4:
                        continue
                    dd = np.linalg.norm(L3.mean(0) - p3)
                    if dd < bd:
                        best_l, bd = L3, dd
                if best_l is not None and bd < 2 * bw + tol:
                    l2 = np.c_[(best_l - o3) @ x3, (best_l - o3) @ y3]
                    f = fit_loop(l2)
                    sec = f"{f['text']} [err {f['err']:.1f}%]"
            except Exception as e:  # noqa: BLE001
                sec = f'cut failed ({e})'
            print(f'    CURVED arm/loop: arc in that plane, centre (u,v)=({cc[0]:.3f},{cc[1]:.3f}), centre-line '
                  f'radius {rm:.3f}, from {a0:.0f} to {a1:.0f} deg (span {arc:.0f}), band width {bw:.3f}')
            print(f'    section across it at its middle (sketch u = radial from the arc centre, v = local {AX[j]} '
                  f'from the mid-plane): {sec or "n/a: use band width x thickness"}')
            print(f'    build: s = K.sketch_at(body, origin={np.round(o3, 3).tolist()}, xdir={np.round(x3, 4).tolist()}, '
                  f'ydir={np.round(y3, 4).tolist()}); draw the section at u = {rm:.3f}; '
                  f"K.revolve(body, s, angle=span + 2 * overlap, symmetric=True) about V_Axis (= the arc axis)")
        else:
            hp = corners(q2[_hull(q2)], 0.02 * float(np.max(q2.max(0) - q2.min(0))))
            print(f'    STRAIGHT (rib/boss/tab): outline in that plane, convex hull corners (u,v): '
                  + ' '.join(f'({x:.2f},{y:.2f})' for x, y in hp))
            fo = fit_loop(q2[_hull(q2)])
            print(f'    outline fit: {fo["text"]} [err {fo["err"]:.1f}%]; build: pad that outline symmetric, '
                  f'length = thickness {thick:.3f}, extended a little into the body')


def _hull(p):
    """Indices of the 2D convex hull, counter-clockwise (monotone chain)."""
    idx = np.lexsort((p[:, 1], p[:, 0]))

    def cross(o, a_, b_):
        return (p[a_, 0] - p[o, 0]) * (p[b_, 1] - p[o, 1]) - (p[a_, 1] - p[o, 1]) * (p[b_, 0] - p[o, 0])
    lower, upper = [], []
    for i in idx:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], i) <= 0:
            lower.pop()
        lower.append(i)
    for i in idx[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], i) <= 0:
            upper.pop()
        upper.append(i)
    return np.array(lower[:-1] + upper[:-1])


if __name__ == '__main__':
    main()
