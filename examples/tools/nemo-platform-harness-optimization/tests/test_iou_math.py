# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the pure-NumPy half of the IoU scorer.

Every expected value here is computed by hand. Requires NumPy only: no
FreeCAD, no running FreeCAD session, no network, no API key.

Run with::

    python3 -m unittest discover -s tests -v
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scorer"))

from iou_math import (  # noqa: E402
    CELL_MIN, X_OFFSET, Y_OFFSET, crossings, grid_axes, intervals,
    iou_from_crossings, length, overlap, resolve_cell)


def triangle(z_at):
    """A triangle spanning the XY region x>=0, y>=0, x+y<=6.

    ``z_at`` maps a vertex ``(x, y)`` to its z, so a caller can build either a
    flat plane or a tilted one and know the interpolated z by hand.
    """
    verts = [(0.0, 0.0), (6.0, 0.0), (0.0, 6.0)]
    a, b, c = [np.array([[x, y, float(z_at(x, y))]]) for x, y in verts]
    return a, b, c


def stack(tris):
    """Concatenate ``(A, B, C)`` triples into single per-vertex arrays."""
    return (np.concatenate([t[0] for t in tris]),
            np.concatenate([t[1] for t in tris]),
            np.concatenate([t[2] for t in tris]))


class TestIntervals(unittest.TestCase):
    def test_pairs_sorted_crossings(self):
        self.assertEqual(intervals([3.0, 1.0, 4.0, 2.0]), [(1.0, 2.0), (3.0, 4.0)])

    def test_sorts_before_pairing(self):
        self.assertEqual(intervals([10.0, 0.0]), [(0.0, 10.0)])

    def test_empty_column_is_empty_list_not_none(self):
        self.assertEqual(intervals([]), [])

    def test_odd_crossing_count_is_unusable(self):
        # A ray that grazed an edge or vertex: no honest interval exists.
        self.assertIsNone(intervals([1.0, 2.0, 3.0]))
        self.assertIsNone(intervals([5.0]))


class TestLength(unittest.TestCase):
    def test_sums_interval_lengths(self):
        self.assertAlmostEqual(length([(1.0, 2.0), (3.0, 7.0)]), 5.0)

    def test_empty_is_zero(self):
        self.assertAlmostEqual(length([]), 0.0)

    def test_zero_width_interval_contributes_nothing(self):
        self.assertAlmostEqual(length([(4.0, 4.0)]), 0.0)


class TestOverlap(unittest.TestCase):
    def test_disjoint(self):
        self.assertAlmostEqual(overlap([(0.0, 1.0)], [(2.0, 3.0)]), 0.0)

    def test_touching_endpoints_do_not_overlap(self):
        self.assertAlmostEqual(overlap([(0.0, 1.0)], [(1.0, 2.0)]), 0.0)

    def test_nested(self):
        self.assertAlmostEqual(overlap([(0.0, 10.0)], [(3.0, 5.0)]), 2.0)

    def test_nested_is_symmetric(self):
        self.assertAlmostEqual(overlap([(3.0, 5.0)], [(0.0, 10.0)]), 2.0)

    def test_partial(self):
        self.assertAlmostEqual(overlap([(0.0, 5.0)], [(3.0, 8.0)]), 2.0)

    def test_identical(self):
        self.assertAlmostEqual(overlap([(2.0, 6.0)], [(2.0, 6.0)]), 4.0)

    def test_multiple_intervals_each_side(self):
        # (0,4) vs (3,5) -> 1 ; (0,4) vs (10,12) -> 0
        # (6,9) vs (3,5) -> 0 ; (6,9) vs (10,12) -> 0
        self.assertAlmostEqual(
            overlap([(0.0, 4.0), (6.0, 9.0)], [(3.0, 5.0), (10.0, 12.0)]), 1.0)

    def test_empty_side(self):
        self.assertAlmostEqual(overlap([], [(0.0, 1.0)]), 0.0)


