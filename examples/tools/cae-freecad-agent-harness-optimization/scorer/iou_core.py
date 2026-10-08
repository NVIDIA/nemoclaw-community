# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""IoU between a BREP solid and a reference mesh, run inside FreeCAD.

This module is the FreeCAD half of the scorer: it imports the BREP, tessellates
it, loads the reference mesh, and hands the triangles to ``iou_math``, which
holds the algorithm and imports nothing from FreeCAD.

Exact along Z, discretized only in XY. Avoids OCC booleans and FreeCAD mesh
booleans, both of which fail or crash on these inputs.

Usage, from a FreeCAD interpreter::

    FreeCAD -c   # then, on stdin:
    import sys; sys.argv = ['iou_core', CANDIDATE_BREP, REFERENCE_MESH]
    exec(open('iou_core.py').read())

``FreeCAD -c`` reads stdin as an interactive console and mis-parses multi-line
blocks, which is why the caller uses ``exec()`` of this file rather than a
heredoc. Output contract: one ``IOU <value>`` line on stdout; diagnostics go to
stderr.
"""

import os
import sys
import time

import numpy as np

import Part, Mesh, MeshPart

# score.py puts this file's directory on sys.path in the preamble it feeds to
# FreeCAD, so a plain import is enough.
from iou_math import crossings, grid_axes, iou_from_crossings, resolve_cell


def tris_from_mesh(m):
    """Return per-triangle vertex arrays ``(A, B, C)`` for a FreeCAD mesh."""
    pts, facets = m.Topology
    P = np.asarray([[p.x, p.y, p.z] for p in pts], dtype=float)
    F = np.asarray(facets, dtype=np.int64)
    return P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]


def main(argv):
    if len(argv) < 3:
        sys.exit("usage: iou_core.py CANDIDATE_BREP REFERENCE_MESH")
    brep, meshf = argv[1], argv[2]

    t0 = time.time()
    s = Part.Shape(); s.importBrep(brep)
    cand = MeshPart.meshFromShape(Shape=s, LinearDeflection=0.02,
                                  AngularDeflection=0.15, Relative=False)
    ref = Mesh.Mesh(meshf)

    bb = cand.BoundBox; bb.add(ref.BoundBox)
    cell = resolve_cell(bb.DiagonalLength)
    bb.enlarge(cell)
    xs, ys, nx, ny = grid_axes(bb.XMin, bb.YMin, bb.XMax, bb.YMax, cell)

    ca = crossings(*tris_from_mesh(cand), xs, ys, nx, ny, cell)
    ra = crossings(*tris_from_mesh(ref), xs, ys, nx, ny, cell)

    iou, bad, cols = iou_from_crossings(ca, ra)

    # Diagnostics go to stderr: stdout carries only the IOU line, which the
    # caller parses.
    print("DBG cell", cell, "cols", cols, "degenerate", bad,
          "cand_vol", round(cand.Volume, 2), "ref_vol", round(ref.Volume, 2),
          "secs", round(time.time() - t0, 1), file=sys.stderr)
    print("IOU", round(iou, 4))


main(sys.argv)
