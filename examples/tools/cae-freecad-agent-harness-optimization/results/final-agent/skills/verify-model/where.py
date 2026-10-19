# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Where a model and a mesh differ: an IoU estimate plus the regions of missing and extra
material, each with its size, world box, and the feature it comes from.

    import sys; sys.path.insert(0, '/agent/skills/verify-model'); import where
    where.report(mesh_triangles, model_shape, features)   # prints, returns the IoU estimate

How: rays along z through a fine grid of columns over both shapes; each column's inside
intervals are the parity pairs of its sorted crossings. The difference of the two shapes'
intervals is binned into coarse cells; touching cells form regions. MISSING = inside the mesh,
not the model; EXTRA = inside the model, not the mesh. A region's 'IoU if fixed' is the IoU
estimate with that region's error removed: fix the region with the largest gain first.
"""
import numpy as np


def _hits(tri, lo, h, G, axis=2):
    u, v = [i for i in range(3) if i != axis]
    cu = lo[u] + (np.arange(G) + 0.5 + 1.234e-4) * h
    cv = lo[v] + (np.arange(G) + 0.5 + 2.345e-4) * h
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
        U, W = np.meshgrid(cu[i0:i1 + 1], cv[j0:j1 + 1], indexing='ij')
        l1 = ((b[u] - U) * (c[v] - W) - (c[u] - U) * (b[v] - W)) / d
        l2 = ((c[u] - U) * (a[v] - W) - (a[u] - U) * (c[v] - W)) / d
        l3 = 1 - l1 - l2
        m = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        if not m.any():
            continue
        z = l1 * a[axis] + l2 * b[axis] + l3 * c[axis]
        for (ii, jj), zz in zip(np.argwhere(m), z[m]):
            cols.setdefault((i0 + ii, j0 + jj), []).append(zz)
    return cols


def _ivs(zs):
    zs = sorted(zs)
    return [(zs[k], zs[k + 1]) for k in range(0, len(zs) - 1, 2)]


def _minus(A, B):
    """intervals of A not covered by B"""
    out = []
    for p, q in A:
        segs = [(p, q)]
        for r, s in B:
            nxt = []
            for a, b in segs:
                if s <= a or r >= b:
                    nxt.append((a, b))
                    continue
                if r > a:
                    nxt.append((a, r))
                if s < b:
                    nxt.append((s, b))
            segs = nxt
        out += [x for x in segs if x[1] - x[0] > 1e-9]
    return out


def _tris_of_shape(shape, diag):
    pts, fs = shape.tessellate(2e-3 * diag)
    if not fs:
        return np.zeros((0, 3, 3))
    return np.array([[p.x, p.y, p.z] for p in pts])[np.array(fs)]


_PIECE = [0.0]


def _largest_piece(A, B, lo, hi, h, G, r=3):
    """voxels of the largest connected piece of mesh material the model lacks, after an
    opening by r voxels (erode r times, keep the largest 6-connected piece, grow it back r
    times inside the missing set): a skin thinner than ~2r voxels, where the model is a
    little small all over, is not a piece; a left-out branch or boss is."""
    K = int(np.ceil((hi[2] - lo[2]) / h)) + 1
    M = np.zeros((G, G, K), bool)
    zc = lo[2] + (np.arange(K) + 0.5) * h
    for key in A:
        for p, q in _minus(_ivs(A.get(key, [])), _ivs(B.get(key, []))):
            M[key[0], key[1], (zc > p) & (zc < q)] = True
    if not M.any():
        return 0

    def shift_and(X):
        Y = X.copy()
        for ax in range(3):
            for d in (1, -1):
                Z = np.roll(X, d, axis=ax)
                sl = [slice(None)] * 3
                sl[ax] = 0 if d == 1 else -1
                Z[tuple(sl)] = False
                Y &= Z
        return Y

    def shift_or(X):
        Y = X.copy()
        for ax in range(3):
            for d in (1, -1):
                Z = np.roll(X, d, axis=ax)
                sl = [slice(None)] * 3
                sl[ax] = 0 if d == 1 else -1
                Z[tuple(sl)] = False
                Y |= Z
        return Y
    E = M
    for _ in range(r):
        E = shift_and(E)
    if not E.any():
        return 0
    # largest 6-connected component of E (flood fill over the few voxels left)
    idx = np.argwhere(E)
    lab = -np.ones(E.shape, int)
    best, best_n, cur = None, 0, 0
    for st in map(tuple, idx):
        if lab[st] >= 0:
            continue
        stack, n = [st], 0
        lab[st] = cur
        while stack:
            c = stack.pop()
            n += 1
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nb = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                if 0 <= nb[0] < G and 0 <= nb[1] < G and 0 <= nb[2] < K and E[nb] and lab[nb] < 0:
                    lab[nb] = cur
                    stack.append(nb)
        if n > best_n:
            best, best_n = cur, n
        cur += 1
    P = lab == best
    for _ in range(r):
        P = shift_or(P) & M
    return int(P.sum())


def analyse(ta, tb, G=140, C=22):
    """IoU estimate and regions. ta, tb: triangle arrays (T x 3 x 3) of mesh and model."""
    allp = np.concatenate([ta.reshape(-1, 3), tb.reshape(-1, 3)]) if len(tb) else ta.reshape(-1, 3)
    lo, hi = allp.min(0), allp.max(0)
    span = max(hi[0] - lo[0], hi[1] - lo[1]) * (1 + 1e-6)
    h = span / G
    H = max(hi - lo) / C                      # coarse cell size
    shape3 = tuple(int(np.ceil((hi[i] - lo[i]) / H)) + 1 for i in range(3))
    A, B = _hits(ta, lo, h, G), _hits(tb, lo, h, G) if len(tb) else {}
    inter = union = 0.0
    miss = np.zeros(shape3)
    extra = np.zeros(shape3)
    rep = {}                                   # (kind, cell) -> (longest piece, its midpoint)
    for key in set(A) | set(B):
        ia, ib = _ivs(A.get(key, [])), _ivs(B.get(key, []))
        la = sum(q - p for p, q in ia)
        lb = sum(q - p for p, q in ib)
        ov = sum(max(0.0, min(q1, q2) - max(p1, p2)) for p1, q1 in ia for p2, q2 in ib)
        inter += ov
        union += la + lb - ov
        x = lo[0] + (key[0] + 0.5) * h
        y = lo[1] + (key[1] + 0.5) * h
        ci, cj = int((x - lo[0]) / H), int((y - lo[1]) / H)
        for kind, arr, pieces in (('MISSING', miss, _minus(ia, ib)), ('EXTRA', extra, _minus(ib, ia))):
            for p, q in pieces:
                k0, k1 = int((p - lo[2]) / H), int((q - lo[2]) / H)
                for k in range(k0, k1 + 1):
                    a, b = max(p, lo[2] + k * H), min(q, lo[2] + (k + 1) * H)
                    if b <= a:
                        continue
                    arr[ci, cj, k] += (b - a) * h * h
                    r = rep.get((kind, (ci, cj, k)))
                    if r is None or b - a > r[0]:
                        rep[(kind, (ci, cj, k))] = (b - a, (x, y, (a + b) / 2))
    iou = inter / union if union else 0.0
    _PIECE[0] = _largest_piece(A, B, lo, hi, h, G) * h ** 3
    inter, union = inter * h * h, union * h * h      # volumes, like the regions'
    regions = []
    for kind, arr in (('MISSING', miss), ('EXTRA', extra)):
        flag = arr > 0.04 * H ** 3
        seen = np.zeros(shape3, bool)
        for start in zip(*np.nonzero(flag)):
            if seen[start]:
                continue
            stack, cells = [start], []
            seen[start] = True
            while stack:
                c = stack.pop()
                cells.append(c)
                for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                    n = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                    if all(0 <= n[i] < shape3[i] for i in range(3)) and flag[n] and not seen[n]:
                        seen[n] = True
                        stack.append(n)
            vol = sum(arr[c] for c in cells)
            idx = np.array(cells)
            w = np.array([arr[c] for c in cells])
            cen = lo + (idx + 0.5) @ np.eye(3) * H
            centre = (cen * w[:, None]).sum(0) / w.sum()
            box = (lo + idx.min(0) * H, lo + (idx.max(0) + 1) * H)
            top = sorted(cells, key=lambda c: -arr[c])[:7]
            samples = [rep[(kind, c)][1] for c in top if (kind, c) in rep]
            gain = (inter / (union - vol) if kind == 'EXTRA' else (inter + vol) / union) if union else 0
            regions.append(dict(kind=kind, vol=vol, box=box, centre=centre, samples=samples, gain=gain))
    regions.sort(key=lambda r: -r['vol'])
    return iou, regions, (inter, union)


def _owner(samples, features, kind):
    """which feature put the material there (EXTRA: additive) or took it away (MISSING: cut)"""
    import FreeCAD as App
    votes = {}
    for nm, shp, cut in features:
        if shp is None or shp.isNull() or cut != (kind == 'MISSING'):
            continue
        for p in samples:
            try:
                if shp.isInside(App.Vector(*p), 1e-3, True):
                    votes[nm] = votes.get(nm, 0) + 1
            except Exception:  # noqa: BLE001
                pass
    if not votes:
        return 'no feature removed it (a feature not built, or one that stops short)' if kind == 'MISSING' \
            else 'no single feature (several overlap there)'
    best = sorted(votes, key=lambda k: -votes[k])
    return ('removed by ' if kind == 'MISSING' else 'added by ') + ', '.join(best[:2])


def features_of(body):
    """(name, its own added/removed shape, is a cut) for each PartDesign feature of a body"""
    out = []
    for o in body.Group:
        if not o.TypeId.startswith('PartDesign::') or not hasattr(o, 'AddSubShape'):
            continue
        cut = any(k in o.TypeId for k in ('Subtractive', 'Pocket', 'Groove', 'Hole'))
        try:
            s = o.AddSubShape
            if s.isNull() or not s.Solids:
                continue
            out.append((o.Name, s, cut))
        except Exception:  # noqa: BLE001
            pass
    return out


LAST = {}     # the last report: iou, largest_missing (fraction of the mesh volume), missing (that region)
MISSING_MAX = 0.012   # a missing piece larger than this is a feature left out, not a skin


def report(ta, shape, features=(), mesh_volume=None, top=3, quiet=False):
    """Print the IoU estimate and up to `top` regions of >= 1% of the mesh volume."""
    diag = float(np.linalg.norm(ta.reshape(-1, 3).max(0) - ta.reshape(-1, 3).min(0)))
    tb = _tris_of_shape(shape, diag) if shape is not None and not shape.isNull() else np.zeros((0, 3, 3))
    iou, regions, (inter, union) = analyse(ta, tb)
    mv = mesh_volume or 1.0
    miss = [r for r in regions if r['kind'] == 'MISSING']
    LAST.clear()
    LAST.update(iou=iou, largest_missing=_PIECE[0] / mv, missing=miss[0] if miss else None,
                missing_owner=_owner(miss[0]['samples'], features, 'MISSING') if miss else '')
    if quiet:
        return iou
    big = [r for r in regions if r['vol'] >= 0.01 * mv][:top]
    print(f'\nWHERE the model differs from the mesh (IoU estimate {iou:.3f}; '
          f'{len(big)} region(s) of >= 1% of the mesh volume, largest first):', flush=True)
    for r in big:
        (x0, y0, z0), (x1, y1, z1) = r['box']
        c = r['centre']
        print(f"  {r['kind']:7s} {100 * r['vol'] / mv:5.1f}% of mesh volume, x {x0:.1f}..{x1:.1f} y {y0:.1f}..{y1:.1f} "
              f"z {z0:.1f}..{z1:.1f}, centre ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f}): "
              f"{_owner(r['samples'], features, r['kind'])}; IoU if fixed ~{r['gain']:.3f}", flush=True)
    if not big:
        print('  none: what remains is a thin skin of small differences over the whole surface', flush=True)
    lm = LAST['largest_missing']
    if lm > MISSING_MAX:
        r = LAST['missing']
        c = r['centre'] if r else (float('nan'),) * 3
        print(f'  LARGEST MISSING PIECE {100 * lm:.1f}% of the mesh volume around ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f}) '
              f'(over {100 * MISSING_MAX:.1f}%: a whole feature is left out or stops short - a branch, a boss, a wall; '
              f'build it, the model is not complete without it)', flush=True)
    else:
        print(f'  largest missing piece {100 * lm:.1f}% of the mesh volume (<= {100 * MISSING_MAX:.1f}%: no feature left out)', flush=True)
    return iou
