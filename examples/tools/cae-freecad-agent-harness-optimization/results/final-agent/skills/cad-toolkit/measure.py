# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Survey a mesh and find the part's own frame (meshes are posed: world axes mean nothing).

    python3 /agent/skills/cad-toolkit/measure.py /app/reference.obj [--out /app/frame.json]

Prints volume, solidity, the frame (round axis or flat-face axes), the local bounding box,
the distinct vertex levels along each local axis, and for a round part the (t, r) rings.
Writes frame.json, which sections.py, sketchkit.pose_body() and verify.py read.
local = (world - origin) @ R.T ; R rows are the local x, y, z axes in world coordinates.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fc  # noqa: E402,F401
import Mesh  # noqa: E402


def load(path):
    m = Mesh.Mesh(path)
    pts, fac = m.Topology
    V = np.array([[p.x, p.y, p.z] for p in pts])
    F = np.array(fac, dtype=int)
    return m, V, F


def tri_data(V, F):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    n = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(n, axis=1)
    nn = n / np.maximum(2 * area[:, None], 1e-30)
    return (a + b + c) / 3, area, nn


def circle_fit(p2):
    # Kasa least-squares circle: returns centre, radius, rms residual
    A = np.c_[2 * p2, np.ones(len(p2))]
    b = (p2 ** 2).sum(1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:2]
    r = np.sqrt(max(sol[2] + c @ c, 1e-30))
    res = np.sqrt(np.mean((np.linalg.norm(p2 - c, axis=1) - r) ** 2))
    return c, r, res


def perp_basis(z):
    t = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = t - (t @ z) * z
    x /= np.linalg.norm(x)
    return x, np.cross(z, x)


def levels(vals, tol, minc=1):
    q = np.round(vals / tol) * tol
    u, c = np.unique(q, return_counts=True)
    keep = c >= minc
    return u[keep], c[keep]


def round_score(V, axis, tol):
    """Median relative residual of circle fits on the vertex rings along axis (0 = round)."""
    x, y = perp_basis(axis)
    t = V @ axis
    lv, cnt = levels(t, tol, minc=8)
    fits = []
    for L in lv:
        sel = np.abs(t - L) < tol * 0.5
        p2 = np.c_[V[sel] @ x, V[sel] @ y]
        c, r, res = circle_fit(p2)
        # use only the outer ring of the level (vertices near the max radius around c)
        d = np.linalg.norm(p2 - c, axis=1)
        outer = p2[d > 0.97 * d.max()]
        if len(outer) >= 6:
            c, r, res = circle_fit(outer)
        fits.append((L, c, r, res / max(r, 1e-9), len(outer)))
    if len(fits) < 2:
        return 9.0, None, fits
    rel = np.array([f[3] for f in fits])
    good = [f for f in fits if f[3] < 0.01]
    centre = np.median(np.array([f[1] for f in good]), axis=0) if good else None
    return float(np.median(rel)), centre, fits


