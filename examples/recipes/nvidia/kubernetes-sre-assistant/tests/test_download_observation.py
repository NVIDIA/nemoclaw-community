# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Classify failed downloads before their Job TTL can erase auth evidence."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1] / "files/skills/openshift-llm-deploy"


class DownloadObservationTests(unittest.TestCase):
    def run_wrapper(self, mode="standard-vllm", invalid_manifest=False, download_outcome="auth", retained=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skill"
            shutil.copytree(SKILL, skill)
            scripts = skill / "scripts"
            (scripts / "resolve-dynamo-image.sh").write_text(
                "printf '%s\\n' DYNAMO_IMAGE=example/runtime:1 DYNAMO_RUNTIME_VERSION=1.4.1\n")
            (scripts / "resolve-vllm-image.sh").write_text("printf '%s\\n' VLLM_IMAGE=example/vllm:1\n")
            (scripts / "dynamo-first-deploy.sh").write_text("printf '%s\\n' DEPLOYMENT_RESULT=ready\n")
            (skill / "dynamo-defaults.yaml").write_text(
                "vllmRuntimeImage: example/runtime:1\nvllmRuntimeVersion: 1.4.1\n"
                "standardVllmImage: example/vllm:1\nobservationTimeoutSeconds: 30\n"
                "verificationTimeoutSeconds: 30\ndownloadObservationTimeoutSeconds: 300\n"
                "downloadTimeoutSeconds: 600\nimagePullSecretName: \"\"\n")
            (skill / "hf-token-intake.yaml").write_text(
                'namespace: "models"\nsecretName: "hf-token"\nsecretKey: "HF_TOKEN"\n'
                'modelRunnerServiceAccount: "model-runner"\nrequireTokenForHuggingFaceModels: false\n')
            oc = root / "oc"
            oc.write_text("""#!/bin/sh
case "$*" in
  *'get job/model-model-download --ignore-not-found=true'*)
    [ "$TEST_RETAINED" != true ] || printf '%s' job.batch/model-model-download ;;
  'get storageclass '*) printf '%s' csi.example ;;
  *'apply --dry-run=client'*)
    [ "$TEST_VALIDATION_FAILURE" != true ] || exit 1 ;;
  *'wait --for=condition=complete'*)
    # Waiting only for success outlives the failed Job's cleanup window.
    touch "$TEST_JOB_EXPIRED"; exit 1 ;;
  *'wait --for=jsonpath='*)
    if [ "$TEST_DOWNLOAD_OUTCOME" = success ]; then
      echo 'error: given jsonpath expression matches more than one value' >&2
      exit 1
    fi
    printf '%s' Failed ;;
  *'get job/model-model-download'*'status.conditions'*)
    [ ! -f "$TEST_JOB_EXPIRED" ] || exit 1
    if [ "$TEST_DOWNLOAD_OUTCOME" = success ]; then
      printf '%s' 'SuccessCriteriaMet Complete'
    else
      printf '%s' 'FailureTarget Failed'
    fi ;;
  *'logs job/model-model-download'*)
    [ ! -f "$TEST_JOB_EXPIRED" ] || exit 1
    [ "$TEST_DOWNLOAD_OUTCOME" != auth ] ||
      printf '%s\\n' MODEL_DOWNLOAD_REASON=huggingface-authentication-required ;;
  *'get job/model-model-download'*)
    [ ! -f "$TEST_JOB_EXPIRED" ] || exit 1
    [ "$TEST_DOWNLOAD_OUTCOME" = success ] || printf '%s' 1 ;;
esac
""")
            oc.chmod(0o755)
            env = os.environ.copy()
            env.update(PATH=str(root) + os.pathsep + env["PATH"],
                       OPENSHIFT_LLM_TARGET_NAMESPACE="models",
                       OPENSHIFT_LLM_RUNNER_SERVICE_ACCOUNT="model-runner",
                       TEST_VALIDATION_FAILURE=str(invalid_manifest).lower(),
                       TEST_DOWNLOAD_OUTCOME=download_outcome,
                       TEST_RETAINED=str(retained).lower(),
                       TEST_JOB_EXPIRED=str(root / "expired"))
            command = ["sh", str(scripts / "deploy-model.sh"), "--namespace", "models",
                       "--release", "model", "--model", "example/model", "--node", "gpu-node",
                       "--gpus", "1", "--storage-class", "csi", "--pvc-size", "20Gi",
                       "--memory-request", "8Gi", "--memory-limit", "16Gi",
                       "--hf-secret", "hf-token", "--platform", "kubernetes",
                       "--deployment-mode", mode]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
            return result.stdout

    def test_fast_auth_failure_is_reported_before_failed_job_expires(self):
        output = self.run_wrapper()
        self.assertIn("DEPLOYMENT_REASON=huggingface-authentication-required", output)
        self.assertIn("DEPLOYMENT_RESULT=failed", output)
        self.assertNotIn("DEPLOYMENT_RESULT=pending", output)

    def test_valid_dynamo_manifest_reaches_download_phase(self):
        output = self.run_wrapper(mode="dynamo")
        self.assertIn("DEPLOYMENT_PHASE=applying-isolated-model-download", output)
        self.assertIn("DEPLOYMENT_REASON=huggingface-authentication-required", output)

    def test_multiple_success_conditions_proceed_to_model_serving(self):
        output = self.run_wrapper(download_outcome="success")
        self.assertIn("MODEL_DOWNLOAD_RESULT=ready", output)
        self.assertIn("DEPLOYMENT_RESULT=ready", output)
        self.assertNotIn("DEPLOYMENT_RESULT=pending", output)

    def test_retained_failed_job_reports_cleanup_instead_of_stale_auth_failure(self):
        output = self.run_wrapper(retained=True)
        self.assertIn("DEPLOYMENT_REASON=model-download-retry-awaiting-cleanup", output)
        self.assertIn("DEPLOYMENT_RESULT=pending", output)
        self.assertNotIn("DEPLOYMENT_REASON=huggingface-authentication-required", output)
        self.assertNotIn("DEPLOYMENT_PHASE=applying-isolated-model-download", output)

    def test_invalid_manifests_stop_before_cluster_mutation(self):
        for mode in ("standard-vllm", "dynamo"):
            with self.subTest(mode=mode):
                output = self.run_wrapper(mode=mode, invalid_manifest=True)
                self.assertIn("DEPLOYMENT_REASON=chart-managed-manifest-validation-failed", output)
                self.assertNotIn("DEPLOYMENT_PHASE=applying-isolated-model-download", output)


if __name__ == "__main__":
    unittest.main()
