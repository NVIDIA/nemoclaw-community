# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Measure a closed triangle mesh: size, volume, wall thickness, principal axes, and the
# loops of cross-sections along one or more axes (each loop: outer or hole, centre,
# half-widths, how round it is, how its centre drifts from level to level).
#
#   MESH=/app/reference.obj AXIS=all N=12 freecadcmd measure.py 2>&1 | grep -v '%)'
#   AXIS = x | y | z | all | "nx,ny,nz" (any direction);  N = number of levels
import math
import os

import FreeCAD as App
import Mesh
import numpy as np

App.Console.SetStatus('Console', 'Log', False)
MESH = os.environ.get('MESH', '/app/reference.obj')
N = int(os.environ.get('N', '12'))
AX = os.environ.get('AXIS', 'all').lower()
m = Mesh.Mesh(MESH)
bb = m.BoundBox
P = np.array([[p.x, p.y, p.z] for p in m.Points])
T = np.array([f.PointIndices for f in m.Facets])
a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
cr = np.cross(b - a, c - a)
area = np.linalg.norm(cr, axis=1).sum() / 2
print(f'\nMESH {MESH}: {m.CountFacets} facets, closed solid {m.isSolid()}')
print(f'bbox x {bb.XMin:.3f}..{bb.XMax:.3f}  y {bb.YMin:.3f}..{bb.YMax:.3f}  z {bb.ZMin:.3f}..{bb.ZMax:.3f}'
      f'  size {bb.XLength:.3f} x {bb.YLength:.3f} x {bb.ZLength:.3f}')
print(f'volume {m.Volume:.4g}  area {area:.4g}  mean wall thickness 2V/A = {2 * m.Volume / area:.3g}'
      f'  (solid fraction of bbox {m.Volume / (bb.XLength * bb.YLength * bb.ZLength):.2f})')
# principal axes of the surface (area weighted)
w = np.linalg.norm(cr, axis=1)
ctr = ((a + b + c) / 3 * w[:, None]).sum(0) / w.sum()
d = (a + b + c) / 3 - ctr
cov = (d * w[:, None]).T @ d / w.sum()
ev, evec = np.linalg.eigh(cov)
print(f'surface centroid ({ctr[0]:.3f}, {ctr[1]:.3f}, {ctr[2]:.3f}); principal axes (largest spread first):')
for k in (2, 1, 0):
    v = evec[:, k]
    print(f'  ({v[0]:+.3f}, {v[1]:+.3f}, {v[2]:+.3f})  spread {math.sqrt(ev[k]):.3g}')


def frame(n):
    n = n / np.linalg.norm(n)
    t = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, t)
    u /= np.linalg.norm(u)
    return n, u, np.cross(n, u)


def area2(q):
    return 0.5 * float(np.sum(q[:, 0] * np.roll(q[:, 1], 1) - np.roll(q[:, 0], 1) * q[:, 1]))


def inside(pt, poly):
    x, y = pt
    cnt = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i - 1], poly[i]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            cnt = not cnt
    return cnt


def describe(q):
    """centre, half-widths along the loop's own principal directions, angle, ellipse deviation"""
    seg = np.linalg.norm(np.diff(np.vstack([q, q[:1]]), axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], 129)[:-1]
    qc = np.vstack([q, q[:1]])
    r = np.column_stack([np.interp(t, s, qc[:, 0]), np.interp(t, s, qc[:, 1])])
    mu = r.mean(0)
    e, V = np.linalg.eigh(np.cov((r - mu).T))
    ax1, ax2 = V[:, 1], V[:, 0]
    p1, p2 = (r - mu) @ ax1, (r - mu) @ ax2
    h1, h2 = (p1.max() - p1.min()) / 2, (p2.max() - p2.min()) / 2
    cen = mu + ax1 * (p1.max() + p1.min()) / 2 + ax2 * (p2.max() + p2.min()) / 2
    x, y = (r - cen) @ ax1, (r - cen) @ ax2
    rho = np.sqrt((x / max(h1, 1e-9)) ** 2 + (y / max(h2, 1e-9)) ** 2)
    dev = float(np.sqrt(np.mean((rho - 1) ** 2)) * (h1 + h2) / 2)
    ang = math.degrees(math.atan2(ax1[1], ax1[0])) % 180
    return cen, h1, h2, ang, dev, s[-1]


NAT = {'x': ('y', 'z'), 'y': ('x', 'z'), 'z': ('x', 'y')}
UNIT = {'x': np.array([1.0, 0, 0]), 'y': np.array([0, 1.0, 0]), 'z': np.array([0, 0, 1.0])}


