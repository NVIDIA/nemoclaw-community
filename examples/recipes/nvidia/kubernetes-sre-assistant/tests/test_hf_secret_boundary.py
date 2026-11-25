# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""The sandbox may check one HF Secret's existence, never its contents."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from email.message import Message
from urllib.error import HTTPError
import urllib.request
from urllib.response import addinfourl

SOURCE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hf_boundary_proxy", SOURCE / "files/scripts/api_proxy.py")
proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proxy)
TARGET = "/api/v1/namespaces/models/secrets/model-hf"
ENV = {"PROXY_POLICY": "general", "PROXY_ALLOWED_METHODS": "GET,PATCH",
       "PROXY_HF_SECRET_NAMESPACE": "models", "PROXY_HF_SECRET_NAME": "model-hf"}


class Handler(proxy.ProxyHandler):
    def __init__(self, target=TARGET, method="GET", body=b""):
        self.path, self.command = target, method
        self.headers = {"Authorization": "Bearer test-proxy-token", "Accept": "application/json"}
        if body:
            self.headers["Content-Length"] = str(len(body))
        self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
        self.status, self.sent_headers = None, {}

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.sent_headers[name] = value

    def end_headers(self):
        pass


class Upstream(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}


class HfSecretBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, ENV, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def invoke(self, handler, upstream):
        with mock.patch.object(proxy, "is_authorized", return_value=True), \
             mock.patch.object(proxy, "read_bounded", return_value="test-api-token"), \
             mock.patch.object(proxy.ssl, "create_default_context"), \
             mock.patch.object(proxy, "build_opener") as builder:
            request = builder.return_value.open
            request.return_value = upstream
            handler.proxy()
        return request

    def test_exact_reference_returns_only_constructed_metadata_without_reading_body(self):
        upstream = Upstream(json.dumps({"data": {"HF_TOKEN": "sensitive"},
                                       "metadata": {"annotations": {"sensitive": "value"}}}).encode())
        handler = Handler()
        with mock.patch.object(upstream, "read", side_effect=AssertionError("Secret body must not be read")):
            request = self.invoke(handler, upstream)
        self.assertEqual(handler.status, 200)
        self.assertEqual(json.loads(handler.wfile.getvalue()), {
            "apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": "model-hf", "namespace": "models"}})
        self.assertIn("as=PartialObjectMetadata", request.call_args.args[0].get_header("Accept"))
        self.assertEqual(handler.sent_headers["Cache-Control"], "no-store")

    def test_sensitive_paths_methods_queries_and_encodings_are_denied(self):
        denied = [
            TARGET + "?watch=true", TARGET + "?resourceVersion=0", TARGET + "?",
            TARGET + "/status", TARGET + "/", TARGET.replace("model-hf", "other"),
            TARGET.replace("models", "other"), TARGET.rsplit("/", 1)[0],
            TARGET.replace("/v1/", "/v1/watch/"), TARGET.replace("model-hf", "%6dodel-hf"),
            TARGET.replace("/v1/", "/v2/"), TARGET.replace("/secrets/", "//secrets/"),
        ]
        for target in denied:
            with self.subTest(target=target):
                handler = Handler(target)
                request = self.invoke(handler, Upstream(b""))
                self.assertEqual(handler.status, 403)
                request.assert_not_called()
        for method in ("PATCH", "POST", "PUT", "DELETE", "HEAD"):
            with self.subTest(method=method):
                self.assertFalse(proxy.request_allowed(TARGET, method, "general"))

    def test_disabled_feature_keeps_all_secret_reads_forbidden(self):
        for name in ("PROXY_HF_SECRET_NAMESPACE", "PROXY_HF_SECRET_NAME"):
            with self.subTest(name=name), mock.patch.dict(os.environ, {name: ""}):
                self.assertFalse(proxy.request_allowed(TARGET, "GET", "general"))

    def test_non_general_proxy_cannot_gain_secret_access(self):
        for policy in ("exact-delete", "exact-service-proxy", "unknown"):
            self.assertFalse(proxy.request_allowed(TARGET, "GET", policy))

    def test_upstream_failures_never_forward_secret_or_error_body(self):
        for status in (403, 404, 406, 500):
            with self.subTest(status=status):
                upstream = HTTPError("https://kubernetes.default.svc" + TARGET, status,
                                     "sensitive upstream message", {}, io.BytesIO(b"sensitive"))
                handler = Handler()
                with mock.patch.object(proxy, "is_authorized", return_value=True), \
                     mock.patch.object(proxy, "read_bounded", return_value="test-api-token"), \
                     mock.patch.object(proxy.ssl, "create_default_context"), \
                     mock.patch.object(proxy, "build_opener") as builder, \
                     mock.patch.object(upstream, "read", side_effect=AssertionError("error body must not be read")):
                    builder.return_value.open.side_effect = upstream
                    handler.proxy()
                self.assertEqual(handler.status, status if status in (403, 404) else 502)
                self.assertNotIn(b"sensitive", handler.wfile.getvalue())

    def test_secret_check_rejects_request_body(self):
        handler = Handler(body=b"unexpected")
        request = self.invoke(handler, Upstream(b""))
        self.assertEqual(handler.status, 400)
        request.assert_not_called()

    def test_redirects_are_not_followed_and_their_bodies_are_not_read(self):
        real_build_opener = urllib.request.build_opener
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                requested, reads = [], []

                class Body(io.BytesIO):
                    def read(self, *args):
                        reads.append(True)
                        return super().read(*args)

                class Transport(urllib.request.BaseHandler):
                    handler_order = 100

                    def https_open(self, request):
                        requested.append(request.full_url)
                        headers = Message()
                        headers["Location"] = "https://kubernetes.default.svc/api/v1/namespaces/other/secrets/private"
                        code = status if len(requested) == 1 else 200
                        response = addinfourl(Body(b"sensitive upstream body"), headers, request.full_url, code)
                        response.msg = "test response"
                        return response

                def opener(*handlers):
                    return real_build_opener(Transport(), *handlers)

                handler = Handler()
                with mock.patch.object(proxy, "is_authorized", return_value=True), \
                     mock.patch.object(proxy, "read_bounded", return_value="test-api-token"), \
                     mock.patch.object(proxy.ssl, "create_default_context"), \
                     mock.patch.object(urllib.request, "build_opener", side_effect=opener), \
                     mock.patch.object(proxy, "build_opener", create=True, side_effect=opener):
                    handler.proxy()
                self.assertEqual(handler.status, 502)
                self.assertEqual(requested, [proxy.UPSTREAM + TARGET])
                self.assertEqual(reads, [])
                self.assertNotIn(b"sensitive", handler.wfile.getvalue())

    def test_unauthenticated_check_never_reaches_upstream(self):
        handler = Handler()
        with mock.patch.object(proxy, "is_authorized", return_value=False), \
             mock.patch.object(proxy, "build_opener") as request:
            handler.proxy()
        self.assertEqual(handler.status, 401)
        request.assert_not_called()