class TestResolveCell(unittest.TestCase):
    def test_scales_with_diagonal(self):
        self.assertAlmostEqual(resolve_cell(2000.0), 1.0)

    def test_floors_at_cell_min(self):
        # 20 / 2000 = 0.01, below the 0.10 mm floor.
        self.assertAlmostEqual(resolve_cell(20.0), CELL_MIN)

    def test_rounds_to_three_decimals(self):
        # 1234.5678 / 2000 = 0.6172839 -> 0.617
        self.assertAlmostEqual(resolve_cell(1234.5678), 0.617)

    def test_explicit_divisor_and_minimum(self):
        self.assertAlmostEqual(resolve_cell(100.0, divisor=10, minimum=0.0), 10.0)


class TestGridAxes(unittest.TestCase):
    def test_counts_and_offsets(self):
        xs, ys, nx, ny = grid_axes(0.0, 0.0, 2.0, 1.0, 1.0)
        self.assertEqual((nx, ny), (3, 2))
        np.testing.assert_allclose(
            xs, [X_OFFSET, 1 + X_OFFSET, 2 + X_OFFSET])
        np.testing.assert_allclose(ys, [Y_OFFSET, 1 + Y_OFFSET])

    def test_offset_keeps_rays_off_integer_facet_edges(self):
        xs, _, _, _ = grid_axes(0.0, 0.0, 5.0, 5.0, 1.0)
        for x in xs:
            self.assertNotAlmostEqual(x, round(x))


class TestCrossings(unittest.TestCase):
    #: Two columns, one row. Column index is i * ny + j == i.
    XS = np.array([1.0, 3.0])
    YS = np.array([1.0])
    NX, NY, CELL = 2, 1, 2.0

    def test_flat_triangle_hits_every_column_it_covers(self):
        A, B, C = triangle(lambda x, y: 4.0)
        got = crossings(A, B, C, self.XS, self.YS, self.NX, self.NY, self.CELL)
        self.assertEqual(sorted(got), [0, 1])
        self.assertAlmostEqual(got[0][0], 4.0)
        self.assertAlmostEqual(got[1][0], 4.0)

    def test_tilted_triangle_interpolates_z(self):
        # Vertices (0,0,0), (6,0,6), (0,6,0) define the plane z = x.
        A, B, C = triangle(lambda x, y: x)
        got = crossings(A, B, C, self.XS, self.YS, self.NX, self.NY, self.CELL)
        self.assertAlmostEqual(got[0][0], 1.0)   # ray at x=1
        self.assertAlmostEqual(got[1][0], 3.0)   # ray at x=3

    def test_triangle_outside_the_grid_is_skipped(self):
        A = np.array([[100.0, 100.0, 0.0]])
        B = np.array([[106.0, 100.0, 0.0]])
        C = np.array([[100.0, 106.0, 0.0]])
        self.assertEqual(
            crossings(A, B, C, self.XS, self.YS, self.NX, self.NY, self.CELL), {})

    def test_triangle_degenerate_in_xy_is_skipped(self):
        # Zero area in XY: the barycentric denominator vanishes, so no ray can
        # meaningfully cross it.
        A = np.array([[0.0, 0.0, 0.0]])
        B = np.array([[0.0, 0.0, 5.0]])
        C = np.array([[0.0, 0.0, 9.0]])
        self.assertEqual(
            crossings(A, B, C, self.XS, self.YS, self.NX, self.NY, self.CELL), {})

    def test_two_triangles_stack_two_crossings_per_column(self):
        A, B, C = stack([triangle(lambda x, y: 0.0), triangle(lambda x, y: 10.0)])
        got = crossings(A, B, C, self.XS, self.YS, self.NX, self.NY, self.CELL)
        self.assertEqual(sorted(got[0]), [0.0, 10.0])
        self.assertEqual(sorted(got[1]), [0.0, 10.0])


