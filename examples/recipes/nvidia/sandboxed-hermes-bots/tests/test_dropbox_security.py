# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Security regression tests for explicit host-side video transfer."""

import importlib.util
import io
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "plugins" / "dropbox" / "__init__.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("swarm_dropbox_security_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _NoHooks:
    def register_hook(self, *_args, **_kwargs):
        raise AssertionError("the plugin must not inspect chat turns")


class DropboxSecurityTests(unittest.TestCase):
    def setUp(self):
        self.dropbox = _load_module()

    def test_register_never_installs_a_chat_hook(self):
        with mock.patch.object(self.dropbox, "upload_video_from_operator") as upload:
            self.dropbox.register(_NoHooks())
        upload.assert_not_called()
        self.assertFalse(hasattr(self.dropbox, "_on_turn"))
        self.assertFalse(hasattr(self.dropbox, "_video_paths"))

    def test_arbitrary_chat_path_has_no_automatic_entry_point(self):
        hostile = '@file:"/Users/operator/private/clip.mp4"'
        self.assertNotIn(hostile, vars(self.dropbox).values())
        with mock.patch.object(self.dropbox.os, "open") as host_open:
            self.dropbox.register(_NoHooks())
        host_open.assert_not_called()

    def test_operator_helper_rejects_unsupported_extension_before_open(self):
        with mock.patch.object(self.dropbox.os, "open") as host_open:
            ok, error = self.dropbox.upload_video_from_operator("private.txt", "vss")
        self.assertFalse(ok)
        self.assertIn(".mp4", error)
        host_open.assert_not_called()

    def test_operator_helper_rejects_malformed_path_without_exception(self):
        with mock.patch.object(self.dropbox.os, "open") as host_open:
            ok, error = self.dropbox.upload_video_from_operator("\x00.mp4", "vss")
        self.assertFalse(ok)
        self.assertIn("inspect", error)
        host_open.assert_not_called()

    def test_operator_helper_requires_a_wrapper_selected_sandbox(self):
        for sandbox in ("", "--foreign", "bad/name", "bad\nname"):
            with self.subTest(sandbox=repr(sandbox)), \
                    mock.patch.object(self.dropbox.os, "open") as host_open:
                ok, error = self.dropbox.upload_video_from_operator("clip.mp4", sandbox)
                self.assertFalse(ok)
                self.assertIn("sandbox", error)
                host_open.assert_not_called()

    def test_operator_helper_rejects_final_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real.mp4"
            real.write_bytes(b"video")
            link = root / "link.mp4"
            link.symlink_to(real)
            with mock.patch.object(self.dropbox.subprocess, "run") as run:
                ok, error = self.dropbox.upload_video_from_operator(link, "vss")
        self.assertFalse(ok)
        self.assertIn("symbolic-link", error)
        run.assert_not_called()

    def test_operator_helper_rejects_empty_and_oversize_files(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.mp4"
            empty.touch()
            ok, error = self.dropbox.upload_video_from_operator(empty, "vss")
            self.assertFalse(ok)
            self.assertIn("empty", error)

            large = Path(directory) / "large.mp4"
            large.write_bytes(b"12345")
            with mock.patch.object(self.dropbox, "MAX_BYTES", 4):
                ok, error = self.dropbox.upload_video_from_operator(large, "vss")
            self.assertFalse(ok)
            self.assertIn("limit", error)

    def test_operator_helper_rejects_special_files_without_opening_them(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "stream.mp4"
            os.mkfifo(fifo)
            with mock.patch.object(self.dropbox.os, "open", wraps=self.dropbox.os.open) as host_open:
                ok, error = self.dropbox.upload_video_from_operator(fifo, "vss")
        self.assertFalse(ok)
        self.assertIn("regular file", error)
        host_open.assert_not_called()

    def test_operator_helper_uploads_only_the_explicit_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "operator clip.mp4"
            source.write_bytes(b"selected-video")
            observed = {}

            def fake_run(command, **kwargs):
                staged_dir = Path(command[-2])
                observed["command"] = command
                observed["content"] = (staged_dir / "operator_clip.mp4").read_bytes()
                observed["kwargs"] = kwargs
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch.object(self.dropbox.shutil, "which", return_value="/usr/bin/openshell"), \
                    mock.patch.object(self.dropbox.subprocess, "run", side_effect=fake_run):
                ok, name = self.dropbox.upload_video_from_operator(source, "owned-vss")

        self.assertTrue(ok)
        self.assertEqual(name, "operator_clip.mp4")
        self.assertEqual(observed["content"], b"selected-video")
        self.assertEqual(observed["command"][:5], [
            "openshell", "sandbox", "upload", "--no-git-ignore", "owned-vss",
        ])
        self.assertEqual(Path(observed["command"][-2]).name, "videos")
        self.assertEqual(observed["command"][-1], "/sandbox")
        self.assertFalse(observed["kwargs"]["check"])

    def test_sanitized_name_matches_the_swarm_command_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / ".operator clip.mp4"
            source.write_bytes(b"selected-video")

            def fake_run(command, **_kwargs):
                self.assertTrue((Path(command[-2]) / "video_.operator_clip.mp4").is_file())
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch.object(self.dropbox.shutil, "which", return_value="/usr/bin/openshell"), \
                    mock.patch.object(self.dropbox.subprocess, "run", side_effect=fake_run):
                ok, name = self.dropbox.upload_video_from_operator(source, "owned-vss")
        self.assertTrue(ok)
        self.assertRegex(name, r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

    def test_cli_requires_explicit_sandbox_and_path(self):
        output = io.StringIO()
        with mock.patch.object(self.dropbox, "upload_video_from_operator", return_value=(True, "clip.mp4")) as upload, \
                mock.patch("sys.stdout", output):
            code = self.dropbox.main(["--sandbox", "owned-vss", "clip.mp4"])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), "clip.mp4\n")
        upload.assert_called_once_with("clip.mp4", "owned-vss")


if __name__ == "__main__":
    unittest.main()
