# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Public downloads must work anonymously; authentication failures stay redacted."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

import yaml

CHART = Path(__file__).resolve().parents[1]
SKILL = CHART / "files/skills/openshift-llm-deploy"


class OptionalHfTests(unittest.TestCase):
    def download(self, token=None, error=None):
        source = (SKILL / "templates/model-download-job.yaml").read_text()
        code = textwrap.dedent(source.split("            - |\n", 1)[1].split("\n          env:", 1)[0])
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model"
            calls = []

            def snapshot(**kwargs):
                calls.append(kwargs)
                if error:
                    raise error
                model.mkdir()
                (model / "config.json").write_text("{}")

            environment = {"MODEL_ID": "public/model"}
            if token is not None:
                environment["HF_TOKEN"] = token
            output = io.StringIO()
            with mock.patch.dict(sys.modules, {"huggingface_hub": types.SimpleNamespace(snapshot_download=snapshot)}), \
                 mock.patch.dict(os.environ, environment, clear=True), \
                 mock.patch("pathlib.Path", return_value=model), contextlib.redirect_stdout(output):
                status = 0
                try:
                    exec(code, {})
                except SystemExit as exc:
                    status = exc.code
                except Exception:
                    status = "unhandled"
                self.assertNotIn("HF_TOKEN", os.environ)
            return calls, status, output.getvalue()

    def test_public_model_download_disables_implicit_auth_when_no_token(self):
        calls, status, output = self.download()
        self.assertEqual(status, 0)
        self.assertIs(calls[0]["token"], False)
        self.assertIn("MODEL_DOWNLOAD_RESULT=ready", output)

    def test_configured_token_is_used_only_for_download(self):
        calls, status, _ = self.download(token="test-sensitive-value")
        self.assertEqual(status, 0)
        self.assertEqual(calls[0]["token"], "test-sensitive-value")

    def test_access_denial_requests_secret_reference_without_leaking_exception(self):
        for status in (401, 403):
            with self.subTest(status=status):
                error = RuntimeError("test-sensitive-value https://private.example/signed-url")
                error.response = types.SimpleNamespace(status_code=status)
                _, result, output = self.download(error=error)
                self.assertEqual(result, 1)
                self.assertIn("MODEL_DOWNLOAD_REASON=huggingface-authentication-required", output)
                self.assertIn("Kubernetes Secret", output)
                self.assertNotIn("test-sensitive-value", output)
                self.assertNotIn("private.example", output)

    def test_network_failure_does_not_claim_token_is_required(self):
        _, status, output = self.download(error=TimeoutError("test-sensitive-value"))
        self.assertEqual(status, 1)
        self.assertIn("MODEL_DOWNLOAD_REASON=model-download-failed", output)
        self.assertNotIn("huggingface-authentication-required", output)
        self.assertNotIn("test-sensitive-value", output)

    def test_download_manifest_secret_reference_is_optional(self):
        template = (SKILL / "templates/model-download-job.yaml").read_text()
        self.assertIn("optional: ${HF_SECRET_OPTIONAL}", template)

    def test_default_chart_token_is_optional(self):
        values = yaml.safe_load((CHART / "values.yaml").read_text())
        self.assertTrue(values["global"]["sre"]["openshiftLlmDeploy"]["hfTokenSecretRef"]["optional"])

    def test_optional_preflight_continues_past_missing_secret(self):
        module = runpy.run_path(str(SKILL / "scripts/preflight-model.py"))
        configuration = [
            {"standardVllmImage": "image@sha256:" + "c" * 64},
            {"secretName": "hf-token", "modelRunnerServiceAccount": "model-runner",
             "requireTokenForHuggingFaceModels": False}, {"targetNamespace": "models"},
        ]
        runtime = {key: "verified" for key in (
            "VLLM_RECIPE_URL", "VLLM_IMAGE", "VLLM_IMAGE_SOURCE", "VLLM_HARDWARE_RECIPE_URL",
            "VLLM_HARDWARE_RECIPE_SHA256", "VLLM_HARDWARE_PROFILE", "VLLM_PROFILE_IDENTITY",
            "VLLM_ARGS_SHA256", "VLLM_ENV_SHA256")}
        results = [{}, {},
                   {"HF_MODEL_REVISION": "a" * 40, "HF_MODEL_SOURCE_BYTES": "1000",
                    "HF_MODEL_RECOMMENDED_PVC_SIZE": "10Gi"},
                   {"VLLM_RECIPE_URL": "https://recipes.vllm.ai/example/model.json", "VLLM_RECIPE_SHA256": "b" * 64},
                   {"HF_GPU_RECIPE_SHA256": "b" * 64, "HF_GPU_SELECTED_PRODUCT": "NVIDIA-B200",
                    "HF_GPU_COUNT": "1", "HF_GPU_SELECTED_NODE": "node"}, runtime]
        runner = mock.Mock(side_effect=results)
        with mock.patch.object(module["sys"], "argv", ["preflight", "--model", "example/model",
                "--namespace", "models", "--storage-class", "local-path"]), \
             mock.patch.object(module["Path"], "read_text", return_value="configuration"), \
             mock.patch.object(module["yaml"], "safe_load", side_effect=configuration), \
             mock.patch.dict(module["main"].__globals__, {"run_stage": runner}), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module["main"](), 0)
        secret_check = runner.call_args_list[1].args[0]
        self.assertIn("--ignore-not-found=true", secret_check)
        self.assertEqual(secret_check[4:6], ["secret", "hf-token"])

    def test_restricted_metadata_reports_access_guidance_before_deploy(self):
        module = runpy.run_path(str(SKILL / "scripts/preflight-model.py"))
        configuration = [{}, {"namespace": "models", "secretName": "hf-token",
            "modelRunnerServiceAccount": "model-runner", "requireTokenForHuggingFaceModels": False}]
        runner = mock.Mock(side_effect=[{}, {}, {"HF_MODEL_STORAGE_ACTION": "blocked",
                                                "HF_MODEL_STORAGE_REASON": "restricted-metadata"}])
        output = io.StringIO()
        with mock.patch.object(module["sys"], "argv", ["preflight", "--model", "example/model",
                "--namespace", "models", "--storage-class", "local-path"]), \
             mock.patch.object(module["Path"], "read_text", return_value="configuration"), \
             mock.patch.object(module["yaml"], "safe_load", side_effect=configuration), \
             mock.patch.dict(module["main"].__globals__, {"run_stage": runner}), \
             contextlib.redirect_stdout(output):
            self.assertEqual(module["main"](), 1)
        self.assertIn("HF_PREFLIGHT_REASON=huggingface-authentication-required", output.getvalue())
        self.assertIn("Kubernetes Secret", output.getvalue())
        self.assertEqual(runner.call_count, 3)


if __name__ == "__main__":
    unittest.main()