class HfReferenceTests(unittest.TestCase):
    def test_deploy_wrapper_uses_intake_reference_without_unset_hf_environment(self):
        skill = SOURCE / "files/skills/openshift-llm-deploy"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copyfile(skill / "scripts/deploy-model.sh", scripts / "deploy-model.sh")
            for name in ("render-template.py", "dynamo-first-deploy.sh", "diagnose-deployment.sh"):
                (scripts / name).write_text("")
            (scripts / "resolve-dynamo-image.sh").write_text(
                "printf '%s\\n' DYNAMO_IMAGE=example/runtime:1 DYNAMO_RUNTIME_VERSION=1.4.1\n")
            (scripts / "resolve-vllm-image.sh").write_text("printf '%s\\n' VLLM_IMAGE=example/vllm:1\n")
            (root / "dynamo-defaults.yaml").write_text(
                "vllmRuntimeImage: example/runtime:1\nvllmRuntimeVersion: 1.4.1\n"
                "standardVllmImage: example/vllm:1\nobservationTimeoutSeconds: 30\n"
                "verificationTimeoutSeconds: 30\ndownloadObservationTimeoutSeconds: 30\n"
                "downloadTimeoutSeconds: 60\nimagePullSecretName: \"\"\n")
            (root / "hf-token-intake.yaml").write_text(
                'namespace: "models"\nsecretName: "model-hf"\nsecretKey: "download-token"\n'
                'modelRunnerServiceAccount: "model-runner"\n')
            oc = root / "oc"
            oc.write_text("#!/bin/sh\ncase \"$*\" in\n"
                          "  'get storageclass '*) printf '%s' csi.example ;;\n"
                          "  *serviceaccount*) exit 1 ;;\n"
                          "esac\n")
            oc.chmod(0o755)
            env = os.environ.copy()
            env.update(PATH=str(root) + os.pathsep + env["PATH"],
                       OPENSHIFT_LLM_TARGET_NAMESPACE="models",
                       OPENSHIFT_LLM_RUNNER_SERVICE_ACCOUNT="model-runner")
            env.pop("OPENSHIFT_LLM_HF_SECRET_NAME", None)
            env.pop("OPENSHIFT_LLM_HF_SECRET_KEY", None)
            command = ["sh", str(scripts / "deploy-model.sh"), "--namespace", "models",
                       "--release", "model", "--model", "example/model", "--node", "gpu-node",
                       "--gpus", "1", "--storage-class", "csi", "--pvc-size", "20Gi",
                       "--memory-request", "8Gi", "--memory-limit", "16Gi",
                       "--hf-secret", "model-hf", "--platform", "kubernetes"]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertIn("DEPLOYMENT_REASON=model-runner-unavailable", result.stdout)
            command[command.index("--hf-secret") + 1] = "other-secret"
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertIn("DEPLOYMENT_REASON=unexpected-hf-token-secret", result.stdout)


if __name__ == "__main__":
    unittest.main()
