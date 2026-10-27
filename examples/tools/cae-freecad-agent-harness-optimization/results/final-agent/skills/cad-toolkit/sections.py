# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Cut the mesh (or a saved model) across one LOCAL axis of frame.json and list the loops.

    python3 /agent/skills/cad-toolkit/sections.py z            # 9 levels across local z
    python3 /agent/skills/cad-toolkit/sections.py x --levels 2.5,10,30
    python3 /agent/skills/cad-toolkit/sections.py z --n 15 --points 12   # + 12 points per loop
    python3 /agent/skills/cad-toolkit/sections.py z --model /app/model.FCStd   # compare areas
    python3 /agent/skills/cad-toolkit/sections.py all          # SURVEY: which body, hollow, side features

Every loop gets a shape fit: circle (diameter), ellipse (full axes, angle), rect (full sides,
corner radius) or polygon (its simplified corner points), with the fit error in % of size.
`all` cuts the three local axes and summarises each: the main loop's shape and size per level,
the hole inside it and the wall between them, extra loops beside it (side features), and the
exact levels where a hole or an extra loop starts or stops (a floor, a closed end, a feature).

For each level: every closed loop with its in-plane extents (local coords of the other two
axes), the extents' midpoint (use it as the centre), the enclosed area, and whether it is a
hole (inside another loop). 'open' = the level grazes a face: shift the level a little. Material area at a level = outer areas - hole areas.
With --model, the same levels are cut through the saved model and the material areas are
compared, so you see WHERE the model is too big or too small.
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


def shoelace(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * (x @ np.roll(y, -1) - y @ np.roll(x, -1))


def inside(pt, poly):
    x, y = pt
    xs, ys = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(xs, -1), np.roll(ys, -1)
    c = ((ys > y) != (y2 > y)) & (x < (x2 - xs) * (y - ys) / np.where(y2 - ys == 0, 1e-30, y2 - ys) + xs)
    return c.sum() % 2 == 1


def mesh_loops(mesh, R, origin, ax, level):
    n = R[ax]
    base = origin + level * n
    try:
        res = mesh.crossSections([(App.Vector(*base), App.Vector(*n))], 1e-4)
    except Exception as e:  # grazing a face can throw: offset slightly
        return None, str(e)
    loops = []
    for pl in res[0]:
        P = np.array([[v.x, v.y, v.z] for v in pl])
        if len(P) < 4:
            continue
        loops.append((P - origin) @ R.T)
    return loops, None


def model_area(shape, R, origin, ax, level):
    n = App.Vector(*R[ax])
    d = float(np.dot(origin, R[ax]) + level)
    try:
        wires = shape.slice(n, d)
    except Exception:
        return None
    import Part
    tot = 0.0
    try:
        faces = [Part.Face(w) for w in wires if w.isClosed()]
        # outer minus holes: sort by area, subtract wires inside a bigger one
        faces.sort(key=lambda f: -f.Area)
        for i, f in enumerate(faces):
            hole = any(g.isInside(f.Vertexes[0].Point, 1e-6, True) for g in faces[:i])
            tot += -f.Area if hole else f.Area
    except Exception:
        return None
    return tot


# ---------- shape fit of one closed loop (2D, local coords) ----------

def resample(p2, n=240):
    p = np.vstack([p2, p2[:1]])
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.r_[0, np.cumsum(seg)]
    t = np.linspace(0, s[-1], n, endpoint=False)
    return np.c_[np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])]


def rdp(p, eps):
    if len(p) < 3:
        return p
    a, b = p[0], p[-1]
    d = b - a
    nd = np.linalg.norm(d)
    dist = (np.abs(d[0] * (p[:, 1] - a[1]) - d[1] * (p[:, 0] - a[0])) / nd if nd > 1e-12
            else np.linalg.norm(p - a, axis=1))
    i = int(np.argmax(dist))
    if dist[i] > eps:
        return np.vstack([rdp(p[:i + 1], eps)[:-1], rdp(p[i:], eps)])
    return np.vstack([a, b])


def corners(q, eps):
    """Closed-loop polygon simplification: the corner points of the outline."""
    i0 = int(np.argmax(np.linalg.norm(q - q.mean(0), axis=1)))
    q = np.roll(q, -i0, axis=0)
    j = int(np.argmax(np.linalg.norm(q - q[0], axis=1)))
    c = np.vstack([rdp(q[:j + 1], eps)[:-1], rdp(np.vstack([q[j:], q[:1]]), eps)[:-1]])
    return c


