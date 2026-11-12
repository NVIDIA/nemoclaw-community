# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Setup copies only regular files that are inside the approved folder.

These tests cover the host-side copy filter. They do not test the sandbox
boundary. The live test suite does that.
"""

import os
import tempfile
import unittest
from pathlib import Path

from localonly.workspace import WorkspaceRejected, list_approved_files, resolve_approved_path


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.base = Path(self._temp.name).resolve()
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        (self.workspace / "hello.txt").write_text("Hello RTX", encoding="utf-8")
        self.private = self.base / "private.txt"
        self.private.write_text("secret", encoding="utf-8")


class ResolveApprovedPathTests(WorkspaceCase):
    def test_reads_approved_file(self):
        path = resolve_approved_path(self.workspace, "hello.txt")
        self.assertEqual(path.read_text(encoding="utf-8"), "Hello RTX")

    def test_reads_approved_file_in_a_subfolder(self):
        (self.workspace / "notes").mkdir()
        (self.workspace / "notes" / "a.md").write_text("A", encoding="utf-8")
        self.assertEqual(
            resolve_approved_path(self.workspace, "notes/a.md"), self.workspace / "notes" / "a.md",
        )

    def test_denies_parent_traversal(self):
        for requested in ("../private.txt", "notes/../../private.txt", ".."):
            with self.subTest(requested=requested):
                with self.assertRaises(WorkspaceRejected):
                    resolve_approved_path(self.workspace, requested)

    def test_denies_absolute_path_to_a_file_outside(self):
        with self.assertRaises(WorkspaceRejected):
            resolve_approved_path(self.workspace, str(self.private))

    def test_denies_absolute_path_to_a_file_inside(self):
        with self.assertRaises(WorkspaceRejected):
            resolve_approved_path(self.workspace, str(self.workspace / "hello.txt"))

    def test_denies_symlink_to_a_file_outside(self):
        os.symlink(self.private, self.workspace / "link.txt")
        with self.assertRaises(WorkspaceRejected):
            resolve_approved_path(self.workspace, "link.txt")

    def test_denies_symlinked_folder_on_the_path(self):
        os.symlink(self.base, self.workspace / "up")
        with self.assertRaises(WorkspaceRejected):
            resolve_approved_path(self.workspace, "up/private.txt")

    def test_denies_missing_file_empty_path_and_directory(self):
        (self.workspace / "notes").mkdir()
        for requested in ("missing.txt", "", "notes"):
            with self.subTest(requested=requested):
                with self.assertRaises(WorkspaceRejected):
                    resolve_approved_path(self.workspace, requested)

    def test_rejection_is_a_permission_error(self):
        self.assertTrue(issubclass(WorkspaceRejected, PermissionError))


class ListApprovedFilesTests(WorkspaceCase):
    def test_lists_regular_files_with_relative_paths(self):
        (self.workspace / "notes").mkdir()
        (self.workspace / "notes" / "a.md").write_text("A", encoding="utf-8")
        files = list_approved_files(self.workspace)
        self.assertEqual([str(item.relative) for item in files], ["hello.txt", "notes/a.md"])
        self.assertEqual(files[0].source, self.workspace / "hello.txt")

    def test_rejects_a_symlinked_file(self):
        os.symlink(self.private, self.workspace / "link.txt")
        with self.assertRaises(WorkspaceRejected):
            list_approved_files(self.workspace)

    def test_rejects_a_symlinked_folder(self):
        os.symlink(self.base, self.workspace / "up")
        with self.assertRaises(WorkspaceRejected):
            list_approved_files(self.workspace)

    def test_rejects_an_approved_folder_that_is_a_symlink(self):
        os.symlink(self.workspace, self.base / "alias")
        with self.assertRaises(WorkspaceRejected):
            list_approved_files(self.base / "alias")

    def test_rejects_an_oversized_file(self):
        (self.workspace / "big.bin").write_bytes(b"x" * 11)
        with self.assertRaises(WorkspaceRejected):
            list_approved_files(self.workspace, max_file_bytes=10)

    def test_rejects_too_many_files(self):
        (self.workspace / "second.txt").write_text("2", encoding="utf-8")
        with self.assertRaises(WorkspaceRejected):
            list_approved_files(self.workspace, max_files=1)

    def test_rejects_a_name_that_breaks_the_copy_command(self):
        (self.workspace / "a:b.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(WorkspaceRejected):
            list_approved_files(self.workspace)

    def test_sample_folder_of_the_recipe_is_accepted(self):
        sample = Path(__file__).resolve().parents[2] / "fixtures" / "workspace"
        names = [str(item.relative) for item in list_approved_files(sample)]
        self.assertIn("hello.txt", names)


if __name__ == "__main__":
    unittest.main()
