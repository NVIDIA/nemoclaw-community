# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Find branches (handles, arms, bosses, tubes) that stand apart from the main body, and
# print each one's centre line as ordered world points with its section size.
#
#   MESH=/app/reference.obj [N=40] freecadcmd branch.py 2>&1 | grep -v '%)'
#
# How: the mesh is cut at N levels along x, y and z. At a level with several OUT loops,
# every small loop outside the body's extent is a branch section; only round-ish ones (cut across
# the branch) are kept. Nearby centres are grouped into branches and each group is
# ordered end to end. The printed points are where the branch is free of the body; extend
# its ends into the body wall yourself so the feature fuses with it.
import os

import FreeCAD as App
import Mesh
import numpy as np

App.Console.SetStatus('Console', 'Log', False)
m = Mesh.Mesh(os.environ.get('MESH', '/app/reference.obj'))
N = int(os.environ.get('N', '40'))
bb = m.BoundBox
lo = np.array([bb.XMin, bb.YMin, bb.ZMin])
hi = np.array([bb.XMax, bb.YMax, bb.ZMax])
TRI = np.array([[list(p) for p in f.Points] for f in m.Facets])
FOUND = []   # what this script finds, written next to the mesh for build-features' checks


def in_mesh(p):
    """is world point p inside the closed mesh (parity of a slightly tilted ray along +z)"""
    d = np.array([1.37e-3, 2.11e-3, 1.0])
    e1, e2 = TRI[:, 1] - TRI[:, 0], TRI[:, 2] - TRI[:, 0]
    h = np.cross(d, e2)
    a = np.einsum('ij,ij->i', e1, h)
    ok = np.abs(a) > 1e-12
    f = np.where(ok, 1.0 / np.where(ok, a, 1), 0)
    s_ = p - TRI[:, 0]
    u = f * np.einsum('ij,ij->i', s_, h)
    q = np.cross(s_, e1)
    v = f * (q @ d)
    t = f * np.einsum('ij,ij->i', e2, q)
    return int(np.sum(ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0))) % 2 == 1


def into_body(end, nxt, dia, centre):
    """carry a branch end into the body: along the branch's own direction at that end (else
    bent toward the part's centre) until inside the material, then about half a diameter on,
    staying in the wall. None if no direction reaches the body within 2.5 diameters."""
    t = end - nxt
    t = t / max(np.linalg.norm(t), 1e-12)
    c = centre - end
    c = c / max(np.linalg.norm(c), 1e-12)
    for dv in (t, t + 0.5 * c, t + c, c):
        dv = dv / max(np.linalg.norm(dv), 1e-12)
        s_in = None
        last = None
        for s in np.arange(0.1, 2.5, 0.1) * dia:
            q = end + dv * s
            if in_mesh(q):
                if s_in is None:
                    s_in = s
                last = q
                if s - s_in >= 0.5 * dia:
                    break
            elif s_in is not None:
                break          # left the wall again (into a cavity): stop in the wall
        if last is not None:
            return last
    return None


def loops_at(axis, t):
    n = np.zeros(3)
    n[axis] = 1
    o = lo.copy()
    o[axis] = t
    res = []
    for s in m.crossSections([(App.Vector(*o), App.Vector(*n))], 1e-6)[0]:
        P = np.array([[p.x, p.y, p.z] for p in s])
        if len(P) > 3 and np.linalg.norm(P[0] - P[-1]) < 1e-9:
            P = P[:-1]
        if len(P) < 4:
            continue
        q = np.delete(P, axis, axis=1)
        a = 0.5 * float(np.sum(q[:, 0] * np.roll(q[:, 1], 1) - np.roll(q[:, 0], 1) * q[:, 1]))
        res.append((P, q, abs(a)))
    return res


def inside(pt, poly):
    x, y = pt
    c = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i - 1], poly[i]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


pts = []   # (centre xyz, equivalent diameter, width, height, axis)
for axis in range(3):
    levels = []
    for t in np.linspace(lo[axis], hi[axis], N + 2)[1:-1]:
        L = loops_at(axis, t)
        outs = []
        for i, (P, q, a) in enumerate(L):
            depth = sum(inside(q[0], L[j][1]) for j in range(len(L)) if j != i)
            if depth % 2 == 0:
                outs.append((P, q, a))
        levels.append(outs)
    big = max((a for outs in levels for _, _, a in outs), default=0)
    boxes = [[(q.min(0), q.max(0)) for _, q, a in outs if a > 0.25 * big] for outs in levels]
    for li, outs in enumerate(levels):
        near = [b for bs in boxes[max(0, li - 2):li + 3] for b in bs]
        for P, q, a in outs:
            if a > 0.25 * big:         # a body section, not a branch
                continue
            c = q.mean(0)
            if any((c >= b0).all() and (c <= b1).all() for b0, b1 in near):
                continue               # within the body's extent here: a wall cut, not a branch
            c = q.mean(0)
            ev = np.sqrt(np.maximum(np.linalg.eigvalsh(np.cov((q - c).T)), 1e-12)) * 2 * np.sqrt(2)
            if ev[1] > 1.6 * ev[0]:      # cut along the branch, not across it
                continue
            pts.append((P.mean(0), 2 * np.sqrt(a / np.pi), ev[1], ev[0], 'xyz'[axis]))