def fit_loop(p2):
    """Best simple shape for a loop. Returns dict(kind, text, err) with err in % of size."""
    q = resample(p2)
    mn, mx = q.min(0), q.max(0)
    size = float(np.max(mx - mn))
    out = []
    # circle (least squares)
    A = np.c_[2 * q, np.ones(len(q))]
    sol, *_ = np.linalg.lstsq(A, (q ** 2).sum(1), rcond=None)
    cc = sol[:2]
    r = float(np.sqrt(max(sol[2] + cc @ cc, 1e-30)))
    e_c = 100 * np.sqrt(np.mean((np.linalg.norm(q - cc, axis=1) - r) ** 2)) / size
    out.append((e_c, 0, 'circle', f'circle d={2 * r:.3f} centre ({cc[0]:.3f},{cc[1]:.3f})'))
    # principal directions of the boundary; also try the local axes (angle 0)
    cov = np.cov((q - q.mean(0)).T)
    w, Vv = np.linalg.eigh(cov)
    ang_p = float(np.degrees(np.arctan2(Vv[1, 1], Vv[0, 1])))
    for ang in sorted({0.0, round(((ang_p + 90) % 180) - 90, 1)}):
        th = np.radians(ang)
        ux, uy = np.array([np.cos(th), np.sin(th)]), np.array([-np.sin(th), np.cos(th)])
        L = np.c_[q @ ux, q @ uy]
        lo, hi = L.min(0), L.max(0)
        c = (lo + hi) / 2
        a, b = (hi - lo) / 2
        u, v = L[:, 0] - c[0], L[:, 1] - c[1]
        cw = c[0] * ux + c[1] * uy
        tag = '' if ang == 0 else f' angle {ang:.1f} deg'
        rho = np.sqrt((u / a) ** 2 + (v / b) ** 2)
        e_e = 100 * np.sqrt(np.mean(((rho - 1) * np.minimum(a, b)) ** 2)) / size
        out.append((e_e, 1, 'ellipse', f'ellipse {2 * a:.3f} x {2 * b:.3f} (full axes){tag} centre ({cw[0]:.3f},{cw[1]:.3f})'))
        area = abs(shoelace(q))
        rc = float(np.sqrt(max(4 * a * b - area, 0) / (4 - np.pi)))
        rc = min(rc, min(a, b))
        au, av = np.abs(u), np.abs(v)
        inc = (au > a - rc) & (av > b - rc)
        d = np.minimum(np.abs(a - au), np.abs(b - av))
        d[inc] = np.abs(np.hypot(au[inc] - (a - rc), av[inc] - (b - rc)) - rc)
        e_r = 100 * np.sqrt(np.mean(d ** 2)) / size
        rtxt = f' corner radius {rc:.3f}' if rc > 0.02 * min(a, b) else ''
        out.append((e_r, 2, 'rect', f'rect {2 * a:.3f} x {2 * b:.3f}{rtxt}{tag} centre ({cw[0]:.3f},{cw[1]:.3f})'))
    # polygon of corners (always available)
    cp = corners(q, 0.01 * size)
    pts = ' '.join(f'({x:.2f},{y:.2f})' for x, y in cp)
    out.append((0.5, 3 + len(cp), 'polygon', f'polygon {len(cp)} corners {pts}'))
    ok = [t for t in out if t[0] < 1.0]
    best = min(ok, key=lambda t: (t[1], t[0])) if ok else min(out, key=lambda t: t[0])
    return {'kind': best[2], 'text': best[3], 'err': best[0],
            'all': {k: e for e, _, k, _ in sorted(out, reverse=True)}}


def fit_line(f):
    alt = ', '.join(f'{k} {e:.1f}%' for k, e in f['all'].items() if k != 'polygon')
    return f"fit {f['text']}  [err {f['err']:.1f}%; {alt}]"


# ---------- survey: the three axes ----------

def classify(loops):
    """Main outer loop (largest), holes inside it, other outer loops."""
    items = sorted(((abs(shoelace(p)), p) for p in loops), key=lambda t: -t[0])
    items = [t for t in items if t[0] > 1e-9]
    if not items:
        return None, [], []
    main = items[0]
    holes, others = [], []
    for A, p in items[1:]:
        (holes if inside(p.mean(0) if inside(p.mean(0), p) else p[0], main[1]) else others).append((A, p))
    return main, holes, others


def state(mesh, R, origin, ax, other, L):
    loops, err = mesh_loops(mesh, R, origin, ax, L)
    if loops is None:
        return None
    main, holes, others = classify([P[:, other] for P in loops])
    return (main, holes, others)


def key(st):
    """(holes, other loops, size class of the largest hole: 0 small .. 3 most of the main loop)"""
    if st is None or st[0] is None:
        return None
    hc = int(min(3, 4 * max(A for A, _ in st[1]) / st[0][0])) if st[1] else -1
    return (len(st[1]), len(st[2]), hc)


