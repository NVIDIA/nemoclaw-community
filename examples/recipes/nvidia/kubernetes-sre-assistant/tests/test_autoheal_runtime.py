# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Credential rotation and finding-scoped cleanup without a live cluster."""

import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

AGENT_DIR = Path(__file__).resolve().parents[1] / "charts/sre-autoheal-agent/files/agent"
sys.path.insert(0, str(AGENT_DIR))
from sre_autoheal.actions import ActionExecutor
from sre_autoheal.kube import HttpTransport, KubeError
from sre_autoheal.models import Finding, Resource
from sre_autoheal.policy import Policy


class TokenRotationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.token_file = self.root / "token"
        self.token_file.write_text("<initial-token>\n", encoding="utf-8")
        self.headers = []

        def respond(request, **kwargs):
            self.headers.append(request.get_header("Authorization"))
            return io.BytesIO(b"{}")

        self.urlopen = mock.patch("sre_autoheal.kube.urllib.request.urlopen", side_effect=respond).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {
            "SRE_AUTOHEAL_KUBE_API": "https://kubernetes.example",
            "SRE_AUTOHEAL_KUBE_TOKEN_FILE": str(self.token_file),
        }, clear=True).start()
        mock.patch("sre_autoheal.kube.ssl.create_default_context").start()

    def test_file_token_is_reloaded_on_each_request(self):
        client = HttpTransport.from_environment()
        client.request("GET", "/version")
        self.token_file.write_text("<rotated-token>\n", encoding="utf-8")
        client.request("GET", "/version")
        self.assertEqual(self.headers, ["Bearer <initial-token>", "Bearer <rotated-token>"])

    def test_default_service_account_projection_follows_rotated_symlink(self):
        first = self.root / "first"
        second = self.root / "second"
        first.write_text("<first-token>", encoding="utf-8")
        second.write_text("<second-token>", encoding="utf-8")
        projected = self.root / "projected"
        projected.symlink_to(first)
        with mock.patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "kubernetes.example"}, clear=True), mock.patch(
            "sre_autoheal.kube.SA_TOKEN", str(projected)
        ):
            client = HttpTransport.from_environment()
            client.request("GET", "/version")
            replacement = self.root / "replacement"
            replacement.symlink_to(second)
            replacement.replace(projected)
            client.request("GET", "/version")
        self.assertEqual(self.headers, ["Bearer <first-token>", "Bearer <second-token>"])

    def test_missing_empty_or_unreadable_file_does_not_reuse_old_token(self):
        client = HttpTransport.from_environment()
        self.token_file.unlink()
        with self.assertRaisesRegex(KubeError, "cannot read"):
            client.request("GET", "/version")
        self.token_file.write_text(" \n", encoding="utf-8")
        with self.assertRaisesRegex(KubeError, "empty"):
            client.request("GET", "/version")
        with mock.patch("builtins.open", side_effect=PermissionError):
            with self.assertRaisesRegex(KubeError, "cannot read"):
                client.request("GET", "/version")
        self.urlopen.assert_not_called()
        self.token_file.write_text("<recovered-token>", encoding="utf-8")
        client.request("GET", "/version")
        self.assertEqual(self.headers, ["Bearer <recovered-token>"])

    def test_explicit_environment_token_takes_precedence_over_file(self):
        os.environ["SRE_AUTOHEAL_KUBE_TOKEN"] = "<explicit-token>"
        client = HttpTransport.from_environment()
        self.token_file.unlink()
        client.request("GET", "/version")
        self.assertEqual(self.headers, ["Bearer <explicit-token>"])

    def test_direct_static_token_client_remains_supported(self):
        client = HttpTransport("https://kubernetes.example", "<static-token>", None)
        client.request("GET", "/version")
        self.assertEqual(self.headers, ["Bearer <static-token>"])


class CleanupScopeTest(unittest.TestCase):
    @staticmethod
    def pod(name, phase="Failed", reason="Evicted", labels=None):
        return {"metadata": {"name": name, "namespace": "team-a", "labels": labels or {}},
                "status": {"phase": phase, "reason": reason}}

    def setUp(self):
        self.finding = Finding("pod-evicted", "low", Resource("Pod", "affected", "team-a"),
                               "evicted", owner=Resource("Deployment", "workload", "team-a"),
                               related_pods=["affected", "related", "recovered"])
        self.client = mock.Mock()
        self.client.list.return_value = [
            self.pod("affected"), self.pod("related", reason="Terminated"),
            self.pod("recovered", phase="Running", reason=""),
            self.pod("unrelated"), self.pod("opted-out", labels={"autoheal": "disabled"}),
        ]

    def test_cleanup_never_expands_approved_finding_to_other_workloads(self):
        policy = Policy({"mode": "safe"}, {"opt_out_label": "autoheal=disabled"})
        self.assertTrue(policy.decide(self.finding, "delete_evicted_pods", {}, {}, {}).allowed)
        self.assertFalse(policy.decide(self.finding, "delete_evicted_pods", {"autoheal": "disabled"}, {}, {}).allowed)
        result = ActionExecutor(self.client).execute("delete_evicted_pods", self.finding, {"pod": "unrelated"})
        self.assertTrue(result.ok)
        self.assertEqual(result.changed, ["affected", "related"])
        self.assertEqual([call.args[0].name for call in self.client.delete.call_args_list], ["affected", "related"])

    def test_cleanup_includes_the_finding_pod_without_related_pods(self):
        self.finding.related_pods = []
        result = ActionExecutor(self.client).execute("delete_evicted_pods", self.finding, {})
        self.assertEqual(result.changed, ["affected"])
        self.assertEqual(self.client.delete.call_count, 1)

    def test_cleanup_dry_run_has_the_same_scope_and_performs_no_deletes(self):
        result = ActionExecutor(self.client, dry_run=True).execute("delete_evicted_pods", self.finding, {})
        self.assertEqual(result.changed, ["affected", "related"])
        self.assertTrue(result.dry_run)
        self.client.delete.assert_not_called()

    def test_cleanup_without_finding_pods_does_not_scan_the_namespace(self):
        finding = Finding("pod-evicted", "low", Resource("Deployment", "workload", "team-a"), "evicted")
        result = ActionExecutor(self.client).execute("delete_evicted_pods", finding, {})
        self.assertTrue(result.ok)
        self.client.list.assert_not_called()
        self.client.delete.assert_not_called()

    def test_cleanup_ignores_recovered_or_missing_pods(self):
        self.client.list.return_value = [self.pod("affected", phase="Running", reason="")]
        result = ActionExecutor(self.client).execute("delete_evicted_pods", self.finding, {})
        self.assertTrue(result.ok)
        self.client.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
