# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Focused tests for the teammates message and image-forwarding contract."""

import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock


EXAMPLE_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


schemas = _load_module(
    "sandboxed_hermes_teammates_schemas",
    EXAMPLE_ROOT / "plugins" / "teammates" / "schemas.py",
)
tools = _load_module(
    "sandboxed_hermes_teammates_tools",
    EXAMPLE_ROOT / "plugins" / "teammates" / "tools.py",
)


class _Reply:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(
            {
                "choices": [{"message": {"content": "acknowledged"}}],
                "usage": {"total_tokens": 7},
            }
        ).encode("utf-8")


class TeammatesMessageTest(unittest.TestCase):
    def setUp(self):
        tools._TURN_IMAGES.clear()
        self.request = None

    def _urlopen(self, request, timeout):
        self.assertEqual(timeout, tools._TIMEOUT_S)
        self.request = request
        return _Reply()

    def _send(self, message: str, *, with_images=False):
        args = {"teammate": "reviewer", "message": message}
        if with_images:
            args["with_images"] = True
        with (
            mock.patch.object(
                tools,
                "_load_peers",
                return_value={"reviewer": {"url": "http://reviewer.test:8080", "note": ""}},
            ),
            mock.patch.object(tools, "_peer_key", return_value="test-key"),
            mock.patch.object(tools.urllib.request, "urlopen", side_effect=self._urlopen),
        ):
            result = json.loads(tools.message_teammate(args, session_id="session-1"))
        self.assertIsNotNone(self.request)
        return result, json.loads(self.request.data.decode("utf-8"))

    def test_schema_describes_image_forwarding_as_opt_in(self):
        description = schemas.MESSAGE_TEAMMATE["description"]
        self.assertIn("not forwarded by default", description)
        self.assertIn("with_images=true", description)
        self.assertNotIn("automatically", description)

    def test_generic_look_and_see_request_stays_unchanged(self):
        tools.remember_turn_images(
            "session-1",
            [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
        )
        message = "Please look into issue 42 and see whether its checks pass."
        result, payload = self._send(message)
        self.assertEqual(payload["messages"][0]["content"], message)
        self.assertNotIn("images_forwarded", result)

    def test_explicit_image_reference_gets_missing_image_notice(self):
        _, payload = self._send("Please inspect this attached image for damage.")
        content = payload["messages"][0]["content"]
        self.assertIn("No image is attached", content)
        self.assertIn("do not guess", content)

    def test_sender_local_image_path_is_removed_without_forwarding(self):
        _, payload = self._send("Review [Image attached at: /tmp/red.png] carefully.")
        content = payload["messages"][0]["content"]
        self.assertNotIn("/tmp/red.png", content)
        self.assertIn("an image", content)
        self.assertIn("No image is attached", content)

    def test_with_images_forwards_current_turn_and_reports_count(self):
        image_url = "data:image/png;base64,AAAA"
        tools.remember_turn_images(
            "session-1",
            [{"type": "image_url", "image_url": {"url": image_url}}],
        )
        result, payload = self._send(
            "Please inspect [Image attached at: /tmp/red.png].",
            with_images=True,
        )
        content = payload["messages"][0]["content"]
        self.assertIsInstance(content, list)
        self.assertNotIn("/tmp/red.png", content[0]["text"])
        self.assertEqual(content[1]["image_url"]["url"], image_url)
        self.assertEqual(result["images_forwarded"], 1)


if __name__ == "__main__":
    unittest.main()