def survey(mesh, R, origin, fr, n):
    scores = []
    for ax in range(3):
        other = [i for i in range(3) if i != ax]
        on = ['xyz'[i] for i in other]
        nm = 'xyz'[ax]
        lo, hi = fr['local_min'][ax], fr['local_max'][ax]
        span = hi - lo
        lv = list(np.linspace(lo + 0.0237 * span, hi - 0.0173 * span, n))  # off the vertex rings
        print(f'\n=== axis {nm}: cuts across local {nm} from {lo:.3f} to {hi:.3f}; loop coords ({on[0]}, {on[1]})')
        sts, kinds, cents, sizes, errs, used, areas = [], [], [], [], [], [], []
        for L in lv:
            st = state(mesh, R, origin, ax, other, L)
            sts.append(st)
            if st is None or st[0] is None:
                print(f'{nm}={L:.3f}: no section')
                continue
            (A, p), holes, others = st
            f = fit_loop(p)
            kinds.append(f['kind'] if f['kind'] != 'polygon' else f"polygon{f['text'].split()[1]}")
            mn, mx = p.min(0), p.max(0)
            cents.append((mn + mx) / 2)
            sizes.append(mx - mn)
            errs.append(f['err'])
            used.append(L)
            areas.append(A)
            print(f'{nm}={L:.3f}: main {fit_line(f)} area {A:.2f}')
            for Ah, h in holes:
                fh = fit_loop(h)
                hm, hx = h.min(0), h.max(0)
                wall = [hm[0] - mn[0], mx[0] - hx[0], hm[1] - mn[1], mx[1] - hx[1]]
                print(f'    hole {fit_line(fh)} area {Ah:.2f}; wall to main: '
                      f'{on[0]}- {wall[0]:.2f} {on[0]}+ {wall[1]:.2f} {on[1]}- {wall[2]:.2f} {on[1]}+ {wall[3]:.2f}')
            for Ao, o in others:
                fo = fit_loop(o)
                print(f'    other loop (beside the main one) {fit_line(fo)} area {Ao:.2f}')
        if not cents:
            continue
        mode = max(set(kinds), key=kinds.count)
        same = kinds.count(mode)
        C, S, Ar = np.array(cents), np.array(sizes), np.array(areas)
        ms = [i for i, k in enumerate(kinds) if k == mode]
        med = float(np.median(Ar[ms]))
        core = [i for i in ms if abs(Ar[i] / med - 1) < 0.03]
        if len(core) >= max(2, len(kinds) / 2):  # one section repeats: the rest are features
            odd = [i for i in range(len(kinds)) if i not in core]
            if odd:
                print(f'    the same main section (area {med:.2f}) at {len(core)}/{len(kinds)} levels; differs at '
                      + ', '.join(f'{nm}={used[i]:.2f} (area {Ar[i]:.2f})' for i in odd)
                      + ' -> features there (holes, slots, ribs): cut them with --levels')
            sel = core
        else:
            sel = ms
        ref = max(float(S.max()), 1e-9)
        drift = float(np.max(np.linalg.norm(C[sel] - C[sel].mean(0), axis=1))) / ref * 100
        svar = float((S[sel].max(0) - S[sel].min(0)).max()) / ref * 100
        print(f'--- axis {nm} summary: main loop {mode} at {same}/{len(kinds)} levels, mean fit err '
              f'{np.mean(errs):.1f}%, centre drift {drift:.1f}%, size change {svar:.1f}% '
              + ('(no regular section along ' + nm + ')' if len(sel) < 3 else
                 f'({"constant section -> pad along " + nm if svar < 2 else "changing section -> loft along " + nm + " (or revolve if circles on a fixed centre)"})'))
        if svar >= 2 and len(used) >= 3:
            if len(sel) >= 3:
                t = np.array(used)[sel]
                dev = max(float(np.max(np.abs(np.polyval(np.polyfit(t, S[sel, j], 1), t) - S[sel, j])))
                          for j in range(2)) / ref * 100
                print(f'    main-loop size vs {nm}: max deviation from a straight taper {dev:.1f}% '
                      f'({"linear: 2 sections, Ruled, are enough" if dev < 1 else "curved: 3-5 sections"})')
        scores.append((len(sel) / len(kinds) if len(sel) >= 3 else 0, -drift, -float(np.mean(errs)), nm, mode))
        # exact levels where the topology changes (hole / other loops appear or vanish)
        for i in range(len(lv) - 1):
            k0, k1 = key(sts[i]), key(sts[i + 1])
            if k0 == k1 or k0 is None or k1 is None:
                continue
            a, b = lv[i], lv[i + 1]
            for _ in range(10):
                m = (a + b) / 2
                km = key(state(mesh, R, origin, ax, other, m))
                if km == k0:
                    a = m
                else:
                    b = m
            print(f'    change at {nm}~{(a + b) / 2:.3f}: (holes, other loops, hole size 0-3) {k0} -> {k1}')
        hl = [L for L, st in zip(lv, sts) if st and st[0] and st[1]]
        if hl:
            print(f'    hollow: a hole inside the main loop at {len(hl)}/{len(lv)} levels ({nm} {min(hl):.2f}..{max(hl):.2f})')
        ol = [L for L, st in zip(lv, sts) if st and st[0] and st[2]]
        if ol:
            print(f'    side feature(s): loops beside the main one at {nm} {min(ol):.2f}..{max(ol):.2f}')
    if scores:
        s = max(scores)
        print(f'\nMost regular axis: {s[3]} (main loop {s[4]} at {s[0] * 100:.0f}% of levels, centre drift '
              f'{-s[1]:.1f}%). Body = this section padded/lofted/revolved along {s[3]}; holes and loops '
              'beside it, and the other axes\' changes, are cavities and side features.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('axis', choices=['x', 'y', 'z', 'all'])
    ap.add_argument('--frame', default='/app/frame.json')
    ap.add_argument('--mesh')
    ap.add_argument('--levels', help='comma-separated local levels')
    ap.add_argument('--n', type=int, default=9, help='number of evenly spaced levels')
    ap.add_argument('--points', type=int, default=0, help='print this many points per loop')
    ap.add_argument('--model', help='saved .FCStd to compare section areas with')
    a = ap.parse_args()
    fr = json.load(open(a.frame))
    R, origin = np.array(fr['R']), np.array(fr['origin'])
    mesh = Mesh.Mesh(a.mesh or fr['mesh'])
    if a.axis == 'all':
        survey(mesh, R, origin, fr, a.n if a.n != 9 else 7)
        return
    ax = 'xyz'.index(a.axis)
    other = [i for i in range(3) if i != ax]
    on = ['xyz'[i] for i in other]
    lo, hi = fr['local_min'][ax], fr['local_max'][ax]
    if a.levels:
        lv = [float(v) for v in a.levels.split(',')]
    else:
        span = hi - lo
        lv = list(np.linspace(lo + 0.02 * span, hi - 0.02 * span, a.n))
    shape = None
    if a.model:
        doc = App.openDocument(a.model)
        vis = [o for o in doc.Objects if getattr(o, 'Visibility', False) and hasattr(o, 'Shape')
               and not o.Shape.isNull() and o.Shape.Solids]
        shape = (vis[0] if vis else doc.Objects[-1]).Shape
    print(f'local {a.axis} from {lo:.3f} to {hi:.3f}; loop coords are local ({on[0]}, {on[1]})')
    for L in lv:
        loops, err = mesh_loops(mesh, R, origin, ax, L)
        if loops is None:
            loops, err = mesh_loops(mesh, R, origin, ax, L + 1e-3 * (hi - lo))
        if loops is None:
            print(f'{a.axis}={L:.3f}: section failed ({err})')
            continue
        items = []
        for P in loops:
            p2 = P[:, other]
            items.append((abs(shoelace(p2)), p2))
        items.sort(key=lambda t: -t[0])
        mat = 0.0
        lines = []
        for i, (A, p2) in enumerate(items):
            hole = any(inside(p2.mean(0) if inside(p2.mean(0), p2) else p2[0], q) for _, q in items[:i])
            mat += -A if hole else A
            mn, mx = p2.min(0), p2.max(0)
            c = (mn + mx) / 2
            kind = 'open ' if A < 1e-9 else 'hole ' if hole else 'outer'
            lines.append(f'   {kind} {on[0]}[{mn[0]:.3f},{mx[0]:.3f}] '
                         f'{on[1]}[{mn[1]:.3f},{mx[1]:.3f}] centre ({c[0]:.3f},{c[1]:.3f}) '
                         f'size {mx[0]-mn[0]:.3f} x {mx[1]-mn[1]:.3f} area {A:.3f} n={len(p2)}')
            if A > 1e-9:
                lines.append('     ' + fit_line(fit_loop(p2)))
            if a.points:
                idx = np.linspace(0, len(p2) - 1, a.points).astype(int)
                lines.append('     pts ' + ' '.join(f'({p2[j,0]:.2f},{p2[j,1]:.2f})' for j in idx))
        cmp_ = ''
        if shape is not None:
            ma = model_area(shape, R, origin, ax, L)
            cmp_ = f'  model area {ma:.3f} ({(ma / mat - 1) * 100:+.1f}%)' if ma is not None and mat else '  model area ?'
        print(f'{a.axis}={L:.3f}: {len(items)} loop(s), material area {mat:.3f}{cmp_}')
        print('\n'.join(lines))


if __name__ == '__main__':
    main()
