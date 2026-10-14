# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the pure helpers of the Harbor agent in harness/helix_cad_agent.py.

No Harbor, FreeCAD, Helix or network needed.
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "harness"))

from helix_cad_agent import MESHES, document_name, pick_trace, task_mesh  # noqa: E402

STARTED = datetime(2026, 10, 9, 8, 23, 0, tzinfo=timezone.utc)


class DocumentName(unittest.TestCase):
    def test_reads_the_requested_document(self):
        self.assertEqual(document_name("Build it in a new FreeCAD document named `EvalPart`, from"),
                         "EvalPart")

    def test_rejects_an_instruction_without_one(self):
        with self.assertRaises(ValueError):
            document_name("Build a part.")


class TaskMesh(unittest.TestCase):
    def test_defaults_to_the_first_reference_part(self):
        self.assertEqual(task_mesh("Turn the mesh at `@MESH_PATH@` into"), MESHES / "reference_part.obj")

    def test_reads_a_named_mesh(self):
        self.assertEqual(task_mesh("Turn the mesh at `@MESH_PATH:reference_part_2.obj@` into"),
                         MESHES / "reference_part_2.obj")


class PickTrace(unittest.TestCase):
    def test_takes_the_finished_trace_started_after_the_trial(self):
        traces = [
            {"id": "new", "started_at": "2026-10-09T08:24:00", "ended_at": "2026-10-09T08:26:00"},
            {"id": "old", "started_at": "2026-10-09T08:00:00", "ended_at": "2026-10-09T08:02:00"},
        ]
        self.assertEqual(pick_trace(traces, STARTED)["id"], "new")

    def test_ignores_a_trace_still_being_written(self):
        traces = [{"id": "running", "started_at": "2026-10-09T08:24:00", "ended_at": None}]
        self.assertIsNone(pick_trace(traces, STARTED))

    def test_ignores_traces_from_before_the_trial(self):
        traces = [{"id": "old", "started_at": "2026-10-09T08:00:00", "ended_at": "2026-10-09T08:02:00"}]
        self.assertIsNone(pick_trace(traces, STARTED))


if __name__ == "__main__":
    unittest.main()
