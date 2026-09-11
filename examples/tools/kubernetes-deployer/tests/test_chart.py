# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render-level safety checks for the kubernetes-deployer chart."""

from pathlib import Path
import base64
import hashlib
import importlib.util
import io
import json
import lzma
import os
import re
import shlex
import stat
import subprocess
import tarfile
import tempfile
import time
import unittest
from unittest import mock


CHART_DIR = Path(__file__).resolve().parents[1]
# Every image the chart renders must come from one of these public registries.
# An allow-list catches a private or internal registry without having to name
# one, so nothing about internal infrastructure appears in this public file.
ALLOWED_IMAGE_REGISTRIES = ("docker.io/", "ghcr.io/", "nvcr.io/", "quay.io/")
IMAGE_LINE = re.compile(r"(?m)^\s*(?:-\s*)?image:\s*[\"']?([^\"'\s]+)")


class ChartTest(unittest.TestCase):
    """Exercise the chart through Helm's public command-line interface."""

    @staticmethod
    def helm_arguments(*arguments: str) -> list[str]:
        """Render against the supported Agent Sandbox API during offline tests."""
        resolved = list(arguments)
        if arguments and arguments[0] == "template":
            resolved.extend(["--api-versions", "agents.x-k8s.io/v1alpha1"])
        if any(argument.endswith("values-openshift.yaml") for argument in arguments) and not any(
            "openshell.server.openshift.gatewayUid.value" in argument for argument in arguments
        ):
            resolved.extend(
                ["--set", "openshell.server.openshift.gatewayUid.value=1001200001"]
            )
        if any(argument.endswith("values-openshift.yaml") for argument in arguments) and not any(
            "openshell.server.openshift.sandboxUid.value" in argument for argument in arguments
        ):
            resolved.extend(
                ["--set", "openshell.server.openshift.sandboxUid.value=1001200002"]
            )
        # The managed gateway requires an explicit issuer-discovery decision
        # (see test_default_render_requires_an_issuer_discovery_decision). Tests
        # that make no decision get the option that renders no extra resources.
        profile_files = ("values-openshift.yaml", "values-kubernetes.yaml", "values-existing-gateway.yaml")
        if arguments and arguments[0] in {"template", "lint"} and not any(
            "serviceAccountIssuerDiscovery" in argument or argument.endswith(profile_files)
            for argument in arguments
        ):
            resolved.extend(
                ["--set", "platform.serviceAccountIssuerDiscovery.preexistingAnonymousAccess=true"]
            )
        return resolved

    def run_helm(self, *arguments: str) -> str:
        resolved = self.helm_arguments(*arguments)
        completed = subprocess.run(
            ["helm", *resolved],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=(
                f"helm {' '.join(arguments)} failed\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            ),
        )
        return completed.stdout

    def assert_helm_rejected(
        self,
        command: str,
        *arguments: str,
        expected: str,
    ) -> None:
        resolved = self.helm_arguments(command, *arguments)
        completed = subprocess.run(
            ["helm", *resolved],
            check=False,
            capture_output=True,
            text=True,
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(
            completed.returncode,
            0,
            msg=f"helm {command} unexpectedly accepted invalid values:\n{output}",
        )
        self.assertIn(
            expected,
            output,
            msg=(
                f"helm {command} failed for the wrong reason\n"
                f"expected fragment: {expected}\noutput:\n{output}"
            ),
        )

    @staticmethod
    def rendered_from_source(rendered: str, source: str) -> str:
        """Return only rendered documents emitted by one chart template."""
        documents = rendered.split("\n---\n")
        selected = [document for document in documents if f"# Source: {source}" in document]
        if not selected:
            raise AssertionError(f"no rendered documents found for {source}")
        return "\n---\n".join(selected)

    @staticmethod
    def bootstrap_config(rendered: str) -> dict[str, object]:
        """Extract the rendered bootstrap JSON from the runtime ConfigMap."""
        runtime = ChartTest.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/runtime-configmap.yaml",
        )
        lines = runtime.splitlines()
        try:
            start = lines.index("  bootstrap-config.json: |") + 1
        except ValueError as error:
            raise AssertionError("bootstrap-config.json was not found in the rendered ConfigMap")
        body_lines: list[str] = []
        for line in lines[start:]:
            if not line.startswith("    "):
                break
            body_lines.append(line[4:])
        body = "\n".join(body_lines)
        return json.loads(body)

    def test_chart_lints(self) -> None:
        self.assertTrue(CHART_DIR.joinpath("Chart.yaml").is_file())
        self.run_helm("lint", str(CHART_DIR))

    def test_vendored_openshell_dependency_is_self_contained(self) -> None:
        chart_yaml = CHART_DIR.joinpath("Chart.yaml").read_text(encoding="utf-8")
        self.assertTrue(CHART_DIR.joinpath("charts", "helm-chart", "Chart.yaml").is_file())
        self.assertNotIn("repository: oci://ghcr.io/nvidia/openshell", chart_yaml)
        self.assertFalse(CHART_DIR.joinpath("Chart.lock").exists())
        self.assertEqual(list(CHART_DIR.joinpath("charts").glob("*.tgz")), [])

    def test_default_render_excludes_disallowed_resources(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        rendered_lower = rendered.lower()

        self.assertNotIn("webui", rendered_lower)
        self.assertNotIn("cluster-admin", rendered_lower)
        images = IMAGE_LINE.findall(rendered)
        self.assertTrue(images, "expected at least one image reference in the render")
        for image in images:
            self.assertTrue(
                image.startswith(ALLOWED_IMAGE_REGISTRIES),
                msg=f"image {image!r} is not from an allowed public registry",
            )
        self.assertIsNone(
            re.search(r"(?m)^kind:\s*Sandbox\s*$", rendered),
            msg="the umbrella chart must not render a Sandbox resource directly",
        )

    def test_values_reject_unsupported_topology(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set-string",
            "openshell.supervisor.topology=sidecar",
            expected="/openshell/supervisor/topology",
        )

    def test_values_reject_mixed_gateway_modes(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set-string",
            "openshell.mode=existing",
            "--set",
            "openshell.enabled=true",
            expected="openshell.enabled",
        )

    def test_values_require_model_secret_reference(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set-string",
            "agent.model.apiKeySecretRef.name=",
            expected="/agent/model/apiKeySecretRef/name",
        )

    def test_plaintext_model_endpoint_requires_explicit_acknowledgement(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set-string",
            "agent.model.baseUrl=http://model.internal.example/v1",
            expected="agent.model.allowInsecureHttp",
        )

        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set-string",
            "agent.model.baseUrl=http://model.internal.example/v1",
            "--set",
            "agent.model.allowInsecureHttp=true",
            "--set-string",
            "agent.model.insecureHttpAcknowledgement=I_ACKNOWLEDGE_PLAINTEXT_MODEL_CREDENTIALS",
        )
        self.assertIn("http://model.internal.example/v1", rendered)

    def test_values_reject_mutable_runtime_images(self) -> None:
        mutable_overrides = (
            "agent.image.multiarch=ghcr.io/nvidia/nemoclaw/hermes-sandbox:latest",
            "artifacts.utilityImage=docker.io/library/python:3.13",
            "openshell.image.tag=0.0.116",
            "openshell.supervisor.image.tag=0.0.116",
        )
        for override in mutable_overrides:
            with self.subTest(override=override):
                key = override.split("=", 1)[0]
                self.assert_helm_rejected(
                    "template",
                    "kubernetes-deployer-test",
                    str(CHART_DIR),
                    "--set-string",
                    override,
                    expected="/" + key.replace(".", "/"),
                )

    def test_default_runtime_images_use_multiarch_index_digests(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        self.assertIn(
            "ghcr.io/nvidia/openshell/gateway:0.0.116@sha256:05cf77bbb022a739aed6f22daa0e7e164415f4ab273b5f84319e46d91eb8f645",
            rendered,
        )
        self.assertIn(
            "ghcr.io/nvidia/openshell/supervisor:0.0.116@sha256:c8c42aef16c200063e32cbf72e553e4ead027085427b555efafd95063ecead42",
            rendered,
        )

    def test_values_require_scc_binding_acknowledgement(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "platform.openshift.enabled=true",
            "--set",
            "platform.openshift.createPrivilegedSccBinding=true",
            expected="platform.openshift.dangerousAcknowledgement",
        )

    def test_public_service_account_issuer_discovery_requires_acknowledgement(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "platform.serviceAccountIssuerDiscovery.createPublicBinding=true",
            expected="I_ACKNOWLEDGE_PUBLIC_OIDC_DISCOVERY",
        )

    def test_acknowledged_issuer_discovery_binding_is_narrow(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "platform.serviceAccountIssuerDiscovery.createPublicBinding=true",
            "--set-string",
            "platform.serviceAccountIssuerDiscovery.dangerousAcknowledgement=I_ACKNOWLEDGE_PUBLIC_OIDC_DISCOVERY",
        )
        binding = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/serviceaccount-issuer-discovery.yaml",
        )

        self.assertIn("name: system:service-account-issuer-discovery", binding)
        self.assertRegex(
            binding,
            r"(?s)kind: Group\s+apiGroup: rbac.authorization.k8s.io\s+name: system:unauthenticated",
        )
        self.assertNotIn("cluster-admin", binding)

    def test_kubernetes_is_the_default_platform(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )

        self.assertNotIn("system:openshift:scc:", rendered)
        self.assertNotIn("security.openshift.io/", rendered)
        self.assertNotIn("openshift.io/required-scc", rendered)
        self.assertIn("runAsUser: 1000", rendered)
        self.assertIn("fsGroup: 1000", rendered)
        self.assertNotIn("PORTABLE_UID_MODE", rendered)

    def test_kubernetes_can_explicitly_enable_user_namespaces(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "openshell.server.enableUserNamespaces=true",
        )
        gateway = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/charts/openshell/templates/gateway-config.yaml",
        )
        self.assertIn("enable_user_namespaces = true", gateway)

    def test_managed_gateway_database_pvc_uses_configured_storage_class(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set-string",
            "persistence.storageClass=portable-rwo",
        )
        gateway_pvc = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/gateway-pvc.yaml",
        )

        self.assertIn(
            "name: openshell-data-kubernetes-deployer-test-openshell-0",
            gateway_pvc,
        )
        self.assertIn('storageClassName: "portable-rwo"', gateway_pvc)
        self.assertIn("storage: 1Gi", gateway_pvc)

    def test_openshift_requires_scc_compatible_gateway_context(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "platform.openshift.enabled=true",
            "--set",
            "openshell.server.openshift.gatewayUid.enabled=true",
            "--set",
            "openshell.server.openshift.gatewayUid.value=1001200001",
            "--api-versions",
            "security.openshift.io/v1",
            expected="openshell.podSecurityContext.fsGroup",
        )

    def test_openshift_profile_renders_only_acknowledged_scc_binding(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--api-versions",
            "security.openshift.io/v1",
            "--api-versions",
            "route.openshift.io/v1",
            "--values",
            str(CHART_DIR / "values-openshift.yaml"),
        )

        self.assertIn("system:openshift:scc:privileged", rendered)
        self.assertNotIn("runAsUser: 1000", rendered)
        self.assertNotIn("fsGroup: 1000", rendered)
        self.assertNotIn("PORTABLE_UID_MODE", rendered)
        self.assertNotIn("enable_user_namespaces = true", rendered)

    def test_openshift_profile_isolates_gateway_uid_from_sandbox_uid(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--api-versions",
            "security.openshift.io/v1",
            "--values",
            str(CHART_DIR / "values-openshift.yaml"),
            "--set",
            "openshell.server.openshift.gatewayUid.value=1001200001",
            "--set",
            "openshell.server.openshift.sandboxUid.value=1001200002",
        )
        gateway = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/charts/openshell/templates/statefulset.yaml",
        )
        gateway_config = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/charts/openshell/templates/gateway-config.yaml",
        )
        seed = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/seed-job.yaml",
        )
        config = self.bootstrap_config(rendered)

        self.assertIn("runAsUser: 1001200001", gateway)
        self.assertNotIn("runAsUser: 1001200000", gateway)
        self.assertIn("sandbox_uid                  = 1001200002", gateway_config)
        self.assertIn("sandbox_gid                  = 1001200002", gateway_config)
        self.assertNotIn("sandbox_uid", config["driverConfig"]["kubernetes"])
        self.assertNotIn("sandbox_gid", config["driverConfig"]["kubernetes"])
        self.assertIn("runAsUser: 1001200002", seed)
        self.assertIn("runAsGroup: 1001200002", seed)
        self.assertNotIn("fsGroup: 1001200002", seed)

    def test_openshift_gateway_uid_lookup_requires_precreated_namespace(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--api-versions",
            "security.openshift.io/v1",
            "--values",
            str(CHART_DIR / "values-openshift.yaml"),
            "--set-json",
            "openshell.server.openshift.gatewayUid.value=null",
            expected="requires the release namespace",
        )

    def test_kubernetes_rejects_openshift_gateway_uid_resolution(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "openshell.server.openshift.gatewayUid.enabled=true",
            "--set",
            "openshell.server.openshift.gatewayUid.value=1001",
            expected="requires platform.openshift.enabled=true",
        )

    def test_openshift_rejects_user_namespaces_with_chart_persistence(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--values",
            str(CHART_DIR / "values-openshift.yaml"),
            "--set",
            "openshell.server.enableUserNamespaces=true",
            "--api-versions",
            "security.openshift.io/v1",
            expected="enableUserNamespaces=false",
        )

    def test_openshift_lifecycle_jobs_require_restricted_scc(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--api-versions",
            "security.openshift.io/v1",
            "--values",
            str(CHART_DIR / "values-openshift.yaml"),
        )
        for source in (
            "kubernetes-deployer/templates/seed-job.yaml",
            "kubernetes-deployer/templates/bootstrap-job.yaml",
        ):
            with self.subTest(source=source):
                job = self.rendered_from_source(rendered, source)
                self.assertIn("openshift.io/required-scc: restricted-v2", job)
                self.assertIn(
                    "serviceAccountName: kubernetes-deployer-test-lifecycle",
                    job,
                )

    def test_install_seed_binds_wait_for_first_consumer_storage_before_bootstrap(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        bootstrap = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/bootstrap-job.yaml",
        )

        self.assertIn("- key: stage_cli.py\n                path: stage_cli.py", bootstrap)
        self.assertIn("- key: wait_seed.py\n                path: wait_seed.py", bootstrap)
        self.assertIn("helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded", bootstrap)
        self.assertIn("name: wait-for-state-seed", bootstrap)
        self.assertIn("persistentVolumeClaim:", bootstrap)
        self.assertIn("mountPath: /state", bootstrap)
        main_container = bootstrap.split("\n      containers:\n", maxsplit=1)[1]
        self.assertNotIn("mountPath: /state", main_container)

        seed = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/seed-job.yaml",
        )
        self.assertIn("name: kubernetes-deployer-test-seed-1", seed)
        self.assertNotIn("helm.sh/hook:", seed)
        self.assertIn("restartPolicy: Never", seed)
        self.assertIn('name: RELEASE_REVISION\n              value: "1"', seed)

    def test_normal_upgrade_does_not_remount_live_sandbox_pvc(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--is-upgrade",
        )
        self.assertNotIn(
            "kubernetes-deployer/templates/seed-job.yaml",
            rendered,
        )
        bootstrap = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/bootstrap-job.yaml",
        )
        self.assertNotIn("name: wait-for-state-seed", bootstrap)
        self.assertNotIn("mountPath: /state", bootstrap)

    def test_seed_job_name_preserves_revision_with_maximal_fullname(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set-string",
            f"fullnameOverride={'a' * 63}",
        )
        seed = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/seed-job.yaml",
        )
        name_line = next(
            line.strip() for line in seed.splitlines() if line.strip().startswith("name: ")
        )
        seed_name = name_line.removeprefix("name: ")
        self.assertLessEqual(len(seed_name), 63)
        self.assertTrue(seed_name.endswith("-seed-1"))

    def test_upgrade_reseed_requires_stopped_sandbox_acknowledgement(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--is-upgrade",
            "--set",
            "lifecycle.seed.runOnUpgrade=true",
            expected="I_ACKNOWLEDGE_SANDBOX_STOPPED",
        )

        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--is-upgrade",
            "--set",
            "lifecycle.seed.runOnUpgrade=true",
            "--set-string",
            "lifecycle.seed.dangerousAcknowledgement=I_ACKNOWLEDGE_SANDBOX_STOPPED",
        )
        self.assertIn("kubernetes-deployer/templates/seed-job.yaml", rendered)
        bootstrap = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/bootstrap-job.yaml",
        )
        self.assertIn("name: wait-for-state-seed", bootstrap)
        self.assertIn("mountPath: /state", bootstrap)

    def test_managed_bootstrap_uses_projected_service_account_oidc(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        bootstrap = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/bootstrap-job.yaml",
        )
        gateway = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/charts/openshell/templates/gateway-config.yaml",
        )

        self.assertIn("automountServiceAccountToken: false", bootstrap)
        self.assertIn("name: kubernetes-api-token", bootstrap)
        self.assertIn("expirationSeconds: 900", bootstrap)
        self.assertIn("path: token", bootstrap)
        self.assertIn("mountPath: /var/run/secrets/openshell-token-request", bootstrap)
        self.assertIn("mountPath: /client-tls", bootstrap)
        self.assertNotIn("mountPath: /cli-config/openshell/gateways/", bootstrap)
        self.assertIn('issuer        = "https://kubernetes.default.svc"', gateway)
        self.assertIn('audience      = "openshell-cli"', gateway)
        self.assertIn('roles_claim   = "aud"', gateway)
        self.assertIn('admin_role    = "openshell-admin"', gateway)
        self.assertIn('user_role     = "openshell-cli"', gateway)
        self.assertNotIn("allow_unauthenticated_users = true", gateway)

    def test_bootstrap_can_mint_only_its_own_short_lived_admin_token(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        rbac = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/lifecycle-tokenrequest-rbac.yaml",
        )

        self.assertIn('resources: ["serviceaccounts/token"]', rbac)
        self.assertIn(
            'resourceNames: ["kubernetes-deployer-test-lifecycle"]',
            rbac,
        )
        self.assertIn('verbs: ["create"]', rbac)
        self.assertNotIn("ClusterRole", rbac)

    def test_operator_client_is_opt_in(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        self.assertNotIn("templates/operator-client.yaml", rendered)
        self.assertNotIn("app.kubernetes.io/component: operator-client", rendered)

    def test_templates_emit_only_valid_resource_manifests(self) -> None:
        rendered_profiles = {
            "defaults": self.run_helm(
                "template",
                "kubernetes-deployer-test",
                str(CHART_DIR),
            ),
            "operator-client-with-skills": self.run_helm(
                "template",
                "kubernetes-deployer-test",
                str(CHART_DIR),
                "--set",
                "operatorClient.enabled=true",
                "--set",
                "operatorClient.skills[0]=kubernetes-sre",
            ),
            "kubernetes-profile": self.run_helm(
                "template",
                "kubernetes-deployer-test",
                str(CHART_DIR),
                "-f",
                str(CHART_DIR / "values-kubernetes.yaml"),
            ),
        }
        empty_sources: list[str] = []
        invalid_sources: list[str] = []
        for profile, rendered in rendered_profiles.items():
            for document in rendered.split("\n---\n"):
                source = next(
                    (line for line in document.splitlines() if line.startswith("# Source:")),
                    None,
                )
                if source is None:
                    continue
                meaningful = [
                    line
                    for line in document.splitlines()
                    if line.strip()
                    and line.strip() != "---"
                    and not line.lstrip().startswith("#")
                ]
                qualified_source = f"{profile}: {source}"
                if not meaningful:
                    empty_sources.append(qualified_source)
                elif not meaningful[0].startswith("apiVersion:"):
                    invalid_sources.append(qualified_source)
        self.assertFalse(
            empty_sources,
            msg=(
                "Helm 4 server validation rejects comment-only manifests:\n"
                + "\n".join(empty_sources)
            ),
        )
        self.assertFalse(
            invalid_sources,
            msg=(
                "Helm 4 server validation requires apiVersion as the first resource field:\n"
                + "\n".join(invalid_sources)
            ),
        )

    def test_operator_client_renders_attach_only_user_session(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "operatorClient.enabled=true",
            "--set",
            "operatorClient.skills[0]=kubernetes-sre",
        )
        client = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/operator-client.yaml",
        )
        gateway_policy = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/gateway-networkpolicy.yaml",
        )
        config = self.bootstrap_config(rendered)

        self.assertIn("kind: ServiceAccount", client)
        self.assertIn("kind: StatefulSet", client)
        self.assertIn("automountServiceAccountToken: false", client)
        self.assertIn('audience: "openshell-cli"', client)
        self.assertIn("expirationSeconds: 3600", client)
        self.assertIn("stdin: true", client)
        self.assertIn("tty: true", client)
        self.assertIn("/tools/hermes-chat", client)
        self.assertIn("readOnlyRootFilesystem: true", client)
        self.assertIn("allowPrivilegeEscalation: false", client)
        self.assertIn('drop: ["ALL"]', client)
        self.assertNotIn("model-api-key", client)
        self.assertNotIn("sre-proxy-auth", client)
        self.assertNotIn("pods/exec", client)
        self.assertIn("app.kubernetes.io/component: operator-client", gateway_policy)
        self.assertTrue(config["operatorClient"]["enabled"])
        self.assertEqual(
            config["operatorClient"]["subject"],
            "system:serviceaccount:default:kubernetes-deployer-test-operator-client",
        )

    def test_operator_client_name_reserves_statefulset_suffix_budget(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-hermes-sre",
            str(CHART_DIR),
            "--set",
            "operatorClient.enabled=true",
        )
        client = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/operator-client.yaml",
        )
        match = re.search(r"kind: StatefulSet\nmetadata:\n  name: ([^\n]+)", client)
        self.assertIsNotNone(match)
        statefulset_name = match.group(1)
        self.assertLessEqual(
            len(statefulset_name),
            52,
            msg="StatefulSet names must reserve 11 characters for the revision-hash label",
        )

    def test_operator_client_rejects_existing_gateway_mode(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-existing-gateway.yaml"),
            "--set",
            "operatorClient.enabled=true",
            expected="operatorClient.enabled requires openshell.mode=managed",
        )

    def test_token_bootstrap_requires_explicit_external_lifecycle_service_account(self) -> None:
        for name in (None, "default"):
            arguments = [
                "template",
                "kubernetes-deployer-test",
                str(CHART_DIR),
                "--set",
                "operatorClient.enabled=true",
                "--set",
                "lifecycle.serviceAccount.create=false",
            ]
            if name is not None:
                arguments.extend(["--set", f"lifecycle.serviceAccount.name={name}"])
            with self.subTest(name=name):
                self.assert_helm_rejected(
                    arguments[0],
                    *arguments[1:],
                    expected=(
                        "serviceAccountToken bootstrap with lifecycle.serviceAccount.create=false "
                        "requires an explicit non-default lifecycle.serviceAccount.name"
                    ),
                )

    def test_disabled_operator_client_removes_stale_workspace_membership(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "bootstrap.py"
        config = {
            "openshellMode": "managed",
            "operatorClient": {
                "enabled": False,
                "workspace": "default",
                "subject": "system:serviceaccount:demo:release-operator-client",
            }
        }
        spec = importlib.util.spec_from_file_location("nemoclaw_bootstrap_membership", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        with mock.patch("pathlib.Path.read_text", return_value=json.dumps(config)):
            spec.loader.exec_module(module)

        absent = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="workspace member not found",
        )
        with mock.patch.object(module, "run", return_value=absent) as run:
            module.reconcile_operator_client_member()

        run.assert_called_once_with(
            [
                "workspace",
                "member",
                "remove",
                "--workspace",
                "default",
                "--subject",
                "system:serviceaccount:demo:release-operator-client",
            ],
            check=False,
            capture=True,
        )

    def test_operator_client_documents_single_operator_boundary(self) -> None:
        readme = CHART_DIR.joinpath("README.md").read_text(encoding="utf-8")
        notes = CHART_DIR.joinpath("templates", "NOTES.txt").read_text(encoding="utf-8")
        for document in (readme, notes):
            self.assertIn("one trusted operator", document)
            self.assertIn("mutually untrusted users", document)

    def test_operator_client_documents_oc_attach_disconnect_behavior(self) -> None:
        readme = CHART_DIR.joinpath("README.md").read_text(encoding="utf-8")
        self.assertNotIn("Ctrl-P", readme)
        self.assertNotIn("Ctrl-Q", readme)
        self.assertIn("`oc attach` does not provide a detach-key option", readme)
        self.assertIn("`Ctrl-C` ends the current Hermes session", readme)

    def test_operator_client_builds_only_a_hermes_sandbox_command(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "operator_client.py"
        self.assertTrue(script.is_file(), "operator client runtime is missing")
        spec = importlib.util.spec_from_file_location("nemoclaw_operator_client", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with mock.patch.dict(
            os.environ,
            {
                "OPENSHELL_SANDBOX_NAME": "release-hermes",
                "OPENSHELL_WORKSPACE": "default",
                "HERMES_SKILLS": "kubernetes-sre",
            },
            clear=True,
        ):
            interactive = module.hermes_command([])
            oneshot = module.hermes_command(["--oneshot", "count pods"])

        self.assertEqual(
            interactive,
            [
                "/tools/openshell",
                "sandbox",
                "exec",
                "--name",
                "release-hermes",
                "--workdir",
                "/sandbox/workspace",
                "--timeout",
                "0",
                "--tty",
                "--",
                "hermes",
                "--skills",
                "kubernetes-sre",
            ],
        )
        self.assertIn("--no-tty", oneshot)
        self.assertNotIn("--tty", oneshot)
        self.assertEqual(oneshot[-2:], ["--oneshot", "count pods"])

    def test_operator_client_rejects_an_admin_bearer_token(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "operator_client.py"
        self.assertTrue(script.is_file(), "operator client runtime is missing")
        spec = importlib.util.spec_from_file_location("nemoclaw_operator_client_token", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        claims = {
            "iss": "https://kubernetes.default.svc",
            "sub": "system:serviceaccount:demo:release-operator-client",
            "aud": ["openshell-cli", "openshell-admin"],
            "exp": int(time.time()) + 900,
        }
        encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        token = f"header.{encoded}.signature"
        with self.assertRaisesRegex(SystemExit, "must not contain the OpenShell admin role"):
            module.validate_token(
                token,
                issuer="https://kubernetes.default.svc",
                audience="openshell-cli",
                admin_role="openshell-admin",
                subject="system:serviceaccount:demo:release-operator-client",
            )

    def test_oidc_custom_ca_preserves_public_model_endpoint_trust(self) -> None:
        """The OIDC CA supplements, rather than replaces, native public roots."""
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        gateway = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/charts/openshell/templates/statefulset.yaml",
        )

        self.assertRegex(
            gateway,
            r"name: SSL_CERT_FILE\s*\n\s+value: /etc/ssl/certs/ca-certificates\.crt",
        )
        self.assertRegex(
            gateway,
            r"name: SSL_CERT_DIR\s*\n\s+value: /etc/openshell-tls/oidc-ca",
        )
        self.assertIn("mountPath: /etc/openshell-tls/oidc-ca", gateway)

    # ------------------------------------------------------------------
    # NemoClaw access surfaces: dashboard (18789) and OpenAI-compatible API (8642)
    # ------------------------------------------------------------------

    OPENSHIFT_ROUTE_ARGUMENTS = (
        "-f",
        str(CHART_DIR / "values-openshift.yaml"),
        "--set",
        "access.exposure.type=route",
        "--set",
        "access.exposure.route.appsDomain=apps.example.test",
        "--api-versions",
        "security.openshift.io/v1",
        "--api-versions",
        "route.openshift.io/v1",
    )

    def test_access_relay_renders_by_default(self) -> None:
        rendered = self.run_helm("template", "release", str(CHART_DIR), "--namespace", "demo")
        relay = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/access-relay.yaml",
        )
        gateway_policy = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/gateway-networkpolicy.yaml",
        )
        config = self.bootstrap_config(rendered)

        self.assertIn("kind: ServiceAccount", relay)
        self.assertIn("kind: Deployment", relay)
        self.assertIn("kind: Service", relay)
        self.assertNotIn("kind: ConfigMap", relay, "no edge proxy without external exposure")
        self.assertNotIn("type: NodePort", relay)
        self.assertIn('value: "dashboard=18789,api=8642"', relay)
        self.assertIn('"/runtime/access_relay.py", "serve"', relay)
        self.assertIn("test -f /tmp/access-relay.ready", relay)
        self.assertIn('audience: "openshell-cli"', relay)
        self.assertIn("automountServiceAccountToken: false", relay)
        self.assertIn("readOnlyRootFilesystem: true", relay)
        self.assertIn('drop: ["ALL"]', relay)
        self.assertIn("containerPort: 18789", relay)
        self.assertIn("containerPort: 8642", relay)
        self.assertIn("subPath: access_relay.py", relay)
        self.assertIn("app.kubernetes.io/component: access-relay", gateway_policy)
        self.assertNotIn("kind: Route", rendered)
        self.assertNotIn("kind: Ingress", rendered)
        self.assertEqual(
            config["accessRelay"],
            {
                "enabled": True,
                "workspace": "default",
                "subject": "system:serviceaccount:demo:release-kubernetes-deployer-access",
            },
        )
        # Default ports match the managed image, so the sandbox environment and
        # its configuration identity stay unchanged for existing releases.
        self.assertNotIn("CHAT_UI_URL", config["agentEnv"])
        self.assertNotIn("NEMOCLAW_DASHBOARD_PORT", config["agentEnv"])
        self.assertNotIn("NEMOCLAW_HERMES_API_PORT", config["agentEnv"])

    def test_access_relay_can_be_disabled(self) -> None:
        rendered = self.run_helm(
            "template",
            "release",
            str(CHART_DIR),
            "--set",
            "access.enabled=false",
        )
        with self.assertRaises(AssertionError):
            self.rendered_from_source(
                rendered,
                "kubernetes-deployer/templates/access-relay.yaml",
            )
        gateway_policy = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/gateway-networkpolicy.yaml",
        )
        self.assertNotIn("access-relay", gateway_policy)
        self.assertFalse(self.bootstrap_config(rendered)["accessRelay"]["enabled"])
        self.assertNotIn("access_relay.py", rendered)

    def test_access_relay_rejects_existing_gateway_mode(self) -> None:
        self.assert_helm_rejected(
            "template",
            "release",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-existing-gateway.yaml"),
            "--set",
            "access.enabled=true",
            expected="access.enabled requires openshell.mode=managed",
        )
        # The existing-gateway profile disables the relay atomically.
        rendered = self.run_helm(
            "template",
            "release",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-existing-gateway.yaml"),
        )
        self.assertNotIn("app.kubernetes.io/component: access-relay", rendered)
        self.assertNotIn("access_relay.py: |", rendered)

    def test_access_route_exposure_protects_dashboard_with_oauth_proxy(self) -> None:
        rendered = self.run_helm(
            "template",
            "release",
            str(CHART_DIR),
            "--namespace",
            "demo",
            *self.OPENSHIFT_ROUTE_ARGUMENTS,
        )
        relay = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/access-relay.yaml",
        )
        exposure = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/access-exposure.yaml",
        )
        config = self.bootstrap_config(rendered)
        dashboard_host = "release-kubernetes-deployer-dashboard.apps.example.test"
        api_host = "release-kubernetes-deployer-api.apps.example.test"

        self.assertEqual(exposure.count("kind: Route"), 2)
        self.assertIn(f'host: "{dashboard_host}"', exposure)
        self.assertIn(f'host: "{api_host}"', exposure)
        self.assertIn("targetPort: oauth-https", exposure)
        self.assertIn("termination: reencrypt", exposure)
        self.assertIn("targetPort: edge-openai", exposure)
        self.assertIn("termination: edge", exposure)
        self.assertIn("insecureEdgeTerminationPolicy: Redirect", exposure)
        self.assertIn("kind: ClusterRoleBinding", exposure)
        self.assertIn("name: system:auth-delegator", exposure)
        self.assertIn("dashboard-oauth-proxy-cookie-signing", exposure)
        self.assertNotIn("cluster-admin", exposure)

        self.assertIn("serviceaccounts.openshift.io/oauth-redirectreference.primary", relay)
        self.assertIn("service.beta.openshift.io/serving-cert-secret-name", relay)
        self.assertIn("- name: oauth-proxy", relay)
        self.assertIn('"--upstream=http://127.0.0.1:8080"', relay)
        self.assertIn("--cookie-samesite=lax", relay)
        self.assertIn("--pass-access-token=false", relay)
        self.assertIn(
            '"--openshift-sar={\\"namespace\\":\\"demo\\",\\"resource\\":\\"services\\",'
            '\\"resourceName\\":\\"release-kubernetes-deployer-access\\",\\"verb\\":\\"get\\"}"',
            relay,
        )
        self.assertIn(
            '"--openshift-delegate-urls={\\"/\\":{\\"namespace\\":\\"demo\\",\\"resource\\":\\"services\\",'
            '\\"resourceName\\":\\"release-kubernetes-deployer-access\\",\\"verb\\":\\"get\\"}}"',
            relay,
        )
        # The nginx edge validates the browser Origin, then presents the
        # loopback Host/Origin values the Hermes dashboard requires.
        self.assertIn("- name: edge", relay)
        self.assertIn("proxy_set_header Host 127.0.0.1:18789;", relay)
        self.assertIn('default "http://127.0.0.1:18789";', relay)
        self.assertIn("if ($edge_origin_host = $http_host)", relay)
        self.assertIn("return 403;", relay)
        self.assertIn("proxy_set_header Host 127.0.0.1:8642;", relay)
        self.assertIn("proxy_set_header Upgrade $http_upgrade;", relay)
        self.assertNotIn("type: NodePort", relay)
        self.assertEqual(config["agentEnv"]["CHAT_UI_URL"], f"https://{dashboard_host}")

    def test_access_route_requires_openshift_profile_and_hosts(self) -> None:
        self.assert_helm_rejected(
            "template",
            "release",
            str(CHART_DIR),
            "--set",
            "access.exposure.type=route",
            expected="access.exposure.type=route requires platform.openshift.enabled=true",
        )
        self.assert_helm_rejected(
            "template",
            "release",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-openshift.yaml"),
            "--set",
            "access.exposure.type=route",
            "--api-versions",
            "security.openshift.io/v1",
            "--api-versions",
            "route.openshift.io/v1",
            expected="access.exposure.route.dashboard.host or access.exposure.route.appsDomain is required",
        )

    def test_access_route_without_oauth_requires_acknowledgement(self) -> None:
        self.assert_helm_rejected(
            "template",
            "release",
            str(CHART_DIR),
            *self.OPENSHIFT_ROUTE_ARGUMENTS,
            "--set",
            "access.exposure.route.oauthProxy.enabled=false",
            expected="disabling access.exposure.route.oauthProxy publishes the Hermes dashboard without a login",
        )
        rendered = self.run_helm(
            "template",
            "release",
            str(CHART_DIR),
            *self.OPENSHIFT_ROUTE_ARGUMENTS,
            "--set",
            "access.exposure.route.oauthProxy.enabled=false",
            "--set",
            "access.exposure.dashboardUnauthenticatedAcknowledgement=I_ACKNOWLEDGE_UNAUTHENTICATED_DASHBOARD",
        )
        exposure = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/access-exposure.yaml",
        )
        self.assertIn("unauthenticated-dashboard-route", exposure)
        self.assertIn("targetPort: edge-dashboard", exposure)
        self.assertNotIn("kind: ClusterRoleBinding", exposure)
        self.assertNotIn("oauth-proxy", rendered)

    def test_access_ingress_and_nodeport_require_acknowledgement(self) -> None:
        for exposure_type in ("ingress", "nodePort"):
            self.assert_helm_rejected(
                "template",
                "release",
                str(CHART_DIR),
                "--set",
                f"access.exposure.type={exposure_type}",
                "--set",
                "access.exposure.ingress.dashboard.host=hermes.example.test",
                "--set",
                "access.exposure.ingress.api.host=hermes-api.example.test",
                expected="publishes the Hermes dashboard without a login",
            )
        acknowledgement = (
            "access.exposure.dashboardUnauthenticatedAcknowledgement="
            "I_ACKNOWLEDGE_UNAUTHENTICATED_DASHBOARD"
        )
        ingress_rendered = self.run_helm(
            "template",
            "release",
            str(CHART_DIR),
            "--set",
            "access.exposure.type=ingress",
            "--set",
            "access.exposure.ingress.dashboard.host=hermes.example.test",
            "--set",
            "access.exposure.ingress.api.host=hermes-api.example.test",
            "--set",
            acknowledgement,
        )
        ingress = self.rendered_from_source(
            ingress_rendered,
            "kubernetes-deployer/templates/access-exposure.yaml",
        )
        self.assertIn("kind: Ingress", ingress)
        self.assertIn('host: "hermes.example.test"', ingress)
        self.assertIn("name: edge-dashboard", ingress)
        self.assertIn("name: edge-openai", ingress)
        self.assertEqual(
            self.bootstrap_config(ingress_rendered)["agentEnv"]["CHAT_UI_URL"],
            "http://hermes.example.test",
        )

        nodeport_rendered = self.run_helm(
            "template",
            "release",
            str(CHART_DIR),
            "--set",
            "access.exposure.type=nodePort",
            "--set",
            "access.exposure.nodePort.dashboard=31789",
            "--set",
            acknowledgement,
        )
        relay = self.rendered_from_source(
            nodeport_rendered,
            "kubernetes-deployer/templates/access-relay.yaml",
        )
        self.assertIn("type: NodePort", relay)
        self.assertIn("nodePort: 31789", relay)
        self.assertIn("unauthenticated-dashboard-node-port", relay)
        # Only the edge ports leave the node; the raw relay listeners stay ClusterIP.
        external = relay.split("type: NodePort", 1)[1]
        self.assertNotIn("port: 18789", external)
        self.assertNotIn("port: 8642", external)

    def test_access_ports_follow_the_nemoclaw_image_contract(self) -> None:
        self.assert_helm_rejected(
            "template",
            "release",
            str(CHART_DIR),
            "--set",
            "access.api.port=9000",
            expected="access/api/port",
        )
        self.assert_helm_rejected(
            "template",
            "release",
            str(CHART_DIR),
            "--set",
            "access.dashboard.port=8642",
            expected="must not use the NemoClaw Hermes API range",
        )
        rendered = self.run_helm(
            "template",
            "release",
            str(CHART_DIR),
            "--set",
            "access.dashboard.port=18790",
            "--set",
            "access.api.port=8643",
            "--set",
            "access.dashboard.externalUrl=https://ignored.example.test",
        )
        env = self.bootstrap_config(rendered)["agentEnv"]
        self.assertEqual(env["NEMOCLAW_DASHBOARD_PORT"], "18790")
        self.assertEqual(env["NEMOCLAW_HERMES_API_PORT"], "8643")
        # NemoClaw forces a loopback CHAT_UI_URL whenever an explicit dashboard
        # port is supplied, so the chart does not send a conflicting origin.
        self.assertNotIn("CHAT_UI_URL", env)
        relay = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/access-relay.yaml",
        )
        self.assertIn('value: "dashboard=18790,api=8643"', relay)

    def test_nemoclaw_home_volume_keeps_the_api_gateway_undrained(self) -> None:
        # NemoClaw refuses OpenAI-compatible API turns unless /sandbox/.nemoclaw
        # is root-owned; OpenShell chowns /sandbox to the injected UID. The chart
        # mounts a prepared read-only volume there.
        rendered = self.run_helm("template", "release", str(CHART_DIR))
        home = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/nemoclaw-home.yaml",
        )
        self.assertIn("kind: PersistentVolumeClaim", home)
        self.assertIn("kind: Job", home)
        self.assertIn('helm.sh/hook-weight: "5"', home)
        self.assertIn("runAsUser: 0", home)
        self.assertIn("readOnlyRootFilesystem: true", home)
        self.assertIn("chcon system_u:object_r:container_file_t:s0 /nemoclaw-home", home)
        self.assertIn("serviceAccountName: release-openshell-sandbox", home)
        driver = self.bootstrap_config(rendered)["driverConfig"]["kubernetes"]
        mounts = driver["containers"]["agent"]["volume_mounts"]
        home_mount = [mount for mount in mounts if mount["mount_path"] == "/sandbox/.nemoclaw"]
        self.assertEqual(len(home_mount), 1)
        self.assertTrue(home_mount[0]["read_only"])
        volumes = {volume["name"]: volume for volume in driver["volumes"]}
        self.assertTrue(volumes["nemoclaw-home"]["persistent_volume_claim"]["read_only"])
        self.assertEqual(
            volumes["nemoclaw-home"]["persistent_volume_claim"]["claim_name"],
            "release-kubernetes-deployer-nemoclaw-home",
        )
        # The bootstrap hook (weight 10) must run after the prepare hook.
        bootstrap = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/bootstrap-job.yaml",
        )
        self.assertIn('helm.sh/hook-weight: "10"', bootstrap)

        disabled = self.run_helm(
            "template",
            "release",
            str(CHART_DIR),
            "--set",
            "agent.nemoclawHome.enabled=false",
        )
        with self.assertRaises(AssertionError):
            self.rendered_from_source(
                disabled,
                "kubernetes-deployer/templates/nemoclaw-home.yaml",
            )
        mounts = self.bootstrap_config(disabled)["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
        self.assertEqual([mount["mount_path"] for mount in mounts], ["/sandbox/workspace"])

    def test_service_names_avoid_nemoclaw_rejected_environment_segments(self) -> None:
        # Kubernetes Service links turn Service and port names into sandbox
        # environment variables; NemoClaw refuses names with an API/KEY/TOKEN
        # style segment, which was observed live as
        # NEMOCLAW_HERMES_..._SERVICE_PORT_API refusing Hermes startup.
        rendered = self.run_helm("template", "nemoclaw-hermes", str(CHART_DIR))
        service_port_names = re.findall(r"^\s+- name: ([a-z0-9-]+)\n\s+port: ", rendered, flags=re.M)
        self.assertTrue(service_port_names)
        forbidden = re.compile(r"(^|-)(token|key|secret|password|credential|api)(-|$)")
        for name in service_port_names:
            self.assertIsNone(forbidden.search(name), name)
        for service_name in re.findall(r"^kind: Service\nmetadata:\n  name: (\S+)", rendered, flags=re.M):
            self.assertIsNone(forbidden.search(service_name), service_name)
        self.assert_helm_rejected(
            "template",
            "hermes-api",
            str(CHART_DIR),
            expected="would become a Kubernetes Service environment variable that NemoClaw rejects",
        )

    def test_access_reserves_chart_managed_sandbox_environment(self) -> None:
        for name in ("CHAT_UI_URL", "NEMOCLAW_DASHBOARD_PORT", "NEMOCLAW_HERMES_API_PORT"):
            self.assert_helm_rejected(
                "template",
                "release",
                str(CHART_DIR),
                "--set",
                f"agent.env.{name}=value",
                expected=f"agent.env.{name} is chart-managed",
            )

    def test_bootstrap_reconciles_access_relay_membership(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "bootstrap.py"
        config = {
            "openshellMode": "managed",
            "operatorClient": {
                "enabled": False,
                "workspace": "default",
                "subject": "system:serviceaccount:demo:release-operator-client",
            },
            "accessRelay": {
                "enabled": True,
                "workspace": "default",
                "subject": "system:serviceaccount:demo:release-access",
            },
        }
        spec = importlib.util.spec_from_file_location("nemoclaw_bootstrap_access", script)
        module = importlib.util.module_from_spec(spec)
        with mock.patch("pathlib.Path.read_text", return_value=json.dumps(config)):
            spec.loader.exec_module(module)

        success = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch.object(module, "run", return_value=success) as run:
            module.reconcile_operator_client_member()

        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                [
                    "workspace",
                    "member",
                    "remove",
                    "--workspace",
                    "default",
                    "--subject",
                    "system:serviceaccount:demo:release-operator-client",
                ],
                [
                    "workspace",
                    "member",
                    "add",
                    "--workspace",
                    "default",
                    "--subject",
                    "system:serviceaccount:demo:release-access",
                    "--role",
                    "user",
                ],
            ],
        )

    def test_access_relay_script_enforces_user_role_and_fixed_forwards(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "access_relay.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_access_relay", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def token(audiences: list[str]) -> str:
            claims = {
                "aud": audiences,
                "iss": "https://kubernetes.default.svc",
                "sub": "system:serviceaccount:demo:release-access",
                "exp": int(time.time()) + 3600,
            }
            encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
            return f"header.{encoded}.signature"

        with self.assertRaisesRegex(SystemExit, "must not contain the OpenShell admin role"):
            module.validate_token(
                token(["openshell-cli", "openshell-admin"]),
                issuer="https://kubernetes.default.svc",
                audience="openshell-cli",
                admin_role="openshell-admin",
                subject="system:serviceaccount:demo:release-access",
            )
        self.assertGreater(
            module.validate_token(
                token(["openshell-cli"]),
                issuer="https://kubernetes.default.svc",
                audience="openshell-cli",
                admin_role="openshell-admin",
                subject="system:serviceaccount:demo:release-access",
            ),
            int(time.time()),
        )

        with mock.patch.dict(
            os.environ,
            {"ACCESS_FORWARDS": "dashboard=18789,api=8642", "OPENSHELL_SANDBOX_NAME": "release-hermes"},
        ):
            self.assertEqual(module.parse_forwards(), [("dashboard", 18789), ("api", 8642)])
            self.assertEqual(
                module.forward_command(18789),
                [
                    "/tools/openshell",
                    "forward",
                    "service",
                    "release-hermes",
                    "--target-port",
                    "18789",
                    "--target-host",
                    "127.0.0.1",
                    "--local",
                    "0.0.0.0:18789",
                ],
            )
        for invalid in ("dashboard=80", "dashboard=18789,api=18789", "bad", ""):
            with mock.patch.dict(os.environ, {"ACCESS_FORWARDS": invalid}):
                with self.assertRaises(SystemExit):
                    module.parse_forwards()
        source = script.read_text(encoding="utf-8")
        self.assertIn("API_SERVER_KEY=", source)
        self.assertIn("/sandbox/.hermes/.env", source)
        self.assertIn('"--no-tty"', source)

    def test_notes_and_readme_document_quickstart_equivalents(self) -> None:
        notes = CHART_DIR.joinpath("templates", "NOTES.txt").read_text(encoding="utf-8")
        for fragment in ("dashboard-url", "gateway-token", "port-forward", "status", "logs --follow"):
            self.assertIn(fragment, notes)
        readme = CHART_DIR.joinpath("README.md").read_text(encoding="utf-8")
        for fragment in (
            "18789",
            "8642",
            "gateway-token",
            "I_ACKNOWLEDGE_UNAUTHENTICATED_DASHBOARD",
            "openshell forward service",
            "access.exposure.type",
        ):
            self.assertIn(fragment, readme)

    def test_gateway_ingress_is_release_scoped(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        policy = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/gateway-networkpolicy.yaml",
        )

        self.assertIn("app.kubernetes.io/name: openshell", policy)
        self.assertIn("app.kubernetes.io/instance: kubernetes-deployer-test", policy)
        self.assertIn("app.kubernetes.io/component: bootstrap", policy)
        self.assertIn("key: agents.x-k8s.io/sandbox-name-hash", policy)
        self.assertIn("operator: Exists", policy)
        self.assertNotIn("openshell.ai/managed-by: openshell", policy)
        self.assertIn("port: 8080", policy)

    def test_managed_gateway_rejects_anonymous_bootstrap(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "openshell.server.auth.allowUnauthenticatedUsers=true",
            expected="allowUnauthenticatedUsers must remain false",
        )

    def test_existing_gateway_client_tls_does_not_mount_service_account_token(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-existing-gateway.yaml"),
        )
        bootstrap = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/bootstrap-job.yaml",
        )

        self.assertNotIn("openshell-bootstrap-token", bootstrap)
        self.assertNotIn("OPENSHELL_OIDC_ISSUER", bootstrap)

    def test_openshift_profile_requires_openshift_api(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--values",
            str(CHART_DIR / "values-openshift.yaml"),
            expected="security.openshift.io/v1",
        )

    def test_kubernetes_mode_rejects_openshift_scc_binding(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "platform.openshift.createPrivilegedSccBinding=true",
            "--set-string",
            "platform.openshift.dangerousAcknowledgement=I_ACKNOWLEDGE_PRIVILEGED_SCC",
            expected="platform.openshift.enabled",
        )

    def test_python_runtime_helpers_compile(self) -> None:
        for script in CHART_DIR.joinpath("files", "scripts").glob("*.py"):
            with self.subTest(script=script.name):
                compile(script.read_text(encoding="utf-8"), str(script), "exec")

    def test_sandbox_create_does_not_combine_command_with_output_flag(self) -> None:
        bootstrap = CHART_DIR.joinpath("files", "scripts", "bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn('"--output",\n        "json",', bootstrap)

    def test_inference_provider_is_not_attached_to_sandbox(self) -> None:
        bootstrap = CHART_DIR.joinpath("files", "scripts", "bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn(
            '"--provider",\n        CONFIG["model"]["providerName"],',
            bootstrap,
        )
        self.assertIn('"inference",\n        "set",', bootstrap)

    def test_sandbox_startup_preserves_nemoclaw_process_identity(self) -> None:
        bootstrap = CHART_DIR.joinpath("files", "scripts", "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn('arguments.extend(["--env", f"{key}={value}"])', bootstrap)
        self.assertIn('arguments.extend(["--", "/bin/sh", "-c", startup])', bootstrap)
        self.assertIn('exec /usr/local/bin/nemoclaw-start', bootstrap)
        self.assertNotIn('arguments.append("env")', bootstrap)
        self.assertNotIn('"/bin/bash"', bootstrap)

    def test_seed_preserves_storage_root_permissions(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "seed.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_seed", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        os.environ["RELEASE_ID"] = "test/release"
        os.environ["RELEASE_REVISION"] = "1"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir()
            state.chmod(0o775)
            module.STATE = state
            module.MARKER = state / ".nemoclaw-helm-owner.json"
            module.RELEASE = "test/release"
            module.RELEASE_REVISION = 1
            module.main()

            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o775)
            self.assertEqual(stat.S_IMODE((state / "hermes").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((state / "workspace").stat().st_mode), 0o700)

    def test_packaged_chart_excludes_review_only_sources_and_large_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.run_helm("package", str(CHART_DIR), "--destination", directory)
            packages = list(Path(directory).glob("*.tgz"))
            self.assertEqual(len(packages), 1)
            package = packages[0]
            self.assertLess(package.stat().st_size, 500_000)
            with tarfile.open(package, mode="r:gz") as archive:
                members = {member.name for member in archive.getmembers()}
            prefix = f"{CHART_DIR.name}/"
            self.assertIn(f"{prefix}LICENSE", members)
            self.assertIn(f"{prefix}THIRD-PARTY-NOTICES", members)
            self.assertFalse(any(name.startswith(f"{prefix}docs/") for name in members))
            self.assertFalse(any(name.startswith(f"{prefix}scripts/") for name in members))
            self.assertFalse(
                any(name.startswith(f"{prefix}files/skills/") for name in members)
            )
            self.assertTrue(
                any(name.startswith(f"{prefix}files/scripts/") for name in members)
            )

    def test_existing_gateway_rejects_plaintext_endpoint(self) -> None:
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set-string",
            "openshell.mode=existing",
            "--set",
            "openshell.enabled=false",
            "--set-string",
            "openshell.existing.endpoint=http://openshell.example:8080",
            expected="https://",
        )

    def test_security_config_identity_changes_with_agent_configuration(self) -> None:
        baseline = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        changed = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set-string",
            "agent.env.FEATURE_FLAG=enabled",
        )
        baseline_labels = self.bootstrap_config(baseline)["labels"]
        changed_labels = self.bootstrap_config(changed)["labels"]
        self.assertIn("nemoclaw.nvidia.com/config-id", baseline_labels)
        self.assertNotEqual(
            baseline_labels["nemoclaw.nvidia.com/config-id"],
            changed_labels["nemoclaw.nvidia.com/config-id"],
        )

    def test_generated_sandbox_name_respects_openshell_limit(self) -> None:
        rendered = self.run_helm(
            "template",
            "a-release-name-that-is-longer-than-openshell-allows",
            str(CHART_DIR),
        )
        sandbox_name = self.bootstrap_config(rendered)["sandboxName"]
        self.assertLessEqual(len(sandbox_name), 19)
        self.assertRegex(sandbox_name, r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

    def test_existing_gateway_mode_does_not_install_openshell_subchart(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-existing-gateway.yaml"),
        )
        self.assertNotIn("charts/openshell/templates/", rendered)
        self.assertIn("https://openshell.example.svc.cluster.local:8080", rendered)

    def test_existing_gateway_defaults_are_namespace_scoped(self) -> None:
        rendered_a = self.run_helm(
            "template",
            "shared-release",
            str(CHART_DIR),
            "--namespace",
            "team-a",
            "-f",
            str(CHART_DIR / "values-existing-gateway.yaml"),
        )
        rendered_b = self.run_helm(
            "template",
            "shared-release",
            str(CHART_DIR),
            "--namespace",
            "team-b",
            "-f",
            str(CHART_DIR / "values-existing-gateway.yaml"),
        )
        config_a = self.bootstrap_config(rendered_a)
        config_b = self.bootstrap_config(rendered_b)

        self.assertNotEqual(config_a["sandboxName"], config_b["sandboxName"])
        self.assertNotEqual(config_a["model"]["providerName"], config_b["model"]["providerName"])
        self.assertNotEqual(
            config_a["labels"]["nemoclaw.nvidia.com/release-id"],
            config_b["labels"]["nemoclaw.nvidia.com/release-id"],
        )

    def test_bootstrap_verifies_sandbox_ownership_before_provider_mutation(self) -> None:
        bootstrap = CHART_DIR.joinpath("files", "scripts", "bootstrap.py").read_text(encoding="utf-8")
        main_body = bootstrap.split("def main() -> None:", 1)[1]
        self.assertLess(
            main_body.index("verify_existing_sandbox()"),
            main_body.index("inspect_provider(existing_sandbox)"),
        )
        self.assertLess(
            main_body.index("inspect_provider(existing_sandbox)"),
            main_body.index("reconcile_provider(provider_exists)"),
        )
        self.assertLess(
            main_body.index("reconcile_provider(provider_exists)"),
            main_body.index("create_sandbox()"),
        )

    def test_bootstrap_refuses_unowned_existing_provider_collision(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "bootstrap.py"
        config = {
            "model": {
                "providerName": "shared-provider",
                "providerType": "openai",
                "baseUrl": "https://example.invalid/v1",
                "name": "example/model",
                "requestTimeoutSeconds": 30,
                "verifyEndpoint": False,
            }
        }
        with mock.patch.object(Path, "read_text", return_value=json.dumps(config)):
            spec = importlib.util.spec_from_file_location("nemoclaw_bootstrap_provider", script)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        existing = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        module.run = mock.Mock(return_value=existing)
        with self.assertRaisesRegex(SystemExit, "provider.*ownership"):
            module.inspect_provider(False)
        module.run.assert_called_once_with(
            ["provider", "get", "shared-provider"], check=False, capture=True
        )
        module.run = mock.Mock(
            return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="provider not found")
        )
        self.assertFalse(module.inspect_provider(False))
        module.run = mock.Mock(
            return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="gateway unavailable")
        )
        with self.assertRaisesRegex(SystemExit, "determine provider ownership safely"):
            module.inspect_provider(False)

    def test_bootstrap_reclaims_release_provider_on_managed_gateway(self) -> None:
        # Deleting the Sandbox through OpenShell and upgrading is the documented
        # recovery path. On the dedicated chart-managed gateway the provider
        # that outlived the Sandbox is still this release's provider.
        script = CHART_DIR / "files" / "scripts" / "bootstrap.py"
        config = {
            "openshellMode": "managed",
            "model": {
                "providerName": "release-model",
                "providerType": "openai",
                "baseUrl": "https://example.invalid/v1",
                "name": "example/model",
                "requestTimeoutSeconds": 30,
                "verifyEndpoint": False,
            },
        }
        with mock.patch.object(Path, "read_text", return_value=json.dumps(config)):
            spec = importlib.util.spec_from_file_location("nemoclaw_bootstrap_managed_provider", script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        module.run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, stdout="{}", stderr=""))
        self.assertTrue(module.inspect_provider(False))
        module.run.assert_called_once_with(
            ["provider", "get", "release-model"], check=False, capture=True
        )
        # Existing-gateway mode keeps failing closed for the same situation.
        config["openshellMode"] = "existing"
        with mock.patch.object(Path, "read_text", return_value=json.dumps(config)):
            spec = importlib.util.spec_from_file_location("nemoclaw_bootstrap_existing_provider", script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        module.run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, stdout="{}", stderr=""))
        with self.assertRaisesRegex(SystemExit, "provider.*ownership"):
            module.inspect_provider(False)

    def test_bootstrap_hardens_injected_uid_paths_before_nemoclaw_start(self) -> None:
        bootstrap = CHART_DIR.joinpath("files", "scripts", "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("test -d /sandbox && test ! -L /sandbox", bootstrap)
        self.assertIn("chmod u=rwx,g=rwx,o=,g-s,o-t /sandbox", bootstrap)
        self.assertIn("chmod u=rwx,g=,o=,g-s,o-t /sandbox/.hermes", bootstrap)
        self.assertIn("exec /usr/local/bin/nemoclaw-start", bootstrap)
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
        )
        config = self.bootstrap_config(rendered)
        self.assertEqual(config["startupContract"], "normalize-injected-uid-path-modes-v1")

    def test_cluster_scoped_names_include_release_identity(self) -> None:
        arguments = (
            "--set",
            "platform.serviceAccountIssuerDiscovery.createPublicBinding=true",
            "--set-string",
            "platform.serviceAccountIssuerDiscovery.dangerousAcknowledgement=I_ACKNOWLEDGE_PUBLIC_OIDC_DISCOVERY",
        )
        rendered_a = self.run_helm(
            "template",
            "shared-release",
            str(CHART_DIR),
            "--namespace",
            "team-a",
            *arguments,
        )
        rendered_b = self.run_helm(
            "template",
            "shared-release",
            str(CHART_DIR),
            "--namespace",
            "team-b",
            *arguments,
        )
        binding_a = self.rendered_from_source(
            rendered_a,
            "kubernetes-deployer/templates/serviceaccount-issuer-discovery.yaml",
        )
        binding_b = self.rendered_from_source(
            rendered_b,
            "kubernetes-deployer/templates/serviceaccount-issuer-discovery.yaml",
        )
        name_a = re.search(r"(?m)^  name: (.+)$", binding_a).group(1)
        name_b = re.search(r"(?m)^  name: (.+)$", binding_b).group(1)
        self.assertNotEqual(name_a, name_b)
        self.assertLessEqual(len(name_a), 253)
        self.assertLessEqual(len(name_b), 253)

    def test_values_reject_secret_and_reserved_agent_environment(self) -> None:
        for override, expected in (
            ("agent.env.MY_API_KEY=not-a-real-key", "looks secret-bearing"),
            ("agent.env.NEMOCLAW_MODEL=override", "chart-managed"),
        ):
            with self.subTest(override=override):
                self.assert_helm_rejected(
                    "template",
                    "kubernetes-deployer-test",
                    str(CHART_DIR),
                    "--set-string",
                    override,
                    expected=expected,
                )

    # --- Review-blocker regressions and extension-point contracts -----------

    @staticmethod
    def raw_helm(*arguments: str) -> subprocess.CompletedProcess[str]:
        """Run Helm without the test defaults so the shipped defaults are exercised."""
        return subprocess.run(["helm", *arguments], check=False, capture_output=True, text=True)

    def load_seed_module(self, name: str):
        script = CHART_DIR / "files" / "scripts" / "seed.py"
        spec = importlib.util.spec_from_file_location(name, script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        os.environ["RELEASE_ID"] = "test/release"
        os.environ["RELEASE_REVISION"] = "1"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def point_seed_at(module, state: Path) -> None:
        module.STATE = state
        module.MARKER = state / ".nemoclaw-helm-owner.json"
        module.RELEASE = "test/release"
        module.RELEASE_REVISION = 1

    @staticmethod
    def snapshot_tree(root: Path) -> dict[str, tuple[object, ...]]:
        """Record every path with its type, mode bits, and (for files) exact bytes."""
        snapshot: dict[str, tuple[object, ...]] = {}
        for path in sorted([root, *root.rglob("*")]):
            info = path.lstat()
            entry: tuple[object, ...] = (stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode))
            if stat.S_ISREG(info.st_mode):
                entry = (*entry, path.read_bytes())
            snapshot[str(path.relative_to(root))] = entry
        return snapshot

    def load_bootstrap_module(self, name: str, config: dict[str, object]):
        script = CHART_DIR / "files" / "scripts" / "bootstrap.py"
        with mock.patch.object(Path, "read_text", return_value=json.dumps(config)):
            spec = importlib.util.spec_from_file_location(name, script)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def test_default_render_requires_an_issuer_discovery_decision(self) -> None:
        # Blocker: the shipped defaults must not describe an install whose
        # gateway cannot initialize authentication. Without a decision the
        # render fails and names both supported options.
        completed = self.raw_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--api-versions",
            "agents.x-k8s.io/v1alpha1",
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("without credentials", output)
        self.assertIn("values-kubernetes.yaml", output)
        self.assertIn("preexistingAnonymousAccess=true", output)
        values = CHART_DIR.joinpath("values.yaml").read_text(encoding="utf-8")
        self.assertIn("preexistingAnonymousAccess: false", values)
        self.assertIn("createPublicBinding: false", values)

    def test_kubernetes_profile_grants_only_issuer_discovery_to_anonymous_callers(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-kubernetes.yaml"),
        )
        binding = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/serviceaccount-issuer-discovery.yaml",
        )
        self.assertIn("kind: ClusterRoleBinding", binding)
        self.assertIn("name: system:service-account-issuer-discovery", binding)
        self.assertIn("name: system:unauthenticated", binding)
        self.assertNotIn("cluster-admin", rendered.lower())
        profile = CHART_DIR.joinpath("values-kubernetes.yaml").read_text(encoding="utf-8")
        self.assertIn("createPublicBinding: true", profile)
        self.assertIn("I_ACKNOWLEDGE_PUBLIC_OIDC_DISCOVERY", profile)
        openshift = CHART_DIR.joinpath("values-openshift.yaml").read_text(encoding="utf-8")
        self.assertIn("createPublicBinding: true", openshift)

    def test_platform_profiles_pin_the_issuer_their_cluster_publishes(self) -> None:
        # The gateway compares the configured issuer to the published one byte
        # for byte. OpenShift publishes the short in-cluster form; a default
        # kubeadm cluster publishes the fully qualified one, which crash-looped
        # the gateway with "OIDC discovery issuer mismatch" until the
        # Kubernetes profile pinned it.
        kubernetes = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-kubernetes.yaml"),
        )
        self.assertIn("https://kubernetes.default.svc.cluster.local", kubernetes)
        openshift = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--api-versions",
            "security.openshift.io/v1",
            "-f",
            str(CHART_DIR / "values-openshift.yaml"),
        )
        self.assertIn("https://kubernetes.default.svc", openshift)
        self.assertNotIn("kubernetes.default.svc.cluster.local", openshift)

    def test_issuer_discovery_guard_covers_both_in_cluster_issuer_spellings(self) -> None:
        # The guard used to match only the short spelling, so a cluster using
        # the fully qualified issuer silently skipped the discovery decision.
        # raw_helm keeps the shipped defaults, which make no discovery choice.
        for issuer in (
            "https://kubernetes.default.svc",
            "https://kubernetes.default.svc.cluster.local",
        ):
            with self.subTest(issuer=issuer):
                completed = self.raw_helm(
                    "template",
                    "kubernetes-deployer-test",
                    str(CHART_DIR),
                    "--api-versions",
                    "agents.x-k8s.io/v1alpha1",
                    "--set",
                    f"openshell.server.oidc.issuer={issuer}",
                )
                output = completed.stdout + completed.stderr
                self.assertNotEqual(completed.returncode, 0, msg=output)
                self.assertIn("without credentials", output)

    def test_relay_tools_mount_matches_the_container_runtime_of_each_platform(self) -> None:
        # CRI-O creates a nested mountpoint under a read-only parent mount;
        # containerd and runc refuse with "make mountpoint ...: read-only file
        # system". The relay nests /tools/nemoclaw-access inside the /tools
        # emptyDir, so the parent stays read-only only on OpenShift.
        def tools_mount_block(rendered: str) -> str:
            relay = self.rendered_from_source(
                rendered,
                "kubernetes-deployer/templates/access-relay.yaml",
            )
            marker = "command: [\"/usr/local/bin/python3\", \"-B\", \"/runtime/access_relay.py\", \"serve\"]"
            self.assertIn(marker, relay)
            container = relay.split(marker, 1)[1]
            start = container.index("- name: tools")
            return container[start : start + 160]

        kubernetes = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-kubernetes.yaml"),
        )
        kubernetes_block = tools_mount_block(kubernetes)
        self.assertIn("mountPath: /tools", kubernetes_block)
        self.assertNotIn("readOnly: true", kubernetes_block.split("- name: runtime", 1)[0])

        openshift = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--api-versions",
            "security.openshift.io/v1",
            "-f",
            str(CHART_DIR / "values-openshift.yaml"),
        )
        openshift_block = tools_mount_block(openshift)
        self.assertIn("mountPath: /tools", openshift_block)
        self.assertIn("readOnly: true", openshift_block.split("- name: runtime", 1)[0])

    def test_state_root_hook_relabels_only_for_a_real_selinux_context(self) -> None:
        # Ubuntu with containerd reports "cri-containerd.apparmor.d (enforce)"
        # in /proc/self/attr/current. Treating that as an SELinux label ran
        # chcon on a kernel without SELinux and failed the install with EPERM.
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-kubernetes.yaml"),
        )
        hook = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/templates/nemoclaw-home.yaml",
        )
        self.assertIn("*:*:*:*)", hook)
        self.assertIn("non-SELinux LSM context", hook)
        self.assertIn("chcon system_u:object_r:container_file_t:s0 /nemoclaw-home", hook)

    def test_preexisting_anonymous_access_renders_no_binding_and_excludes_the_public_one(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "platform.serviceAccountIssuerDiscovery.preexistingAnonymousAccess=true",
        )
        self.assertNotIn("templates/serviceaccount-issuer-discovery.yaml", rendered)
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "platform.serviceAccountIssuerDiscovery.preexistingAnonymousAccess=true",
            "--set",
            "platform.serviceAccountIssuerDiscovery.createPublicBinding=true",
            "--set",
            "platform.serviceAccountIssuerDiscovery.dangerousAcknowledgement=I_ACKNOWLEDGE_PUBLIC_OIDC_DISCOVERY",
            expected="mutually exclusive",
        )

    def test_bootstrap_probes_anonymous_issuer_discovery_before_waiting_for_the_gateway(self) -> None:
        bootstrap = CHART_DIR.joinpath("files", "scripts", "bootstrap.py").read_text(encoding="utf-8")
        main_body = bootstrap.split("def main() -> None:", 1)[1]
        self.assertLess(main_body.index("verify_issuer_discovery()"), main_body.index("wait_for_gateway()"))

        module = self.load_bootstrap_module("nemoclaw_bootstrap_issuer", {"sandboxName": "x", "labels": {}})
        environment = {
            "OPENSHELL_BOOTSTRAP_AUTH_MODE": "serviceAccountToken",
            "OPENSHELL_OIDC_ISSUER": "https://kubernetes.default.svc",
            "KUBERNETES_API_CA": "/var/run/secrets/openshell-token-request/ca.crt",
        }

        class FakeResponse:
            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *exc: object) -> bool:
                return False

            def read(self, limit: int) -> bytes:
                return self.payload[:limit]

        requested: list[str] = []

        def anonymous_ok(request, timeout, context):  # noqa: ANN001 - urllib signature
            requested.append(request.full_url)
            self.assertIsNone(request.get_header("Authorization"))
            if request.full_url.endswith("/.well-known/openid-configuration"):
                return FakeResponse(
                    json.dumps(
                        {
                            "issuer": "https://kubernetes.default.svc",
                            "jwks_uri": "https://api.cluster.example:6443/openid/v1/jwks",
                        }
                    ).encode()
                )
            return FakeResponse(json.dumps({"keys": [{"kid": "k1", "kty": "RSA"}]}).encode())

        def denied(request, timeout, context):  # noqa: ANN001 - urllib signature
            raise module.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        with mock.patch.dict(os.environ, environment, clear=False), mock.patch.object(
            module.ssl, "create_default_context", return_value=mock.Mock()
        ):
            with mock.patch.object(module, "urlopen", side_effect=anonymous_ok):
                module.verify_issuer_discovery()
            self.assertEqual(
                requested,
                [
                    "https://kubernetes.default.svc/.well-known/openid-configuration",
                    "https://api.cluster.example:6443/openid/v1/jwks",
                ],
            )
            with mock.patch.object(module, "urlopen", side_effect=denied):
                with self.assertRaisesRegex(SystemExit, "createPublicBinding=true"):
                    module.verify_issuer_discovery()
        # Operator mTLS bootstrap does not depend on OIDC discovery at all.
        with mock.patch.dict(os.environ, {"OPENSHELL_BOOTSTRAP_AUTH_MODE": "clientTLS"}, clear=False), mock.patch.object(
            module, "urlopen", side_effect=AssertionError("must not fetch")
        ):
            module.verify_issuer_discovery()

    def test_seed_leaves_a_foreign_owned_claim_byte_for_byte_and_mode_for_mode_unchanged(self) -> None:
        # Blocker: ownership must be checked before any create, chmod, or
        # marker write. A claim owned by another release is never modified.
        module = self.load_seed_module("nemoclaw_seed_foreign_owner")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            (state / "hermes" / "skills" / "custom").mkdir(parents=True)
            (state / "workspace").mkdir()
            (state / "hermes" / "skills" / "custom" / "SKILL.md").write_bytes(b"theirs\n")
            (state / "workspace" / "notes.md").write_bytes(b"keep me\n")
            (state / "hermes").chmod(0o755)
            (state / "hermes" / "skills").chmod(0o750)
            (state / "workspace").chmod(0o770)
            (state / ".nemoclaw-helm-owner.json").write_text(
                json.dumps({"schema": 1, "release": "other/release", "revision": 3, "status": "ready"}),
                encoding="utf-8",
            )
            before = self.snapshot_tree(state)
            self.point_seed_at(module, state)
            with self.assertRaisesRegex(SystemExit, "owned by another Helm release"):
                module.main()
            self.assertEqual(self.snapshot_tree(state), before)

    def test_seed_refuses_an_unmarked_populated_claim_without_touching_it(self) -> None:
        module = self.load_seed_module("nemoclaw_seed_unmarked")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            (state / "hermes" / "skills" / "existing").mkdir(parents=True)
            (state / "workspace").mkdir()
            (state / "lost+found").mkdir()
            (state / "hermes" / "skills" / "existing" / "SKILL.md").write_bytes(b"pre-existing\n")
            (state / "workspace" / "draft.txt").write_bytes(b"draft\n")
            (state / "hermes").chmod(0o755)
            (state / "workspace").chmod(0o775)
            before = self.snapshot_tree(state)
            self.point_seed_at(module, state)
            with self.assertRaisesRegex(SystemExit, "unmarked state volume"):
                module.main()
            self.assertEqual(self.snapshot_tree(state), before)
            self.assertFalse(module.MARKER.exists())
        # A freshly provisioned claim (only filesystem bookkeeping) is adopted.
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            (state / "lost+found").mkdir(parents=True)
            self.point_seed_at(module, state)
            with mock.patch.dict(os.environ, {"SEED_PLUGINS": "[]"}, clear=False):
                module.main()
            marker = json.loads(module.MARKER.read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "ready")
            self.assertEqual(stat.S_IMODE((state / "hermes").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((state / "workspace").stat().st_mode), 0o700)

    def test_seed_plugins_run_with_the_state_contract_and_keep_a_retryable_marker(self) -> None:
        module = self.load_seed_module("nemoclaw_seed_plugins")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir()
            plugins = Path(directory) / "plugins"
            (plugins / "demo").mkdir(parents=True)
            (plugins / "demo" / "seed_demo.py").write_text(
                "import os, sys\n"
                "from pathlib import Path\n"
                "state = Path(os.environ['SEED_STATE'])\n"
                "target = state / 'hermes' / 'skills' / 'demo'\n"
                "target.mkdir(parents=True, exist_ok=True)\n"
                "(target / 'SKILL.md').write_text(\n"
                "    os.environ['SEED_PLUGIN_NAME'] + '\\n' + os.environ['SEED_PLUGIN_ROOT'] + '\\n'\n"
                ")\n"
                "sys.exit(3 if os.environ.get('DEMO_FAIL') == '1' else 0)\n",
                encoding="utf-8",
            )
            self.point_seed_at(module, state)
            module.PLUGIN_ROOT = plugins
            manifest = json.dumps([{"name": "demo", "entrypoint": "seed_demo.py"}])
            with mock.patch.dict(os.environ, {"SEED_PLUGINS": manifest, "DEMO_FAIL": "1"}, clear=False):
                with self.assertRaisesRegex(SystemExit, "seed plugin demo failed"):
                    module.main()
            marker = json.loads(module.MARKER.read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "seeding")
            with mock.patch.dict(os.environ, {"SEED_PLUGINS": manifest, "DEMO_FAIL": "0"}, clear=False):
                module.main()
            marker = json.loads(module.MARKER.read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "ready")
            skill = (state / "hermes" / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(skill.splitlines(), ["demo", str(plugins / "demo")])
            for bad_manifest in (
                json.dumps([{"name": "Demo", "entrypoint": "seed_demo.py"}]),
                json.dumps([{"name": "demo", "entrypoint": "../seed_demo.py"}]),
                json.dumps([{"name": "demo", "entrypoint": "seed_demo.py", "extra": 1}]),
                "not json",
            ):
                with mock.patch.dict(os.environ, {"SEED_PLUGINS": bad_manifest}, clear=False):
                    with self.assertRaisesRegex(SystemExit, "invalid seed plugin"):
                        module.main()

    def extension_values_file(self, directory: str) -> str:
        values = Path(directory) / "extensions.yaml"
        values.write_text(
            "lifecycle:\n"
            "  seed:\n"
            "    plugins:\n"
            "      - name: demo\n"
            '        configMapName: "{{ .Release.Name }}-demo-seed"\n'
            "        entrypoint: seed_demo.py\n"
            "        identity: abc123\n"
            "        env:\n"
            "          - name: DEMO_ENDPOINT\n"
            '            value: "https://demo.{{ .Release.Namespace }}.svc.cluster.local:8001"\n'
            "        initContainers:\n"
            "          - name: stage-demo\n"
            '            image: "{{ .Values.artifacts.utilityImage }}"\n'
            '            command: ["true"]\n'
            "            volumeMounts:\n"
            "              - name: demo-staging\n"
            "                mountPath: /demo-staging\n"
            "        volumes:\n"
            "          - name: demo-staging\n"
            "            emptyDir: {}\n"
            "        volumeMounts:\n"
            "          - name: demo-staging\n"
            "            mountPath: /demo-staging\n"
            "            readOnly: true\n"
            "agent:\n"
            "  env:\n"
            "    DEMO_MODE: safe\n"
            "  envTemplate: |\n"
            '    DEMO_ENDPOINT: "https://demo.{{ .Release.Namespace }}.svc.cluster.local:8001"\n'
            "  extraStateMounts:\n"
            "    - mountPath: /sandbox/.hermes/skills/demo\n"
            "      subPath: hermes/skills/demo\n"
            "      readOnly: true\n"
            "    - mountPath: /chart-bin\n"
            "      subPath: hermes/bin\n"
            "      readOnly: true\n"
            "policy:\n"
            "  readOnlyPaths:\n"
            "    - /chart-bin\n"
            "  networkPoliciesTemplate: |\n"
            "    demo_api:\n"
            "      endpoints:\n"
            '        - host: "demo.{{ .Release.Namespace }}.svc.cluster.local"\n'
            "          port: 8001\n"
            "          protocol: rest\n"
            "          tls: skip\n"
            "          enforcement: enforce\n"
            "          rules:\n"
            '            - allow: { method: GET, path: "/**" }\n'
            "      binaries:\n"
            "        - { path: /chart-bin/oc }\n"
            "operatorClient:\n"
            "  enabled: true\n"
            "  skills:\n"
            "    - demo\n",
            encoding="utf-8",
        )
        return str(values)

    def test_extension_points_render_seed_plugins_mounts_policy_and_skills(self) -> None:
        baseline = self.run_helm("template", "kubernetes-deployer-test", str(CHART_DIR))
        with tempfile.TemporaryDirectory() as directory:
            rendered = self.run_helm(
                "template",
                "kubernetes-deployer-test",
                str(CHART_DIR),
                "-f",
                self.extension_values_file(directory),
            )
        seed = self.rendered_from_source(rendered, "kubernetes-deployer/templates/seed-job.yaml")
        self.assertIn('\\"name\\":\\"demo\\"', seed)
        self.assertIn('\\"entrypoint\\":\\"seed_demo.py\\"', seed)
        self.assertIn("name: DEMO_ENDPOINT", seed)
        self.assertIn('value: "https://demo.default.svc.cluster.local:8001"', seed)
        self.assertIn("name: plugin-demo", seed)
        self.assertIn("mountPath: /plugins/demo", seed)
        self.assertIn("name: kubernetes-deployer-test-demo-seed", seed)
        self.assertIn("name: stage-demo", seed)
        self.assertIn("image: docker.io/library/python:3.13.7-slim@sha256:", seed)
        self.assertIn("mountPath: /demo-staging", seed)
        config = self.bootstrap_config(rendered)
        mounts = {mount["mount_path"]: mount for mount in config["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]}
        self.assertEqual(mounts["/sandbox/.hermes/skills/demo"]["sub_path"], "hermes/skills/demo")
        self.assertTrue(mounts["/sandbox/.hermes/skills/demo"]["read_only"])
        self.assertEqual(mounts["/chart-bin"]["sub_path"], "hermes/bin")
        self.assertEqual(config["seedPlugins"], [{"name": "demo", "identity": "abc123"}])
        self.assertEqual(config["agentEnv"]["DEMO_MODE"], "safe")
        self.assertEqual(config["agentEnv"]["DEMO_ENDPOINT"], "https://demo.default.svc.cluster.local:8001")
        self.assertNotEqual(
            self.bootstrap_config(baseline)["labels"]["nemoclaw.nvidia.com/config-id"],
            config["labels"]["nemoclaw.nvidia.com/config-id"],
        )
        runtime = self.rendered_from_source(rendered, "kubernetes-deployer/templates/runtime-configmap.yaml")
        policy_text = runtime.split("  policy.yaml: |", 1)[1]
        self.assertIn("- /chart-bin", policy_text)
        self.assertIn("demo_api:", policy_text)
        self.assertIn("name: demo_api", policy_text)
        self.assertIn("host: demo.default.svc.cluster.local", policy_text)
        self.assertIn("managed_inference:", policy_text)
        client = self.rendered_from_source(rendered, "kubernetes-deployer/templates/operator-client.yaml")
        self.assertIn('value: "demo"', client)

    def test_extension_points_reject_overlapping_mounts_reserved_names_and_bad_paths(self) -> None:
        cases = (
            (
                (
                    "--set", "agent.extraStateMounts[0].mountPath=/sandbox/.hermes",
                    "--set", "agent.extraStateMounts[0].subPath=hermes",
                    "--set", "agent.extraStateMounts[0].readOnly=true",
                ),
                "overlaps a chart-managed mount",
            ),
            (
                (
                    "--set", "agent.extraStateMounts[0].mountPath=/sandbox/.hermes/skills/x",
                    "--set", "agent.extraStateMounts[0].subPath=../etc",
                    "--set", "agent.extraStateMounts[0].readOnly=true",
                ),
                "without . or .. segments",
            ),
            (
                (
                    "--set", "agent.extraStateMounts[0].mountPath=/sandbox/.hermes/skills/x",
                    "--set", "agent.extraStateMounts[0].subPath=workspace/x",
                    "--set", "agent.extraStateMounts[0].readOnly=true",
                ),
                "outside workspace/",
            ),
            (
                ("--set", "policy.networkPolicies.managed_inference.endpoints[0].host=x"),
                "collides with a base sandbox policy entry",
            ),
            (
                (
                    "--set", "lifecycle.seed.plugins[0].name=demo",
                    "--set", "lifecycle.seed.plugins[0].configMapName=demo-seed",
                    "--set", "lifecycle.seed.plugins[0].entrypoint=seed_demo.py",
                    "--set", "lifecycle.seed.plugins[0].env[0].name=SEED_STATE",
                    "--set", "lifecycle.seed.plugins[0].env[0].value=/elsewhere",
                ),
                "reserved seed variable",
            ),
            (
                (
                    "--set", "lifecycle.seed.plugins[0].name=demo",
                    "--set", "lifecycle.seed.plugins[0].configMapName=demo-seed",
                    "--set", "lifecycle.seed.plugins[0].entrypoint=seed_demo.py",
                    "--set", "lifecycle.seed.plugins[0].volumes[0].name=state",
                ),
                "collides with a chart-managed seed volume",
            ),
            (
                ("--set-string", "agent.env.MODEL_API_URL=https://example.test"),
                "NemoClaw rejects",
            ),
        )
        for overrides, expected in cases:
            with self.subTest(expected=expected):
                self.assert_helm_rejected(
                    "template",
                    "kubernetes-deployer-test",
                    str(CHART_DIR),
                    *overrides,
                    expected=expected,
                )

    def test_default_render_has_no_extension_resources(self) -> None:
        rendered = self.run_helm("template", "kubernetes-deployer-test", str(CHART_DIR))
        config = self.bootstrap_config(rendered)
        mounts = config["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
        self.assertEqual([mount["mount_path"] for mount in mounts], ["/sandbox/workspace", "/sandbox/.nemoclaw"])
        self.assertEqual(config["seedPlugins"], [])
        self.assertEqual(config["sandboxDesiredState"], "present")
        self.assertNotIn("mountPath: /plugins/", rendered)
        seed = self.rendered_from_source(rendered, "kubernetes-deployer/templates/seed-job.yaml")
        self.assertNotIn("initContainers", seed)
        self.assertIn('value: "[]"', seed)

    def test_sandbox_teardown_is_acknowledged_and_executable_without_a_local_cli(self) -> None:
        # Blocker: teardown must be runnable with helm and kubectl only. The
        # bootstrap Job, already authenticated to the chart-managed gateway,
        # deletes the sandbox when the release asks for desiredState=absent.
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "lifecycle.sandbox.desiredState=absent",
            expected="I_ACKNOWLEDGE_SANDBOX_DELETE",
        )
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "lifecycle.sandbox.desiredState=absent",
            "--set",
            "lifecycle.sandbox.dangerousAcknowledgement=I_ACKNOWLEDGE_SANDBOX_DELETE",
        )
        self.assertEqual(self.bootstrap_config(rendered)["sandboxDesiredState"], "absent")
        notes = CHART_DIR.joinpath("templates", "NOTES.txt").read_text(encoding="utf-8")
        self.assertIn("lifecycle.sandbox.desiredState=absent", notes)
        self.assertIn("helm uninstall", notes)
        self.assertNotIn("openshell sandbox get", notes)
        readme = CHART_DIR.joinpath("README.md").read_text(encoding="utf-8")
        teardown = readme.split("## Teardown", 1)[1]
        self.assertIn("lifecycle.sandbox.desiredState=absent", teardown)
        self.assertIn("I_ACKNOWLEDGE_SANDBOX_DELETE", teardown)
        self.assertIn("get sandbox", teardown)
        self.assertIn("helm uninstall", teardown)

        labels = {
            "nemoclaw.nvidia.com/release": "release",
            "nemoclaw.nvidia.com/image-id": "abc",
            "nemoclaw.nvidia.com/config-id": "current-config",
            "nemoclaw.nvidia.com/managed-by": "helm",
        }
        module = self.load_bootstrap_module(
            "nemoclaw_bootstrap_teardown",
            {"sandboxName": "release-her", "sandboxDesiredState": "absent", "labels": labels, "openshellMode": "managed"},
        )
        owned = dict(labels, **{"nemoclaw.nvidia.com/config-id": "stale-config"})
        calls: list[list[str]] = []
        gets = iter(
            [
                subprocess.CompletedProcess([], 0, stdout=json.dumps({"labels": owned}), stderr=""),
                subprocess.CompletedProcess([], 1, stdout="", stderr="sandbox not found"),
            ]
        )

        def fake_run(arguments, *, check=True, capture=False):  # noqa: ANN001 - mirrors bootstrap.run
            calls.append(list(arguments))
            if arguments[:2] == ["sandbox", "get"]:
                return next(gets)
            if arguments[:2] == ["sandbox", "delete"]:
                return subprocess.CompletedProcess([], 0, stdout="", stderr="")
            raise AssertionError(arguments)

        module.run = fake_run
        with mock.patch.object(module.time, "sleep"):
            module.delete_sandbox()
        self.assertEqual(
            calls,
            [
                ["sandbox", "get", "release-her", "--output", "json"],
                ["sandbox", "delete", "release-her"],
                ["sandbox", "get", "release-her", "--output", "json"],
            ],
        )
        # A same-named sandbox owned by something else is never deleted.
        foreign = dict(labels, **{"nemoclaw.nvidia.com/release": "someone-else"})
        module.run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps({"labels": foreign}), stderr=""))
        with self.assertRaisesRegex(SystemExit, "does not carry this release's identity labels"):
            module.delete_sandbox()
        module.run.assert_called_once()
        # Already absent is success, not an error.
        module.run = mock.Mock(return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="not found"))
        module.delete_sandbox()
        module.run.assert_called_once()
        # main() routes to the delete path and never reaches sandbox creation.
        with mock.patch.multiple(
            module,
            stage_client_tls=mock.DEFAULT,
            verify_issuer_discovery=mock.DEFAULT,
            configure_cli_authentication=mock.DEFAULT,
            wait_for_gateway=mock.DEFAULT,
            delete_sandbox=mock.DEFAULT,
            verify_existing_sandbox=mock.DEFAULT,
            create_sandbox=mock.DEFAULT,
        ) as patched:
            module.main()
        patched["delete_sandbox"].assert_called_once()
        patched["verify_existing_sandbox"].assert_not_called()
        patched["create_sandbox"].assert_not_called()

    def test_certgen_hook_prerequisites_do_not_outlive_the_hook(self) -> None:
        # Blocker: hook-created identity and RBAC must not survive uninstall.
        rendered = self.run_helm("template", "kubernetes-deployer-test", str(CHART_DIR))
        certgen = self.rendered_from_source(
            rendered,
            "kubernetes-deployer/charts/openshell/templates/certgen.yaml",
        )
        documents = [document for document in certgen.split("\n---\n") if "kind:" in document]
        kinds = sorted(re.search(r"(?m)^kind: (\S+)$", document).group(1) for document in documents)
        self.assertEqual(kinds, ["Job", "Role", "RoleBinding", "ServiceAccount"])
        for document in documents:
            self.assertIn("helm.sh/hook: pre-install,pre-upgrade", document)
            self.assertIn("helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded", document)
        notices = CHART_DIR.joinpath("THIRD-PARTY-NOTICES").read_text(encoding="utf-8")
        self.assertIn("templates/certgen.yaml", notices)

    def test_operator_client_activates_declared_skills(self) -> None:
        rendered = self.run_helm(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "operatorClient.enabled=true",
            "--set",
            "operatorClient.skills[0]=kubernetes-sre",
            "--set",
            "operatorClient.skills[1]=openshift-llm-deploy",
        )
        client = self.rendered_from_source(rendered, "kubernetes-deployer/templates/operator-client.yaml")
        self.assertIn('value: "kubernetes-sre,openshift-llm-deploy"', client)
        self.assert_helm_rejected(
            "template",
            "kubernetes-deployer-test",
            str(CHART_DIR),
            "--set",
            "operatorClient.enabled=true",
            "--set",
            "operatorClient.skills[0]=Not_A_Skill",
            expected="skills",
        )

    def test_catalog_metadata_marks_nemoclaw_not_applicable(self) -> None:
        # Blocker: the chart consumes a prebuilt managed image and never runs
        # the NemoClaw CLI or bootstrap, so the catalog row is N/A while the
        # provenance section keeps the pinned managed-image release.
        readme = CHART_DIR.joinpath("README.md").read_text(encoding="utf-8")
        self.assertIn("| NemoClaw | N/A |", readme)
        self.assertIn("| Harness | Hermes 0.19.0 |", readme)
        self.assertIn("| OpenShell | 0.0.116 |", readme)
        self.assertRegex(readme, r"NemoClaw `?v0\.0\.117`?")


if __name__ == "__main__":
    unittest.main()
