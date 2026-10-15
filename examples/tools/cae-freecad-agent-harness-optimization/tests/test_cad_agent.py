# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the pure helpers of the Harbor agent in harness/cad_agent.py.

No Harbor, FreeCAD, Helix, Docker or network needed.
"""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "harness"))

from cad_agent import from_container, session_id, task_mesh  # noqa: E402


class FromContainer(unittest.TestCase):
    def test_points_localhost_at_the_docker_host(self):
        self.assertEqual(from_container("http://127.0.0.1:9080/apis/intake"),
                         "http://host.docker.internal:9080/apis/intake")
        self.assertEqual(from_container("http://localhost:8080"), "http://host.docker.internal:8080")

    def test_keeps_a_remote_host(self):
        self.assertEqual(from_container("https://helix.example.com/apis"), "https://helix.example.com/apis")


class TaskMesh(unittest.TestCase):
    def test_reads_the_mesh_the_instruction_names(self):
        self.assertEqual(task_mesh("Turn the mesh at\n`/app/reference_part_2.obj`\ninto"),
                         "/app/reference_part_2.obj")


class SessionId(unittest.TestCase):
    def test_reads_the_printed_session(self):
        output = "trace session 01a140ea-bc9f-7483-8cb0-6355ffac74fa\nstopped after 300 s\n"
        self.assertEqual(session_id(output), "01a140ea-bc9f-7483-8cb0-6355ffac74fa")

    def test_none_when_the_runner_failed_early(self):
        self.assertIsNone(session_id("Traceback (most recent call last):\n"))


if __name__ == "__main__":
    unittest.main()