class TestIouFromCrossings(unittest.TestCase):
    def test_identical_columns_score_one(self):
        cols = {0: [0.0, 4.0]}
        iou, bad, n = iou_from_crossings(cols, dict(cols))
        self.assertAlmostEqual(iou, 1.0)
        self.assertEqual((bad, n), (0, 1))

    def test_nested_single_column(self):
        # cand (0,10) len 10, ref (3,5) len 2, overlap 2
        # -> 2 / (10 + 2 - 2) = 0.2
        iou, bad, n = iou_from_crossings({0: [0.0, 10.0]}, {0: [3.0, 5.0]})
        self.assertAlmostEqual(iou, 0.2)
        self.assertEqual((bad, n), (0, 1))

    def test_column_present_on_one_side_only_is_pure_union(self):
        # col 0: inter 2, union 10 ; col 1: cand (0,4), ref empty -> union 4
        # -> 2 / 14
        iou, bad, n = iou_from_crossings(
            {0: [0.0, 10.0], 1: [0.0, 4.0]}, {0: [3.0, 5.0]})
        self.assertAlmostEqual(iou, 2.0 / 14.0)
        self.assertEqual((bad, n), (0, 2))

    def test_degenerate_column_is_excluded_not_scored_zero(self):
        # col 1 has an odd crossing count on the candidate side, so it is
        # dropped entirely -- it must not drag the score down as a miss.
        iou, bad, n = iou_from_crossings(
            {0: [0.0, 10.0], 1: [1.0]}, {0: [3.0, 5.0], 1: [0.0, 4.0]})
        self.assertAlmostEqual(iou, 0.2)
        self.assertEqual((bad, n), (1, 2))

    def test_disjoint_geometry_scores_zero(self):
        iou, _, _ = iou_from_crossings({0: [0.0, 1.0]}, {0: [5.0, 6.0]})
        self.assertAlmostEqual(iou, 0.0)

    def test_no_columns_scores_zero(self):
        self.assertEqual(iou_from_crossings({}, {}), (0.0, 0, 0))

    def test_all_columns_degenerate_scores_zero(self):
        iou, bad, n = iou_from_crossings({0: [1.0]}, {0: [2.0]})
        self.assertAlmostEqual(iou, 0.0)
        self.assertEqual((bad, n), (1, 1))


class TestEndToEndColumn(unittest.TestCase):
    """One column, from triangles to IoU, with the answer computed by hand."""

    def test_slab_against_thinner_slab(self):
        xs, ys, nx, ny, cell = np.array([1.0]), np.array([1.0]), 1, 1, 2.0
        cand = stack([triangle(lambda x, y: 0.0), triangle(lambda x, y: 10.0)])
        ref = stack([triangle(lambda x, y: 3.0), triangle(lambda x, y: 5.0)])
        ca = crossings(*cand, xs, ys, nx, ny, cell)
        ra = crossings(*ref, xs, ys, nx, ny, cell)
        # candidate occupies z 0..10, reference z 3..5:
        # intersection 2, union 10 + 2 - 2 = 10 -> IoU 0.2
        iou, bad, n = iou_from_crossings(ca, ra)
        self.assertEqual((bad, n), (0, 1))
        self.assertAlmostEqual(iou, 0.2)

    def test_offset_slabs_partial_overlap(self):
        xs, ys, nx, ny, cell = np.array([1.0]), np.array([1.0]), 1, 1, 2.0
        cand = stack([triangle(lambda x, y: 0.0), triangle(lambda x, y: 6.0)])
        ref = stack([triangle(lambda x, y: 4.0), triangle(lambda x, y: 8.0)])
        ca = crossings(*cand, xs, ys, nx, ny, cell)
        ra = crossings(*ref, xs, ys, nx, ny, cell)
        # 0..6 vs 4..8: intersection 2, union 6 + 4 - 2 = 8 -> 0.25
        iou, _, _ = iou_from_crossings(ca, ra)
        self.assertAlmostEqual(iou, 0.25)


if __name__ == "__main__":
    unittest.main()