if not pts:
    print('no branches: every level has one outer loop (or branches are cut lengthwise); '
          'a straight branch shows in measure.py as a constant loop with steady drift', flush=True)
    try:
        import json
        with open(os.path.join(os.path.dirname(os.path.abspath(os.environ.get('MESH', '/app/reference.obj'))),
                               '.branches.json'), 'w') as fh:
            json.dump([], fh)
    except OSError:
        pass
    raise SystemExit
C = np.array([p[0] for p in pts])
D = np.array([p[1] for p in pts])
# group: link points closer than 3 equivalent diameters
n = len(C)
lab = list(range(n))


def find(i):
    while lab[i] != i:
        lab[i] = lab[lab[i]]
        i = lab[i]
    return i


for i in range(n):
    for j in range(i + 1, n):
        if np.linalg.norm(C[i] - C[j]) < 3 * max(D[i], D[j]):
            lab[find(i)] = find(j)
groups = {}
for i in range(n):
    groups.setdefault(find(i), []).append(i)
k = 0
for g in sorted(groups.values(), key=len, reverse=True):
    if len(g) < 3:
        continue
    k += 1
    P = C[g]
    # order: longest path through the minimum spanning tree
    m_ = len(g)
    W = np.linalg.norm(P[:, None] - P[None], axis=2)
    inT, par, best = [0], {0: None}, W[0].copy()
    src = np.zeros(m_, int)
    adj = {i: [] for i in range(m_)}
    while len(inT) < m_:
        best[inT] = np.inf
        j = int(np.argmin(best))
        adj[j].append(src[j])
        adj[src[j]].append(j)
        inT.append(j)
        upd = W[j] < best
        best = np.where(upd, W[j], best)
        src = np.where(upd, j, src)

    def far(s):
        dist, prev, st = {s: 0}, {s: None}, [s]
        while st:
            a = st.pop()
            for b in adj[a]:
                if b not in dist:
                    dist[b] = dist[a] + W[a, b]
                    prev[b] = a
                    st.append(b)
        e = max(dist, key=dist.get)
        return e, prev
    a, _ = far(0)
    b, prev = far(a)
    path = []
    while b is not None:
        path.append(b)
        b = prev[b]
    # thin to points about one diameter apart
    dmean = float(np.median(D[g]))
    keep = [path[0]]
    for i in path[1:-1]:
        if np.linalg.norm(P[i] - P[keep[-1]]) > 0.8 * dmean:
            keep.append(i)
    keep.append(path[-1])
    wid = np.median([pts[g[i]][2] for i in path])
    hei = np.median([pts[g[i]][3] for i in path])
    length = sum(np.linalg.norm(P[keep[i + 1]] - P[keep[i]]) for i in range(len(keep) - 1))
    print(f'BRANCH {k}: {len(g)} sections, section about {wid:.3f} x {hei:.3f} (equivalent diameter {dmean:.3f}), '
          f'centre line length {length:.3f}, {len(keep)} ordered centre points (world):')
    print('  [' + ', '.join(f'({P[i][0]:.3f}, {P[i][1]:.3f}, {P[i][2]:.3f})' for i in keep) + ']')
    print(f'  ends: {tuple(round(float(x), 3) for x in P[keep[0]])} and {tuple(round(float(x), 3) for x in P[keep[-1]])}', flush=True)
    # straight or curved?
    Q = P[keep]
    # direction from the centres of one cut axis only (centroids of different cuts of a
    # non-round section differ)
    axs = [pts[g[i]][4] for i in range(len(g))]
    best_ax = max(set(axs), key=axs.count)
    Qa = np.array([P[i] for i in range(len(g)) if axs[i] == best_ax])
    if len(Qa) < 3:
        Qa = Q
    mu = Qa.mean(0)
    d = np.linalg.svd(Qa - mu)[2][0]
    ta = (Qa - mu) @ d                    # ends are distorted where the branch joins or ends:
    lo_, hi_ = np.percentile(ta, [20, 80])  # fit the middle part again
    Qm = Qa[(ta >= lo_) & (ta <= hi_)]
    if len(Qm) >= 3:
        d = np.linalg.svd(Qm - Qm.mean(0))[2][0]
        mu = Qm.mean(0)
    t = (Q - mu) @ d
    off = np.linalg.norm(Q - mu - np.outer(t, d), axis=1).max()
    span = t.max() - t.min()
    if span <= 0 or off > 0.08 * span:
        cm_ = np.array([bb.Center.x, bb.Center.y, bb.Center.z])
        full = [tuple(float(x) for x in q_) for q_ in Q]
        e0 = into_body(Q[0], Q[1], dmean, cm_) if len(Q) > 1 else None
        e1 = into_body(Q[-1], Q[-2], dmean, cm_) if len(Q) > 1 else None
        if e0 is not None:
            full = [tuple(float(x) for x in e0)] + full
        if e1 is not None:
            full = full + [tuple(float(x) for x in e1)]
        ptxt = '[' + ', '.join(f'({p_[0]:.3f}, {p_[1]:.3f}, {p_[2]:.3f})' for p_ in full) + ']'
        print(f'  CURVED (centre line leaves a straight line by {off:.3f}).')
        print(f'  PATH for the tube, its ends already carried into the body wall along the branch\'s own direction '
              f'({"both ends" if e0 is not None and e1 is not None else "WARNING: an end did not reach the body"}): {ptxt}')
        print(f'  SUGGESTED feature: m.param(\'BranchDiameter\', {wid:.3f}); m.tube(\'Branch\', <the PATH above, '
              f'as printed>, \'BranchDiameter\', {hei:.3f})', flush=True)
        FOUND.append(dict(kind='CURVED', free=[list(map(float, q_)) for q_ in Q], path=[list(p_) for p_ in full],
                          d=float(wid), h=float(hei), deq=dmean))
        continue
    # orient d from the body end to the free end (the free end is farther from the mesh centre)
    cm = np.array([m.BoundBox.Center.x, m.BoundBox.Center.y, m.BoundBox.Center.z])
    if np.linalg.norm(Q[np.argmax(t)] - cm) < np.linalg.norm(Q[np.argmin(t)] - cm):
        d = -d
    t = (Q - mu) @ d
    R = 0.75 * max(wid, hei)
    V_ = np.array([[p.x, p.y, p.z] for p in m.Points])
    tv = (V_ - mu) @ d
    rv = np.linalg.norm(V_ - mu - np.outer(tv, d), axis=1)
    near = V_[(rv <= R) & (tv > t.min())]
    k = int(np.argmax(np.abs(d)))               # the world axis the branch runs most along
    sg = 1.0 if d[k] > 0 else -1.0
    ax = 'xyz'[k]
    send = float(sg * (near[:, k] * sg).max())   # its free end along that axis
    s1 = send - sg * 0.3 * dmean * abs(d[k])     # last section just before the free end
    s0 = float(Q[np.argmin(t)][k]) - sg * 0.75 * dmean * abs(d[k])   # first one inside the body
    dd = d / max(np.abs(d).max(), 1e-9)
    nrm = [0, 0, 0]; nrm[k] = 1
    p_start = Q[np.argmin(t)]                   # where it leaves the body
    reach = float(send - p_start[k]) / max(abs(d[k]), 1e-9) * sg
    print(f'  STRAIGHT along direction ({dd[0]:.4g}, {dd[1]:.4g}, {dd[2]:.4g}); its free end reaches {ax} = {send:.3f}. '
          f'Build it from its own sections cut across its axis (the SUGGESTED branch_loft), not as a tube: a tube is round.', flush=True)
    print(f'  SUGGESTED feature (its own measured sections normal to its axis, a root carried into the body, the tip '
          f'closed by its own sections): m.param(\'BranchLength\', {reach:.3f}); '
          f'm.branch_loft(\'Branch\', ({p_start[0]:.3f}, {p_start[1]:.3f}, {p_start[2]:.3f}), '
          f'({dd[0]:.4g}, {dd[1]:.4g}, {dd[2]:.4g}), \'BranchLength\')', flush=True)
    FOUND.append(dict(kind='STRAIGHT', free=[list(map(float, q_)) for q_ in Q], start=[float(x) for x in p_start],
                      direction=[float(x) for x in dd], reach=reach, d=float(wid), h=float(hei), deq=dmean))

try:
    import json
    with open(os.path.join(os.path.dirname(os.path.abspath(os.environ.get('MESH', '/app/reference.obj'))),
                           '.branches.json'), 'w') as fh:
        json.dump(FOUND, fh)
except OSError:
    pass
