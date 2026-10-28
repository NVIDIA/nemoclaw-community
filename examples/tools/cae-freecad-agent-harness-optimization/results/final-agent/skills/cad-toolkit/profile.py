# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Revolve axis and measured half-section of a round body, even with an arm or handle on it.

    python3 /agent/skills/cad-toolkit/profile.py [/app/reference.obj] [--write] [--tol 0.004]

1. Finds the revolve axis: starts from a normal-line fit (every normal line of a surface of
   revolution meets its axis), the PCA axes and the flat-face normals, then tilts and shifts it
   to make the cross-sections round (median over angle, so an arm or handle does not count).
   Prints the roundness: < 0.01 = the body is round about this axis.
2. Cuts the mesh across that axis at many levels and, per level, takes the median over angle of
   the outer and inner radius (an arm covers only a few angles, so it does not move the median).
3. Prints the closed half-section (u = r, v = t) as a point list ready for K.polygon on 'XZ' and
   K.revolve, simplified to --tol x size, with the volume that profile revolves to vs the mesh.
--write replaces /app/frame.json with this axis frame (local z = axis, origin on the axis at the
body's lowest level, local x toward off-axis material), so sketchkit, sections.py and sides.py
all use it; the old frame is kept as /app/frame_measure.json.
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure import load, tri_data  # noqa: E402


def fit_axis(C, A, N):
    """Plucker fit: line (a, m) meets normal line (n, p x n) iff a.(p x n) + m.n = 0."""
    w = np.sqrt(A / A.sum())
    ctr = (A[:, None] * C).sum(0) / A.sum()
    C = C - ctr  # well conditioned: fit about the centroid
    keep = np.ones(len(C), bool)
    scale = np.sqrt((A * np.linalg.norm(C, axis=1) ** 2).sum() / A.sum())
    for _ in range(4):
        B = np.cross(C, N)[keep] * w[keep, None]
        Nw = N[keep] * w[keep, None]
        # eliminate m (m = -N+ B a), then a = least singular vector; |a| = 1 avoids the line at infinity
        Mm = B - Nw @ np.linalg.lstsq(Nw, B, rcond=1e-9)[0]
        a = np.linalg.svd(Mm, full_matrices=False)[2][-1]
        m = -np.linalg.lstsq(Nw, B @ a, rcond=1e-9)[0]
        c = np.cross(a, m)  # point on the axis closest to the origin
        # residual per face: distance between its normal line and the axis
        d = C - c
        cr = np.cross(N, a)
        ncr = np.linalg.norm(cr, axis=1)
        dist = np.where(ncr > 1e-6, np.abs(np.einsum('ij,ij->i', d, cr)) / np.maximum(ncr, 1e-9), 0.0)
        res = dist / scale
        keep = res < max(0.02, 3 * np.median(res[keep]))
    frac = A[keep].sum() / A.sum()
    return a, c + ctr, float(np.median(res[keep])), float(frac)


def axis_point(C, A, N, a):
    """Point of the axis with direction a that the normal lines meet best (linear solve)."""
    w = np.sqrt(A / A.sum())[:, None]
    ctr = (A[:, None] * C).sum(0) / A.sum()
    B = np.cross(C - ctr, N) @ a
    m = -np.linalg.lstsq(N * w, B * w[:, 0], rcond=1e-9)[0]
    c = np.cross(a, m) + ctr
    return c


def edges_of(F):
    E = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    return np.unique(np.sort(E, 1), axis=0)


def cut_points(L, E, t):
    za, zb = L[E[:, 0], 2] - t, L[E[:, 1], 2] - t
    k = za * zb < 0
    a, b = L[E[k, 0]], L[E[k, 1]]
    return a + (b - a) * (za[k] / (za[k] - zb[k]))[:, None]


def ring(P, nb):
    """Per angle bin max and min radius (bins with points only)."""
    r = np.hypot(P[:, 0], P[:, 1])
    b = ((np.arctan2(P[:, 1], P[:, 0]) + np.pi) / (2 * np.pi) * nb).astype(int) % nb
    mx = np.full(nb, np.nan); mn = np.full(nb, np.nan)
    np.fmax.at(mx, b, r); np.fmin.at(mn, b, r)
    return mx, mn


def section_radii(L, E, levels, nb=48):
    """Per level: (outer, inner or None) as medians over angle bins; None where no loop surrounds the axis."""
    out = []
    for t in levels:
        P = cut_points(L, E, t)
        if len(P) < 6:
            out.append(None); continue
        mx, mn = ring(P, nb)
        ok = ~np.isnan(mx)
        if ok.sum() < 0.75 * nb:
            out.append(None); continue
        ro, ri = float(np.median(mx[ok])), float(np.median(mn[ok]))
        out.append((ro, ri if ri < ro * 0.995 and ri > 0.02 * ro else None))
    return out


def frame_of(ax, c):
    ax = ax / np.linalg.norm(ax)
    x0 = np.cross(ax, [1, 0, 0] if abs(ax[0]) < 0.9 else [0, 1, 0]); x0 /= np.linalg.norm(x0)
    return np.array([x0, np.cross(ax, x0), ax]), c


def roundness(V, E, ax, c, nb=36):
    """Spread of the outer and inner radius over angle, median over 9 levels (0 = round)."""
    R, c = frame_of(ax, c)
    L = (V - c) @ R.T
    lo, hi = L[:, 2].min(), L[:, 2].max()
    sc = []
    for f in np.linspace(0.1, 0.9, 9):
        P = cut_points(L, E, lo + f * (hi - lo))
        if len(P) < 6:
            continue
        mx, mn = ring(P, nb)
        ok = ~np.isnan(mx)
        if ok.sum() < 0.75 * nb:
            continue
        for v in (mx[ok], mn[ok]):
            md = np.median(v)
            sc.append(np.median(np.abs(v - md)) / max(md, 1e-9))
    return float(np.median(sc)) if len(sc) >= 6 else 1.0


def refine_axis(V, E, ax, c, size):
    """Pattern search on two tilts and two offsets of the axis, minimising roundness()."""
    R, c = frame_of(ax, c)
    best = roundness(V, E, ax, c)
    da, do = np.radians(6.0), 0.05 * size
    while da > np.radians(0.02):
        moved = False
        for k in range(4):
            for sgn in (1, -1):
                if k < 2:
                    a2 = R[2] + sgn * np.tan(da) * R[k]; c2 = c
                else:
                    a2 = R[2]; c2 = c + sgn * do * R[k - 2]
                v = roundness(V, E, a2, c2)
                if v < best - 1e-7:
                    best, c = v, c2
                    R, c = frame_of(a2, c)
                    moved = True
        if not moved:
            da, do = da / 2, do / 2
    return R[2], c, best


def simplify(pts, tol):
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return pts.tolist()
    a, b = pts[0], pts[-1]
    ab = b - a; L = np.linalg.norm(ab)
    d = (np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / L) if L > 0 else np.linalg.norm(pts - a, axis=1)
    i = int(np.argmax(d))
    if d[i] > tol:
        return simplify(pts[:i + 1], tol)[:-1] + simplify(pts[i:], tol)
    return [a.tolist(), b.tolist()]


def revolved_volume(poly):
    p = np.asarray(poly, float); q = np.roll(p, -1, 0)
    # Pappus on a closed (r, t) polygon: V = 2 pi * |sum over edges|
    return float(abs(np.pi / 3 * np.sum((p[:, 0] ** 2 + p[:, 0] * q[:, 0] + q[:, 0] ** 2) * (q[:, 1] - p[:, 1]))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mesh', nargs='?', default='/app/reference.obj')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--levels', type=int, default=60)
    ap.add_argument('--tol', type=float, default=0.004, help='simplify tolerance, fraction of size')
    a = ap.parse_args()
    m, V, F = load(a.mesh)
    C, A, N = tri_data(V, F)
    E = edges_of(F)
    size0 = float(np.linalg.norm(V.max(0) - V.min(0)))
    ax, c, res, frac = fit_axis(C, A, N)
    dirs = [ax] + list(np.linalg.svd((C - (A[:, None] * C).sum(0) / A.sum()) * np.sqrt(A)[:, None],
                                     full_matrices=False)[2])
    nf = N * np.sign(N @ np.array([0.577, 0.578, 0.5771]))[:, None]  # fold the sign
    key = np.round(nf * 20).astype(int)
    u, inv = np.unique(key, axis=0, return_inverse=True)
    wsum = np.bincount(inv.ravel(), A)
    for k in np.argsort(-wsum)[:4]:  # largest flat-normal clusters: a flat end or rim faces the axis
        v = (A[inv.ravel() == k, None] * nf[inv.ravel() == k]).sum(0)
        dirs.append(v / np.linalg.norm(v))
    cands = [(d, axis_point(C, A, N, d)) for d in dirs]
    scored = sorted(((roundness(V, E, a0, c0), i) for i, (a0, c0) in enumerate(cands)))
    ax, c = cands[scored[0][1]]
    ax, c, res = refine_axis(V, E, ax, c, size0)
    c = c - ax * (c @ ax)
    # local frame: z = axis, x toward off-axis material (arm) if any
    t_all = (V - c) @ ax
    rv = V - c - np.outer(t_all, ax)
    zf = np.abs(ax) < 0.9
    x0 = np.cross(ax, [1, 0, 0] if zf[0] else [0, 1, 0]); x0 /= np.linalg.norm(x0)
    rr = np.linalg.norm(rv, axis=1)
    far = rr > np.percentile(rr, 90)
    xd = rv[far].mean(0) if far.any() else x0
    xd = xd - ax * (xd @ ax)
    if np.linalg.norm(xd) < 1e-6 * (rr.max() + 1e-9):
        xd = x0
    xd /= np.linalg.norm(xd)
    yd = np.cross(ax, xd)
    R = np.array([xd, yd, ax])
    L = (V - c) @ R.T
    tmin, tmax = L[:, 2].min(), L[:, 2].max()
    H = tmax - tmin
    L[:, 2] -= tmin
    origin = c + tmin * ax
    print(f'revolve axis (world) {np.round(ax, 5).tolist()} through {np.round(origin, 4).tolist()}')
    print(f'roundness {res:.4f} (radius spread over angle; < 0.01 = round about this axis, > 0.03 = not round: '
          'use sections.py instead)')
    if res > 0.02:
        print('NOT ROUND about any axis found (an elliptic, prismatic or free-form body, or an arm too '
              'large): no profile printed, frame.json unchanged; use sections.py all.')
        return
    eps = 1e-3 * H
    lv = np.concatenate([[eps], np.linspace(0, H, a.levels + 1)[1:-1], [H - eps]])
    rad = section_radii(L, E, lv)
    good = [(t, x) for t, x in zip(lv, rad) if x is not None]
    if len(good) < 3:
        print('not a round body about this axis (no loop around it at most levels): use sections.py')
        return
    size = max(H, max(x[0] for _, x in good))
    tol = a.tol * size
    outer = [(x[0], t) for t, x in good]
    inner = [(x[1], t) for t, x in good if x[1] is not None]
    print(f'height {H:.4f}; outer r from {outer[0][0]:.4f} (t=0) to {outer[-1][0]:.4f} (t={H:.4f}), '
          f'max {max(o[0] for o in outer):.4f}')
    ends = lambda pts, t0, t1: [(pts[0][0], t0)] + pts + [(pts[-1][0], t1)]
    step = H / a.levels
    g0 = 0.0 if good[0][0] <= 1.5 * step else good[0][0] - step / 2
    g1 = H if good[-1][0] >= H - 1.5 * step else good[-1][0] + step / 2
    if g1 - g0 < 0.98 * H:
        print(f'round body over t {g0:.4f}..{g1:.4f} only; beyond it the mesh is not around the axis '
              '(an arm or handle): model that from sections.py/sides.py')
    o = simplify(ends(outer, g0, g1), tol)
    poly = [(0.0, g0)] + o
    if inner:
        ti0, ti1 = inner[0][1], inner[-1][1]
        top_open = ti1 >= g1 - 1.5 * step
        bot_open = ti0 <= g0 + 1.5 * step
        i_pts = simplify(ends(inner, g0 if bot_open else ti0 - step / 2, g1 if top_open else ti1 + step / 2), tol)
        wall = np.median([x[0] - x[1] for _, x in good if x[1] is not None])
        print(f'cavity: inner r {inner[0][0]:.4f}..{inner[-1][0]:.4f} over t {i_pts[0][1]:.4f}..{i_pts[-1][1]:.4f} '
              f'({"open at the top" if top_open else "closed top"}, {"open at the bottom" if bot_open else "floor below"}); '
              f'median wall {wall:.4f}' + ('' if bot_open else f'; floor thickness {i_pts[0][1]:.4f}'))
        if top_open and not bot_open:   # open at the top: up the outside, down the inside, floor to the axis
            poly = [(0.0, 0.0)] + o + i_pts[::-1] + [(0.0, i_pts[0][1])]
        elif bot_open and not top_open:  # opening at the bottom
            poly = [(0.0, g1)] + [p for p in reversed(o)] + i_pts + [(0.0, i_pts[-1][1])]
            poly = poly[::-1]
        elif bot_open and top_open:      # tube / ring: no axis segment
            poly = o + i_pts[::-1]
        else:                            # closed hollow: revolve the outer, cut the inner separately
            print('closed inner void: revolve the outer profile; the inner one is a Groove profile:')
            print('INNER = ' + json.dumps([[round(u, 4), round(v, 4)] for u, v in [(0.0, i_pts[0][1])] + i_pts + [(0.0, i_pts[-1][1])]]))
    if poly[-1][0] != 0.0 and poly[0][0] == 0.0 and not (inner and bot_open and top_open):
        poly.append((0.0, poly[-1][1]))
    # drop repeated points
    clean = []
    for p in poly:
        if not clean or np.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-6 * size:
            clean.append(p)
    if np.hypot(clean[0][0] - clean[-1][0], clean[0][1] - clean[-1][1]) < 1e-6 * size:
        clean.pop()
    pv = revolved_volume(clean)
    print(f'\nhalf-section, {len(clean)} points (u = r, v = t), closed; revolves to {pv:.6g} '
          f'= {pv / m.Volume:.3f} x mesh volume (the rest is arms/ribs/holes, or < 1 means they cut):')
    print('PROFILE = ' + json.dumps([[round(u, 4), round(v, 4)] for u, v in clean]))
    print("use: sk = K.sketch(body, 'XZ'); c = K.polygon(sk, PROFILE); K.revolve(body, sk)  "
          "(in this frame; bind the radii/heights a designer would change)")
    if a.write:
        fr = '/app/frame.json'
        if os.path.exists(fr):
            shutil.copy(fr, '/app/frame_measure.json')
        lmin, lmax = L.min(0), L.max(0)
        json.dump({'kind': 'round', 'R': R.tolist(), 'origin': origin.tolist(),
                   'local_min': lmin.tolist(), 'local_max': lmax.tolist(),
                   'mesh': os.path.abspath(a.mesh), 'mesh_volume': m.Volume}, open(fr, 'w'), indent=1)
        print(f'wrote {fr} (local z = this axis, origin on it at t=0; old frame in /app/frame_measure.json). '
              f'local bbox {np.round(lmin, 3).tolist()} .. {np.round(lmax, 3).tolist()}')
    else:
        print('run again with --write to model in this frame (PROFILE is in it).')


if __name__ == '__main__':
    main()