def normal_clusters(nn, area, cos_tol=0.998):
    order = np.argsort(-area)
    dirs, w = [], []
    for i in order:
        n = nn[i]
        for k, d in enumerate(dirs):
            if abs(n @ d) > cos_tol:
                w[k] += area[i]
                break
        else:
            if len(dirs) < 60:
                dirs.append(n.copy())
                w.append(area[i])
    w = np.array(w) / area.sum()
    o = np.argsort(-w)
    return [dirs[i] for i in o], w[o]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mesh')
    ap.add_argument('--out', default='/app/frame.json')
    ap.add_argument('--force', choices=['round', 'flat', 'pca'], help='override the frame kind')
    a = ap.parse_args()

    m, V, F = load(a.mesh)
    cen, area, nn = tri_data(V, F)
    bbmin, bbmax = V.min(0), V.max(0)
    diag = float(np.linalg.norm(bbmax - bbmin))
    tol = max(diag * 2e-3, 0.01)
    print(f'mesh: {len(V)} vertices, {len(F)} triangles, area {m.Area:.4g}, volume {m.Volume:.6g}, '
          f'solid(closed) {m.isSolid()}, non-manifold {m.hasNonManifolds()}')
    print(f'world bbox min {np.round(bbmin, 3)} max {np.round(bbmax, 3)} (diag {diag:.4g})')

    w = area / area.sum()
    mu = (w[:, None] * cen).sum(0)
    C = ((cen - mu) * w[:, None]).T @ (cen - mu)
    ev, evec = np.linalg.eigh(C)
    sig = np.sqrt(np.maximum(ev, 0))
    print('PCA sigmas', np.round(sig, 4), 'axes (columns)\n', np.round(evec, 4))

    dirs, dw = normal_clusters(nn, area)
    print('largest flat-normal clusters (area fraction, direction):')
    for d, f in list(zip(dirs, dw))[:6]:
        print(f'  {f:.3f}  {np.round(d, 4)}')

    # candidate round axes: PCA axes and the largest normal directions
    cands = [evec[:, i] for i in range(3)] + dirs[:3]
    best = (9.0, None, None, None)
    for ax in cands:
        ax = ax / np.linalg.norm(ax)
        s, c, fits = round_score(V, ax, tol)
        if s < best[0]:
            best = (s, ax, c, fits)
    rscore, rax, rc, rfits = best
    print(f'round score (0 = revolved about an axis; > 0.02 = not round): {rscore:.4f}')

    # flat-walled: at least two large, non-parallel planar normal clusters
    big = [d for d, f in zip(dirs, dw) if f > 0.08]
    two_flat = any(abs(big[0] @ d) < 0.2 for d in big[1:]) if big else False
    kind = a.force or ('flat' if two_flat else
                       'round' if rscore < 0.01 and rc is not None else 'pca')
    if kind == 'round' and rax is not None:
        z = rax
        x, y = perp_basis(z)
        pc = rc[0] * x + rc[1] * y  # axis point (projection plane)
        # point x toward the off-axis material, if any
        off = (cen - pc - np.outer((cen - pc) @ z, z)) * w[:, None]
        v = off.sum(0)
        if np.linalg.norm(v) > 1e-3 * diag:
            x = v / np.linalg.norm(v)
            y = np.cross(z, x)
        R = np.array([x, y, z])
        t = V @ z
        origin = pc + (t.min()) * z
    elif kind == 'flat':
        n1 = dirs[0]
        n2 = next((d for d in dirs[1:] if abs(d @ n1) < 0.2), None)
        if n2 is None:
            n2 = perp_basis(n1)[0]
        n2 = n2 - (n2 @ n1) * n1
        n2 /= np.linalg.norm(n2)
        axes = [n1, n2, np.cross(n1, n2)]
        ext = [np.ptp(V @ ax) for ax in axes]
        o = np.argsort(ext)[::-1]  # x longest, z shortest
        x, y = axes[o[0]], axes[o[1]]
        R = np.array([x, y, np.cross(x, y)])
        L = V @ R.T
        origin = R.T @ L.min(0)
    else:
        # free-form: z = the largest flat face's normal if there is one (a base), else
        # the smallest PCA axis; x = the main PCA direction in that plane
        z = dirs[0] if dw[0] > 0.08 else evec[:, 0]
        x = evec[:, 2] - (evec[:, 2] @ z) * z
        if np.linalg.norm(x) < 0.3:
            x = evec[:, 1] - (evec[:, 1] @ z) * z
        x /= np.linalg.norm(x)
        R = np.array([x, np.cross(z, x), z])
        L = V @ R.T
        origin = R.T @ L.min(0)

    L = (V - origin) @ R.T
    lmin, lmax = L.min(0), L.max(0)
    print(f'\nFRAME kind={kind}')
    for i, nme in enumerate('xyz'):
        print(f'  local {nme} = world {np.round(R[i], 5)}')
    print(f'  origin (world) {np.round(origin, 4)}')
    print(f'local bbox min {np.round(lmin, 3)} max {np.round(lmax, 3)} size {np.round(lmax - lmin, 3)}')
    if kind == 'round':
        print('  round: local z is the revolve axis, the axis passes through local (0,0); '
              'local x points toward off-axis material if any.')

    print(f'\nDistinct vertex levels per local axis (coordinate: vertex count; tol {tol:.3g}). '
          'Few levels with many vertices = face planes / extrusion ends.')
    for i, nme in enumerate('xyz'):
        u, c = levels(L[:, i], tol)
        top = np.sort(u[np.argsort(-c)[:20]])
        cc = {float(k): int(c[list(u).index(k)]) for k in top}
        print(f'  {nme}: {len(u)} levels; top: ' + ', '.join(f'{k:.3f}:{v}' for k, v in cc.items()))

    if kind == 'round':
        r = np.linalg.norm(L[:, :2], axis=1)
        print('\n(t, r) rings: t = local z level, radii found at that level (vertex counts). '
              'Outer profile = max r, bore/cavity = inner r. Consecutive collinear rings are one segment.')
        u, c = levels(L[:, 2], tol, minc=6)
        for t in u:
            sel = np.abs(L[:, 2] - t) < tol * 0.5
            ru, rc_ = levels(r[sel], tol, minc=3)
            print(f'  t={t:9.3f}: ' + ', '.join(f'r={a_:.3f}x{b_}' for a_, b_ in zip(ru, rc_)))

    json.dump({'kind': kind, 'R': R.tolist(), 'origin': origin.tolist(),
               'local_min': lmin.tolist(), 'local_max': lmax.tolist(),
               'mesh': os.path.abspath(a.mesh), 'mesh_volume': m.Volume},
              open(a.out, 'w'), indent=1)
    print(f'\nwrote {a.out}. Next: sections.py for loops, or pose a Body with '
          'sketchkit.pose_body(body, "' + a.out + '") and model in local coordinates.')


if __name__ == '__main__':
    main()