def levels(n, label):
    if label in NAT:
        u, v = UNIT[NAT[label][0]], UNIT[NAT[label][1]]
    else:
        n, u, v = frame(n)
    proj = P @ n
    lo, hi = proj.min(), proj.max()
    print(f'\nSECTIONS along {label} = ({n[0]:+.3f},{n[1]:+.3f},{n[2]:+.3f}), from {lo:.3f} to {hi:.3f};'
          f' 2D coords (u,v) are world coords projected on u=({u[0]:+.2f},{u[1]:+.2f},{u[2]:+.2f})'
          f' v=({v[0]:+.2f},{v[1]:+.2f},{v[2]:+.2f})' if label not in 'xyz' else
          f'\nSECTIONS along {label}, from {lo:.3f} to {hi:.3f}; loop centres in world coords;'
          f' ang = direction of the first half-width, degrees from +{NAT[label][0]} toward +{NAT[label][1]}')
    print('  kind: OUT = outer boundary, HOLE = hole/cavity inside it; hw = half-widths along the'
          ' loop\'s own axes (angle from first 2D axis); dev = rms distance from that ellipse;'
          ' drift = centre motion per unit of height since the previous level')
    prev = []
    hprev = lo
    stats = []   # per level: (dev/size of the largest loop, has HOLE, number of OUT loops)
    bigs = []    # per level: (level, area of the largest loop)
    holes = []   # (level, world centre, area) of every HOLE loop
    eps = 0.003 * (hi - lo)
    hs = [lo + eps] + [lo + (hi - lo) * (k + 0.5) / N for k in range(N)] + [hi - eps]
    for k, h in enumerate(hs):
        loops = []
        for s in m.crossSections([(App.Vector(*(n * h)), App.Vector(*n))], 1e-6)[0]:
            q3 = np.array([[p.x, p.y, p.z] for p in s])
            if len(q3) < 4:
                continue
            q = np.column_stack([q3 @ u, q3 @ v])
            if np.linalg.norm(q[0] - q[-1]) < 1e-9:
                q = q[:-1]
            A = area2(q)
            if abs(A) < 1e-6 * (bb.DiagonalLength ** 2):
                continue
            loops.append((q, abs(A)))
        polys = [L[0] for L in loops]
        cur = []
        parts = []
        for i, (q, A) in enumerate(loops):
            depth = sum(inside(q[0], polys[j]) for j in range(len(polys)) if j != i)
            cen, h1, h2, ang, dev, per = describe(q)
            w3 = cen[0] * u + cen[1] * v + h * n
            drift = ''
            if prev:
                j = min(range(len(prev)), key=lambda j: np.linalg.norm(prev[j][0] - w3) + abs(prev[j][1] - A) / max(per, 1e-9))
                dd = (w3 - prev[j][0]) / max(h - hprev, 1e-9)
                dd = dd - n * (dd @ n)
                if np.linalg.norm(dd) > 0.05:
                    drift = f' drift ({dd[0]:+.2f},{dd[1]:+.2f},{dd[2]:+.2f})'
            cur.append((w3, A))
            if depth % 2:
                holes.append((h, w3, A))
            parts.append(f"{'HOLE' if depth % 2 else 'OUT'} c=({w3[0]:.2f},{w3[1]:.2f},{w3[2]:.2f}) "
                         f"hw {h1:.2f}x{h2:.2f} ang {ang:.0f} dev {dev:.2f} A {A:.4g}{drift}")
        if loops:
            big = max(range(len(loops)), key=lambda i: loops[i][1])
            _, b1, b2, _, bdev, _ = describe(loops[big][0])
            nh = sum(p.startswith('HOLE') for p in parts)
            stats.append((bdev / max((b1 + b2) / 2, 1e-9), nh > 0, len(parts) - nh))
            bigs.append((h, loops[big][1]))
        prev = cur
        hprev = h
        tag = ' (bottom end)' if k == 0 else ' (top end)' if k == len(hs) - 1 else ''
        print(f'  {label}={h:.3f}{tag}: {len(parts)} loop(s): ' + ' | '.join(parts))
    def largest(h):
        best = 0.0
        for sct in m.crossSections([(App.Vector(*(n * h)), App.Vector(*n))], 1e-6)[0]:
            q3 = np.array([[p.x, p.y, p.z] for p in sct])
            if len(q3) >= 4:
                best = max(best, abs(area2(np.column_stack([q3 @ u, q3 @ v]))))
        return best
    steps = []
    inner = bigs[1:-1]   # the end levels are grazing cuts
    for (h1_, a1), (h2_, a2) in zip(inner, inner[1:]):
        if max(a1, a2) > 4 * min(a1, a2):
            thr = math.sqrt(a1 * a2)
            lo_h, hi_h = h1_, h2_
            for _ in range(14):
                mid = (lo_h + hi_h) / 2
                if (largest(mid) > thr) == (a1 > thr):
                    lo_h = mid
                else:
                    hi_h = mid
            big_side = 'below' if a1 > a2 else 'above'
            steps.append((lo_h + hi_h) / 2)
            STEPS.setdefault(label, []).append(((lo_h + hi_h) / 2, big_side))
            print(f'  STEP at {label}={(lo_h + hi_h) / 2:.3f}: the largest loop changes from area {a1:.4g} to {a2:.4g}; '
                  f'the large feature ends there ({big_side} it); a smaller one (a branch) continues on the other side')
    series = []   # chain HOLE loops of successive levels: nearest pairs first, one per series per level
    for h in sorted(set(x[0] for x in holes)):
        here = [x for x in holes if x[0] == h]
        open_ = [sr for sr in series if sr[-1][0] < h]
        pairs = sorted(((np.linalg.norm((sr[-1][1] - x[1]) - n * ((sr[-1][1] - x[1]) @ n)), si, xi)
                        for si, sr in enumerate(open_) for xi, x in enumerate(here)), key=lambda t: t[0])
        used_s, used_x = set(), set()
        for dist, si, xi in pairs:
            if si in used_s or xi in used_x or dist > 1.5 * math.sqrt(max(open_[si][-1][2], here[xi][2])):
                continue
            open_[si].append(here[xi])
            used_s.add(si)
            used_x.add(xi)
        for xi, x in enumerate(here):
            if xi not in used_x:
                series.append([x])
    series = [sr for sr in series if len(sr) >= 2]

    def hole_near(h, c, A):
        for sct in m.crossSections([(App.Vector(*(n * h)), App.Vector(*n))], 1e-6)[0]:
            q3 = np.array([[p.x, p.y, p.z] for p in sct])
            if len(q3) < 4:
                continue
            w = q3.mean(0)
            if np.linalg.norm((w - c) - n * ((w - c) @ n)) < 1.5 * math.sqrt(A):
                # a loop here near the series: is it a HOLE (inside another loop)?
                q = np.column_stack([q3 @ u, q3 @ v])
                for sct2 in m.crossSections([(App.Vector(*(n * h)), App.Vector(*n))], 1e-6)[0]:
                    q4 = np.array([[p.x, p.y, p.z] for p in sct2])
                    if len(q4) >= 4 and abs(area2(np.column_stack([q4 @ u, q4 @ v]))) > abs(area2(q)) and \
                            inside(q[0], np.column_stack([q4 @ u, q4 @ v])):
                        return True
        return False
    ext = []
    beg = []
    for sr in series:   # refine where each series really ends (bisect toward the next level)
        hl, c, A = sr[-1]
        nxt = [x for x in hs if x > hl + 1e-9]
        hi_h = nxt[0] if nxt else hl
        lo_h = hl
        if hole_near(hi_h, c, A):
            lo_h = hi_h
        else:
            for _ in range(10):
                mid = (lo_h + hi_h) / 2
                if hole_near(mid, c, A):
                    lo_h = mid
                else:
                    hi_h = mid
        ext.append(lo_h)
        h0, c0, A0 = sr[0]   # and where it really starts (bisect toward the previous level)
        prv = [x for x in hs if x < h0 - 1e-9]
        a_h, b_h = (prv[-1] if prv else h0), h0
        for _ in range(10):
            mid = (a_h + b_h) / 2
            if hole_near(mid, c0, A0):
                b_h = mid
            else:
                a_h = mid
        beg.append(b_h)
    series.sort(key=lambda sr: -max(a for _, _, a in sr))
    ENDS[label] = (lo, hi)
    for k, sr in enumerate(series):
        mid = sr[len(sr) // 2][1]
        HOLES.setdefault(label, []).append((beg[k], ext[k], mid, max(a for _, _, a in sr)))
        SERIES.setdefault(label, []).append(f'  HOLE series {k + 1} ({"the largest" if k == 0 else "a smaller cavity or pocket"}): '
              f'{label}={beg[k]:.3f} to {ext[k]:.3f}{" (the top: cut on past it, e.g. top=Height + 1)" if k == 0 and (ext[k] >= hs[-1] - 0.02 * (hi - lo) or any(abs(ext[k] - b) < 0.02 * (hi - lo) for b in steps)) else ""}, area {sr[0][2]:.4g} to {sr[-1][2]:.4g}, '
              f'centre near ({mid[0]:.2f}, {mid[1]:.2f}, {mid[2]:.2f}); its own cut: section_loft(kind=\'HOLE\', '
              f'pick=that centre, cut=True) from where it starts to where it ends')
    if stats:
        rd = float(np.median([t[0] for t in stats]))
        nh = sum(t[1] for t in stats)
        SUMMARY.append((label, rd, nh, len(stats)))
        print(f'  SUMMARY along {label}: largest loop median dev/size {rd:.3f} '
              f'({"ellipse-like" if rd < 0.05 else "free-form"}), HOLE loops at {nh} of {len(stats)} levels')


SUMMARY = []
SERIES = {}
STEPS = {}
HOLES = {}
ENDS = {}
axes = {'x': np.array([1.0, 0, 0]), 'y': np.array([0, 1.0, 0]), 'z': np.array([0, 0, 1.0])}
if AX == 'all':
    for k in 'xyz':
        levels(axes[k], k)
    best = max(SUMMARY, key=lambda t: (t[2] / t[3], -t[1]))
    for line in SERIES.get(best[0], []):
        print(line)
    print(f'\nMAIN AXIS hint: {best[0]} - a cavity opens along the axis whose cuts show HOLE loops '
          f'(cuts along the other axes show it as one U-shaped OUT loop with large dev); with no HOLE '
          f'anywhere, take the axis of the most ellipse-like loops. Build the body from sections across it.')
elif AX in axes:
    levels(axes[AX], AX)
else:
    levels(np.array([float(x) for x in AX.split(',')]), 'h')
if AX != 'all':
    for lines in SERIES.values():
        for line in lines:
            print(line)

if AX == 'all':
    # branches, then the part's structure in a few lines: check it before building
    import runpy
    print()
    os.environ['N'] = os.environ.get('BRANCH_N', '40')   # branch.py's own level count
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'branch.py'), run_name='__main__')
        except SystemExit:
            pass
    btxt = buf.getvalue()
    print(btxt, end='')
    blines = [ln.strip() for ln in btxt.splitlines()]
    ax = best[0]
    lo_, hi_ = ENDS.get(ax, (None, None))
    st = STEPS.get(ax, [])
    print(f'\nSTRUCTURE (check it against the sections above before you build):')
    print(f'  main axis {ax}: the body is built from sections across {ax}, from its bottom end {ax}={lo_:.3f}'
          + (f' to the STEP at {ax}={st[0][0]:.3f} (its own top: a branch continues beyond it; '
             f'the bounding box top {ax}={hi_:.3f} belongs to the branch, not the body)' if st and st[0][1] == 'below'
             else f' to its top end {ax}={hi_:.3f}'))
    for k, (b0, e0, mid, amax_) in enumerate(HOLES.get(ax, [])):
        print(f'  cavity {k + 1}: HOLE loops from {ax}={b0:.3f} (its floor: the cut starts here, not lower) to '
              f'{ax}={e0:.3f}, largest area {amax_:.4g}, a point in it ({mid[0]:.2f}, {mid[1]:.2f}, {mid[2]:.2f})')
    if not HOLES.get(ax):
        print('  no cavity along the main axis')
    nb = 0
    for i, ln in enumerate(blines):
        if ln.startswith('BRANCH '):
            nb += 1
            kind = next((x for x in blines[i + 1:i + 6] if x.startswith(('STRAIGHT', 'CURVED'))), '')
            sug = next((x for x in blines[i + 1:i + 6] if 'SUGGESTED feature' in x), '')
            print(f'  branch {nb}: {ln.split(",")[1].strip() if "," in ln else ""}; '
                  + ('STRAIGHT: build it with ' + sug.split('):', 1)[-1].strip() if kind.startswith('STRAIGHT')
                     else 'CURVED: m.tube through its PATH (BRANCH lines above; its ends are already in the body wall)'))
    if not nb:
        print('  no branch')
    else:
        print(f'  -> the model needs {nb} branch feature(s); m.save checks each measured branch is in the saved model')
    print('  HOLE loops that show only in cuts along another axis, next to a branch, are the opening between '
          'a handle and the body, not holes to cut.')
