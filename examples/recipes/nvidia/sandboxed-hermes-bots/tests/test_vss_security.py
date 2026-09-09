# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Security regression tests for VSS media resolution."""

import base64
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "plugins" / "vss" / "tools.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("swarm_vss_security_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VssSecurityTests(unittest.TestCase):
    def setUp(self):
        self.vss = _load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.video_dir = Path(self.temp.name) / "videos"
        self.video_dir.mkdir()
        self.video_dir_patch = mock.patch.object(self.vss, "_VIDEO_DIR", str(self.video_dir))
        self.video_dir_patch.start()
        self.addCleanup(self.video_dir_patch.stop)

    def test_rejects_http_https_and_other_uri_schemes(self):
        for value in (
            "http://attacker.example/clip.mp4",
            "HTTPS://attacker.example/clip.mp4",
            "file:///etc/passwd.mp4",
            "data:video/mp4;base64,AAAA",
        ):
            with self.subTest(value=value):
                url, error = self.vss._resolve_video(value)
                self.assertEqual(url, "")
                self.assertIn("not accepted", error)

    def test_rejects_malformed_untrusted_references_without_exception(self):
        for value in ("http://[", "\x00.mp4"):
            with self.subTest(value=repr(value)):
                url, error = self.vss._resolve_video(value)
                self.assertEqual(url, "")
                self.assertTrue(error)

    def test_rejects_relative_and_absolute_traversal(self):
        outside = Path(self.temp.name) / "outside.mp4"
        outside.write_bytes(b"outside")
        inside = self.video_dir / "inside.mp4"
        inside.write_bytes(b"inside")
        for value in ("../outside.mp4", "nested/../inside.mp4", str(outside)):
            with self.subTest(value=value):
                url, error = self.vss._resolve_video(value)
                self.assertEqual(url, "")
                self.assertIn("confined", error.lower())

    def test_rejects_symlink_escape_and_internal_symlink(self):
        outside = Path(self.temp.name) / "outside.mp4"
        outside.write_bytes(b"outside")
        regular = self.video_dir / "regular.mp4"
        regular.write_bytes(b"inside")
        links = [self.video_dir / "escape.mp4", self.video_dir / "alias.mp4"]
        links[0].symlink_to(outside)
        links[1].symlink_to(regular)
        for link in links:
            with self.subTest(link=link.name):
                url, error = self.vss._resolve_video(link.name)
                self.assertEqual(url, "")
                self.assertIn("symlink", error.lower())

    def test_rejects_symlinked_directory_component(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "clip.mp4").write_bytes(b"outside")
        inside = self.video_dir / "inside"
        inside.mkdir()
        (inside / "clip.mp4").write_bytes(b"inside")
        links = {
            "outside-link": outside,
            "inside-link": inside,
        }
        for name, target in links.items():
            (self.video_dir / name).symlink_to(target, target_is_directory=True)
            with self.subTest(name=name):
                url, error = self.vss._resolve_video(f"{name}/clip.mp4")
                self.assertEqual(url, "")
                self.assertIn("symlink", error.lower())

    def test_accepts_relative_and_absolute_confined_regular_video(self):
        payload = b"local-video"
        clip = self.video_dir / "clip.mp4"
        clip.write_bytes(payload)
        expected = "data:video/mp4;base64," + base64.b64encode(payload).decode("ascii")
        for value in ("clip.mp4", str(clip)):
            with self.subTest(value=value):
                url, error = self.vss._resolve_video(value)
                self.assertIsNone(error)
                self.assertEqual(url, expected)

    def test_accepts_nested_regular_video_without_crossing_symlinks(self):
        nested = self.video_dir / "nested"
        nested.mkdir()
        clip = nested / "clip.webm"
        clip.write_bytes(b"webm")
        url, error = self.vss._resolve_video("nested/clip.webm")
        self.assertIsNone(error)
        self.assertEqual(url, "data:video/webm;base64,d2VibQ==")

    def test_rejects_empty_unsupported_and_oversize_files(self):
        empty = self.video_dir / "empty.mp4"
        empty.touch()
        _, error = self.vss._resolve_video(empty.name)
        self.assertIn("empty", error.lower())

        unsupported = self.video_dir / "notes.txt"
        unsupported.write_bytes(b"not video")
        _, error = self.vss._resolve_video(unsupported.name)
        self.assertIn("must use one of", error)

        large = self.video_dir / "large.mp4"
        large.write_bytes(b"12345")
        with mock.patch.object(self.vss, "_MAX_INLINE_BYTES", 4):
            _, error = self.vss._resolve_video(large.name)
        self.assertIn("inline limit", error)

    def test_rejects_special_file_without_blocking(self):
        fifo = self.video_dir / "stream.mp4"
        os.mkfifo(fifo)
        url, error = self.vss._resolve_video(fifo.name)
        self.assertEqual(url, "")
        self.assertIn("regular file", error)

    def test_tool_rejects_url_without_calling_rt_vlm(self):
        with mock.patch.object(self.vss, "_chat") as chat:
            result = self.vss.vss_ask_video(
                {"video": "https://attacker.example/clip.mp4", "question": "What happens?"}
            )
        self.assertIn("not accepted", result)
        chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
