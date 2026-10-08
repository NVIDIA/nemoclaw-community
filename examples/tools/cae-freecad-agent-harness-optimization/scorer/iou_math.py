# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pure-NumPy geometry for the ray-cast IoU scorer.

Nothing here imports FreeCAD, so the algorithm can be imported and tested in
plain CPython with only NumPy installed. The FreeCAD glue -- BREP import, mesh
tessellation, mesh loading and the CLI -- lives in ``iou_core.py``, which
imports this module.

The method: for every column of a regular XY grid, cast a +Z ray and record
where it crosses each triangle of a surface. Sorted crossings pair up into
solid Z-intervals, so intersection and union are exact along Z and discretized
only in XY.
"""

import numpy as np

# XY sampling pitch, in mm, is resolved from part size so one scorer covers an
# 11 mm mug and a 450 mm wheel rim at comparable cost (~1-4 s): a fixed 0.1 mm
# would make a car part take minutes, and a fixed 0.5 mm would blur the mug's
# walls.
CELL_DIVISOR = 2000  # target ~2000 columns across the bounding diagonal
CELL_MIN = 0.10

# Half-cell offsets keep rays off the axis-aligned facet edges of the mesh,
# where a ray would graze an edge and produce an odd crossing count.
X_OFFSET = 0.5137
Y_OFFSET = 0.4861


def resolve_cell(diagonal_length, divisor=CELL_DIVISOR, minimum=CELL_MIN):
    """Pick the XY sampling pitch for a bounding-box diagonal, in mm."""
    return max(minimum, round(diagonal_length / divisor, 3))


def grid_axes(xmin, ymin, xmax, ymax, cell):
    """Return ``(xs, ys, nx, ny)``: the ray positions of a regular XY grid."""
    nx = int((xmax - xmin) / cell) + 1
    ny = int((ymax - ymin) / cell) + 1
    xs = xmin + cell * (np.arange(nx) + X_OFFSET)
    ys = ymin + cell * (np.arange(ny) + Y_OFFSET)
    return xs, ys, nx, ny


def crossings(A, B, C, xs, ys, nx, ny, cell):
    """Return dict col_index -> list of z where a +Z ray through the column hits.

    ``A``, ``B``, ``C`` are per-triangle vertex arrays of shape ``(n, 3)``.
    A column index is ``i * ny + j`` for grid position ``(xs[i], ys[j])``.
    """
    out = {}
    minx, miny = xs[0], ys[0]
    for a, b, c in zip(A, B, C):
        x0 = min(a[0], b[0], c[0]); x1 = max(a[0], b[0], c[0])
        y0 = min(a[1], b[1], c[1]); y1 = max(a[1], b[1], c[1])
        i0 = max(0, int(np.ceil((x0 - minx) / cell))); i1 = min(nx - 1, int((x1 - minx) / cell))
        j0 = max(0, int(np.ceil((y0 - miny) / cell))); j1 = min(ny - 1, int((y1 - miny) / cell))
        if i0 > i1 or j0 > j1:
            continue
        gx = xs[i0:i1 + 1][:, None]
        gy = ys[j0:j1 + 1][None, :]
        # barycentric in XY
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-15:
            continue
        l1 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / d
        l2 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / d
        l3 = 1.0 - l1 - l2
        hit = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        if not hit.any():
            continue
        z = l1 * a[2] + l2 * b[2] + l3 * c[2]
        ii, jj = np.nonzero(hit)
        for k in range(ii.size):
            col = (i0 + ii[k]) * ny + (j0 + jj[k])
            out.setdefault(col, []).append(float(z[ii[k], jj[k]]))
    return out


def intervals(zs):
    """Pair sorted crossings into solid Z-intervals, or None if unusable.

    An odd crossing count means the ray grazed an edge or vertex, so the
    column carries no usable evidence and is excluded rather than guessed at.
    """
    zs = sorted(zs)
    if len(zs) % 2:            # ray grazed an edge/vertex; column is unusable
        return None
    return list(zip(zs[0::2], zs[1::2]))


def length(iv):
    """Total length of a list of ``(lo, hi)`` intervals."""
    return sum(b - a for a, b in iv)


def overlap(p, q):
    """Total length shared by two lists of ``(lo, hi)`` intervals.

    Touching intervals (``hi == lo``) contribute nothing.
    """
    t = 0.0
    for a, b in p:
        for c, d in q:
            lo, hi = max(a, c), min(b, d)
            if hi > lo:
                t += hi - lo
    return t


def iou_from_crossings(cand_cols, ref_cols):
    """Accumulate IoU over every column touched by either surface.

    Returns ``(iou, degenerate_columns, total_columns)``. Columns where either
    side has an odd crossing count are counted as degenerate and skipped.
    """
    inter = union = 0.0
    bad = 0
    cols = set(cand_cols) | set(ref_cols)
    for col in cols:
        p = intervals(cand_cols.get(col, []))
        q = intervals(ref_cols.get(col, []))
        if p is None or q is None:
            bad += 1
            continue
        lp, lq = length(p), length(q)
        ov = overlap(p, q)
        inter += ov
        union += lp + lq - ov
    return (inter / union if union > 0 else 0.0), bad, len(cols)
