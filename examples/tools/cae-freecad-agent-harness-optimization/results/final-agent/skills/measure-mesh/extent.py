# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# How far the mesh reaches along a line: for a straight feature (arm, bar, boss, shaft),
# where its two ends are, measured along its direction from a point on its axis.
#
#   MESH=/app/reference.obj ORIGIN=x,y,z DIR=dx,dy,dz [RADIUS=r] freecadcmd extent.py 2>&1 | grep -v '%)'
#
# Considers the mesh vertices within RADIUS of the line (default: 0.75 x the largest
# half-width of the section through ORIGIN normal to DIR) and prints the distances
# along DIR (negative = behind ORIGIN) of the nearest and farthest one, with the world
# points of the axis there. Pad a section cut normal to DIR through ORIGIN by `ahead`
# along DIR and by `behind` back (two-sided).
import os

import FreeCAD as App
import Mesh
import numpy as np

App.Console.SetStatus('Console', 'Log', False)
m = Mesh.Mesh(os.environ.get('MESH', '/app/reference.obj'))
O = np.array([float(x) for x in os.environ['ORIGIN'].split(',')])
d = np.array([float(x) for x in os.environ['DIR'].split(',')])
d /= np.linalg.norm(d)
P = np.array([[p.x, p.y, p.z] for p in m.Points])
if 'RADIUS' in os.environ:
    R = float(os.environ['RADIUS'])
else:
    sec = m.crossSections([(App.Vector(*O), App.Vector(*d))], 1e-6)[0]
    best = None
    for s in sec:
        q = np.array([[p.x, p.y, p.z] for p in s])
        r = np.linalg.norm(q - O - np.outer((q - O) @ d, d), axis=1)
        if best is None or r.min() < best[0]:
            best = (r.min(), r.max())
    R = 0.75 * best[1] if best else 1.0
t = (P - O) @ d
r = np.linalg.norm(P - O - np.outer(t, d), axis=1)
sel = r <= R
# keep the contiguous run of the feature around ORIGIN (stop at gaps longer than R)
ts = np.sort(t[sel])
i0 = int(np.searchsorted(ts, 0.0))
lo_i, hi_i = max(i0 - 1, 0), min(i0, len(ts) - 1)
while lo_i > 0 and ts[lo_i] - ts[lo_i - 1] < R:
    lo_i -= 1
while hi_i < len(ts) - 1 and ts[hi_i + 1] - ts[hi_i] < R:
    hi_i += 1
behind, ahead = -ts[lo_i], ts[hi_i]
print(f'axis through {tuple(round(float(v), 3) for v in O)} direction {tuple(round(float(v), 4) for v in d)}, radius {R:.3f}: '
      f'{sel.sum()} vertices', flush=True)
print(f'ahead {ahead:.3f} (end at {tuple(round(float(v), 3) for v in O + ahead * d)})  behind {behind:.3f} '
      f'(end at {tuple(round(float(v), 3) for v in O - behind * d)})  length {ahead + behind:.3f}', flush=True)
print('note: where the feature joins a body, "behind" runs on into the body; stop the feature '
      'about one wall thickness inside the body surface there.', flush=True)
