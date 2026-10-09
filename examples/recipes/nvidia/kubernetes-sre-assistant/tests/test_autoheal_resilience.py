# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Exercise the agent actually shipped by this recipe, without a live cluster.

For red/green checks against an upstream checkout, set SRE_AUTOHEAL_TEST_SOURCE
to that checkout's charts/sre-autoheal-agent/files/agent directory. This is a
test-only override; it never changes deployment source selection.
"""
from pathlib import Path
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import patch

RECIPE = Path(__file__).resolve().parents[1]
AGENT_SOURCE = Path(os.environ.get(
    "SRE_AUTOHEAL_TEST_SOURCE",
    str(RECIPE / "charts/sre-autoheal-agent/files/agent"),
)).resolve()
sys.path.insert(0, str(AGENT_SOURCE))

from sre_autoheal import kube  # noqa: E402
from sre_autoheal.llm import LLMClient, LLMUnavailable  # noqa: E402


class AutohealCollectorTests(unittest.TestCase):
    def setUp(self):
        self.transport = kube.HttpTransport("https://cluster.invalid", "test-token", None)
        self.client = kube.KubeClient(self.transport)

    def test_imports_the_selected_recipe_runtime(self):
        self.assertEqual(Path(kube.__file__).resolve().parent.parent, AGENT_SOURCE)

    def test_json_prefix_followed_by_text_is_preserved(self):
        raw = b'{\n  "gpu": 2\n}\nNVML initialization failed\n'
        with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)):
            self.assertEqual(self.client.pod_logs("gpu", "discovery-1", "discovery"), raw.decode())

    def test_json_lines_are_preserved(self):
        raw = b'{"event":"start"}\n{"event":"failure"}\n'
        with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)):
            self.assertEqual(self.client.pod_logs("gpu", "discovery-1", "discovery"), raw.decode())

    def test_json_array_log_is_not_a_resource_response(self):
        raw = b'["configuration"]\nordinary log output\n'
        with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)):
            self.assertEqual(self.client.pod_logs("gpu", "discovery-1", "discovery"), raw.decode())

    def test_previous_logs_request_text_and_keep_query(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"previous log\n")) as call:
            self.assertEqual(self.client.pod_logs("gpu", "discovery-1", "discovery", previous=True), "previous log\n")
        request = call.call_args.args[0]
        self.assertEqual(request.get_header("Accept"), "text/plain")
        self.assertIn("previous=true", request.full_url)

    def test_empty_logs_are_an_empty_string(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"")):
            self.assertEqual(self.client.pod_logs("gpu", "discovery-1", "discovery"), "")

    def test_resource_json_with_whitespace_is_decoded(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b' \n{"items": []}\n')) as call:
            self.assertEqual(self.transport.request("GET", "/api/v1/pods"), {"items": []})
        self.assertEqual(call.call_args.args[0].get_header("Accept"), "application/json")

    def test_resources_named_log_still_use_json(self):
        for resource in ("pods", "services", "configmaps"):
            with self.subTest(resource=resource):
                with patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"metadata":{"name":"log"}}')) as call:
                    result = self.transport.request("GET", f"/api/v1/namespaces/shop/{resource}/log")
                self.assertEqual(result, {"metadata": {"name": "log"}})
                self.assertEqual(call.call_args.args[0].get_header("Accept"), "application/json")

    def test_invalid_resource_json_is_normalized_without_body(self):
        raw = b'{"sensitive":"do-not-report"} trailing'
        with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)):
            with self.assertRaises(kube.KubeError) as raised:
                self.transport.request("GET", "/api/v1/pods")
        self.assertNotIn("do-not-report", str(raised.exception))

    def test_resource_html_is_not_accepted_as_cluster_data(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"<html>proxy error</html>")):
            with self.assertRaises(kube.KubeError):
                self.transport.request("GET", "/api/v1/pods")

    def test_log_timeout_does_not_abort_the_caller(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            self.assertIn("logs unavailable", self.client.pod_logs("gpu", "discovery-1", "discovery"))

    def test_alternate_transport_decoder_error_is_isolated(self):
        with patch.object(self.transport, "request", side_effect=json.JSONDecodeError("mixed log", "x", 0)):
            self.assertIn("logs unavailable", self.client.pod_logs("gpu", "discovery-1", "discovery"))


class AutohealModelRetryTests(unittest.TestCase):
    def model(self):
        return LLMClient({"base_url": "https://model.invalid/v1", "model": "test",
                          "max_attempts": 3, "retry_backoff_seconds": 0}, None)

    def test_malformed_response_has_three_total_attempts(self):
        model = self.model()
        with patch.object(model, "complete", return_value="not JSON") as call:
            with self.assertRaises(LLMUnavailable):
                model.diagnose({}, ["notify_only"])
        self.assertEqual(call.call_count, 3)

    def test_missing_required_fields_are_not_a_valid_diagnosis(self):
        model = self.model()
        with patch.object(model, "complete", return_value="{}") as call:
            with self.assertRaises(LLMUnavailable):
                model.diagnose({}, ["notify_only"])
        self.assertEqual(call.call_count, 3)

    def test_non_text_completion_is_normalized_and_retried(self):
        model = self.model()
        with patch.object(model, "complete", return_value={"private": "do-not-report"}) as call:
            with self.assertRaises(LLMUnavailable) as raised:
                model.diagnose({}, ["notify_only"])
        self.assertEqual(call.call_count, 3)
        self.assertNotIn("do-not-report", str(raised.exception))

    def test_authentication_failure_is_not_retried(self):
        model = self.model()
        error = urllib.error.HTTPError("https://model.invalid", 401, "denied", {}, io.BytesIO(b"private-provider-body"))
        with patch("urllib.request.urlopen", side_effect=error) as call:
            with self.assertRaisesRegex(LLMUnavailable, "HTTP 401") as raised:
                model.diagnose({}, ["notify_only"])
        self.assertEqual(call.call_count, 1)
        self.assertNotIn("private-provider-body", str(raised.exception))

    def test_transient_provider_failure_recovers(self):
        model = self.model()
        error = urllib.error.HTTPError("https://model.invalid", 503, "unavailable", {}, io.BytesIO(b""))
        content = {"root_cause": "unconfirmed", "confidence": 0.5, "action": None, "params": {}}
        response = json.dumps({"choices": [{"message": {"content": json.dumps(content)}, "finish_reason": "stop"}]}).encode()
        with patch("urllib.request.urlopen", side_effect=[error, io.BytesIO(response)]) as call:
            diagnosis = model.diagnose({}, ["notify_only"])
        self.assertEqual(call.call_count, 2)
        self.assertIsNone(diagnosis.action)

    def test_truncation_does_not_multiply_retry_budget(self):
        model = self.model()
        original_budget = model.max_tokens
        response = json.dumps({"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]}).encode()
        with patch("urllib.request.urlopen", side_effect=lambda *args, **kwargs: io.BytesIO(response)) as call:
            with self.assertRaises(LLMUnavailable):
                model.diagnose({}, ["notify_only"])
        self.assertEqual(call.call_count, 3)
        self.assertEqual(model.max_tokens, original_budget)


if __name__ == "__main__":
    unittest.main()
