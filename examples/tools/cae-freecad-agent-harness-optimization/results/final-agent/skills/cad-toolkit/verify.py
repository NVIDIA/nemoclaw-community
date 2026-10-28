# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Verify a saved model against the mesh, the way a reviewer would. ~5-15 s.

    python3 /agent/skills/cad-toolkit/verify.py [/app/model.FCStd] [/app/reference.obj] [--n 20000]

Reopens the file, recomputes, and prints: objects in error, visible objects (must be exactly
one: the Body), solids / isValid / check(True), face count, volume vs mesh volume, an IoU
estimate (own point sampling: ray parity inside the mesh and inside the model's tessellation,
both vectorized, so a loft model costs seconds, not minutes), sketches not
fully constrained or using Block, and for every Params alias the volume/bbox change at +10 %
(a named dimension that changes nothing is not driving the model).
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fc  # noqa: E402,F401
import FreeCAD as App  # noqa: E402
import Mesh  # noqa: E402


def mesh_inside(V, F, P):
    """Ray parity along +z for points P (N,3) against triangles."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    eps = 1e-7
    P = P + np.array([eps * 1.37, eps * 2.11, 0])  # avoid hitting edges exactly
    cnt = np.zeros(len(P), dtype=int)
    tmin = np.minimum(np.minimum(a[:, :2], b[:, :2]), c[:, :2])
    tmax = np.maximum(np.maximum(a[:, :2], b[:, :2]), c[:, :2])
    for s in range(0, len(F), 256):
        A, B, C = a[s:s + 256], b[s:s + 256], c[s:s + 256]
        lo, hi = tmin[s:s + 256], tmax[s:s + 256]
        px, py = P[:, None, 0], P[:, None, 1]
        cand = (px >= lo[None, :, 0]) & (px <= hi[None, :, 0]) & (py >= lo[None, :, 1]) & (py <= hi[None, :, 1])
        if not cand.any():
            continue
        x0, y0, x1, y1, x2, y2 = A[:, 0], A[:, 1], B[:, 0], B[:, 1], C[:, 0], C[:, 1]
        det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        det = np.where(np.abs(det) < 1e-30, 1e-30, det)
        l0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / det
        l1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / det
        l2 = 1 - l0 - l1
        hit = cand & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        z = l0 * A[:, 2] + l1 * B[:, 2] + l2 * C[:, 2]
        hit &= z > P[:, None, 2]
        cnt += hit.sum(1)
    return cnt % 2 == 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('model', nargs='?', default='/app/model.FCStd')
    ap.add_argument('mesh', nargs='?', default='/app/reference.obj')
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--no-params', action='store_true')
    a = ap.parse_args()

    doc = App.openDocument(a.model)
    for o in doc.Objects:
        o.touch()
    doc.recompute()
    errs = [(o.Name, list(o.State)) for o in doc.Objects if 'Invalid' in o.State or 'Error' in o.State]
    vis = [o.Name for o in doc.Objects if getattr(o, 'Visibility', False)
           and o.TypeId not in ('App::Origin', 'App::Line', 'App::Plane')]
    bodies = [o for o in doc.Objects if o.TypeId == 'PartDesign::Body']
    print(f'objects in error: {errs or "none"}')
    print(f'visible top-level objects: {vis}  (want exactly one: the Body)')
    if not bodies:
        print('FAIL: no PartDesign::Body')
        return
    body = bodies[0]
    s = body.Shape
    try:
        chk = s.check(True) is None
    except Exception as e:
        chk = f'FAILED {str(e)[:150]}'
    m = Mesh.Mesh(a.mesh)
    mv = m.Volume
    print(f'solids {len(s.Solids)}  isValid {s.isValid()}  check(True) {chk}  faces {len(s.Faces)}')
    print(f'volume model {s.Volume:.6g}  mesh {mv:.6g}  ratio {s.Volume / mv:.4f}')
    feats = [o for o in body.Group if o.TypeId.startswith('PartDesign::') and o.TypeId != 'PartDesign::Body']
    print('features:', [f'{o.Name}({o.TypeId.split("::")[1]})' for o in feats])
    for sk in [o for o in doc.Objects if o.TypeId == 'Sketcher::SketchObject']:
        nblock = sum(1 for c in sk.Constraints if c.Type == 'Block')
        named = [c.Name for c in sk.Constraints if c.Name]
        try:
            sk.solve()
        except Exception:
            pass
        flag = '' if sk.FullyConstrained and not nblock else '  <-- fix'
        print(f'  sketch {sk.Name}: fully constrained {sk.FullyConstrained}, Block {nblock}, named {named}{flag}')

    # IoU estimate on the union bounding box
    pts, fac = m.Topology
    V = np.array([[p.x, p.y, p.z] for p in pts])
    F = np.array(fac, dtype=int)
    bb = s.BoundBox
    lo = np.minimum(V.min(0), [bb.XMin, bb.YMin, bb.ZMin])
    hi = np.maximum(V.max(0), [bb.XMax, bb.YMax, bb.ZMax])
    rng = np.random.default_rng(0)
    P = lo + rng.random((a.n, 3)) * (hi - lo)
    inm = mesh_inside(V, F, P)
    # The model: tessellate once and use the same vectorized ray parity. Per-point
    # shape.isInside took 45-165 s on loft models and ran runs out of time.
    diag = max(float(np.linalg.norm(hi - lo)), 1e-9)
    tv, tf = s.tessellate(diag * 1e-3)
    if len(tf):
        ins = mesh_inside(np.array([[q.x, q.y, q.z] for q in tv]), np.array(tf, dtype=int), P)
    else:
        ins = np.zeros(len(P), dtype=bool)
    inter, union = (inm & ins).sum(), (inm | ins).sum()
    iou = inter / max(union, 1)
    print(f'IoU estimate {iou:.4f} (n={a.n}; mesh-only {int((inm & ~ins).sum())} = model too small there, '
          f'model-only {int((ins & ~inm).sum())} = model too big there)')
    if (inm & ~ins).sum() + (ins & ~inm).sum():
        for lab, msk in (('missing material', inm & ~ins), ('extra material', ins & ~inm)):
            if msk.sum():
                c = P[msk].mean(0)
                loc = ''
                if os.path.exists('/app/frame.json'):
                    import json
                    fr = json.load(open('/app/frame.json'))
                    loc = f' = local {np.round((c - np.array(fr["origin"])) @ np.array(fr["R"]).T, 2)}'
                print(f'  {lab} centred near world {np.round(c, 2)}{loc}')

    if a.no_params:
        return
    sheets = [o for o in doc.Objects if o.TypeId == 'Spreadsheet::Sheet']
    v0 = s.Volume
    b0 = np.array([bb.XLength, bb.YLength, bb.ZLength])
    for sh in sheets:
        for r in range(1, 500):
            cell = f'B{r}'
            alias = sh.getAlias(cell) if hasattr(sh, 'getAlias') else None
            if sh.getContents(f'A{r}') == '' and not alias:
                break
            if not alias:
                continue
            old = sh.getContents(cell)
            try:
                val = float(sh.get(alias))
            except Exception:
                continue
            sh.set(cell, str(val * 1.1))
            doc.recompute()
            ns = body.Shape
            ok = ns.isValid() and len(ns.Solids) == 1
            nb = ns.BoundBox
            dv = (ns.Volume - v0) / v0 * 100 if ok else float('nan')
            db = np.abs(np.array([nb.XLength, nb.YLength, nb.ZLength]) - b0).max()
            tag = '' if ok and (abs(dv) > 1e-6 or db > 1e-6) else '  <-- drives nothing or breaks the model'
            print(f'  param {alias}={val:g}: +10% -> dV {dv:+.2f}%  max dBBox {db:.3g}  valid {ok}{tag}')
            sh.set(cell, old)
            doc.recompute()


if __name__ == '__main__':
    main()
