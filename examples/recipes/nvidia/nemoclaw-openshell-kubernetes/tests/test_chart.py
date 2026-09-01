# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render-level safety checks for the NemoClaw OpenShell chart."""

from pathlib import Path
import importlib.util
import json
import os
import re
import stat
import subprocess
import tempfile
import unittest


CHART_DIR = Path(__file__).resolve().parents[1]
INTERNAL_REGISTRY_MARKERS = (
    "localhost:32000",
    "urm.nvidia.com",
)


class ChartTest(unittest.TestCase):
    """Exercise the chart through Helm's public command-line interface."""

    @staticmethod
    def helm_arguments(*arguments: str) -> list[str]:
        """Render against the supported Agent Sandbox API during offline tests."""
        resolved = list(arguments)
        if arguments and arguments[0] == "template":
            resolved.extend(["--api-versions", "agents.x-k8s.io/v1alpha1"])
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
            "nemoclaw-openshell-kubernetes/templates/runtime-configmap.yaml",
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

    def test_default_render_excludes_disallowed_resources(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        rendered_lower = rendered.lower()

        self.assertNotIn("webui", rendered_lower)
        self.assertNotIn("cluster-admin", rendered_lower)
        for registry in INTERNAL_REGISTRY_MARKERS:
            self.assertNotIn(registry, rendered_lower)
        self.assertIsNone(
            re.search(r"(?m)^kind:\s*Sandbox\s*$", rendered),
            msg="the umbrella chart must not render a Sandbox resource directly",
        )

    def test_values_reject_unsupported_topology(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set-string",
            "openshell.supervisor.topology=sidecar",
            expected="/openshell/supervisor/topology",
        )

    def test_values_reject_mixed_gateway_modes(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set-string",
            "agent.model.apiKeySecretRef.name=",
            expected="/agent/model/apiKeySecretRef/name",
        )

    def test_plaintext_model_endpoint_requires_explicit_acknowledgement(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set-string",
            "agent.model.baseUrl=http://model.internal.example/v1",
            expected="agent.model.allowInsecureHttp",
        )

        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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
                    "nemoclaw-openshell-kubernetes-test",
                    str(CHART_DIR),
                    "--set-string",
                    override,
                    expected="/" + key.replace(".", "/"),
                )

    def test_default_runtime_images_use_multiarch_index_digests(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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

    def test_values_require_broad_access_acknowledgement(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
            "--set-string",
            "sre.rbac.mode=broad-no-delete",
            expected="sre.rbac.dangerousAcknowledgement",
        )

    def test_values_require_model_deletion_namespace(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.deletion.enabled=true",
            expected="sre.openshiftLlmDeploy.deletion.namespace",
        )

    def test_values_require_scc_binding_acknowledgement(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "platform.serviceAccountIssuerDiscovery.createPublicBinding=true",
            expected="I_ACKNOWLEDGE_PUBLIC_OIDC_DISCOVERY",
        )

    def test_acknowledged_issuer_discovery_binding_is_narrow(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "platform.serviceAccountIssuerDiscovery.createPublicBinding=true",
            "--set-string",
            "platform.serviceAccountIssuerDiscovery.dangerousAcknowledgement=I_ACKNOWLEDGE_PUBLIC_OIDC_DISCOVERY",
        )
        binding = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/serviceaccount-issuer-discovery.yaml",
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
            "nemoclaw-openshell-kubernetes-test",
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
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "openshell.server.enableUserNamespaces=true",
        )
        gateway = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/charts/openshell/templates/gateway-config.yaml",
        )
        self.assertIn("enable_user_namespaces = true", gateway)

    def test_managed_gateway_database_pvc_uses_configured_storage_class(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set-string",
            "persistence.storageClass=portable-rwo",
        )
        gateway_pvc = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/gateway-pvc.yaml",
        )

        self.assertIn(
            "name: openshell-data-nemoclaw-openshell-kubernetes-test-0",
            gateway_pvc,
        )
        self.assertIn('storageClassName: "portable-rwo"', gateway_pvc)
        self.assertIn("storage: 1Gi", gateway_pvc)

    def test_openshift_requires_scc_compatible_gateway_context(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "platform.openshift.enabled=true",
            "--api-versions",
            "security.openshift.io/v1",
            expected="openshell.podSecurityContext.fsGroup",
        )

    def test_openshift_profile_renders_only_acknowledged_scc_binding(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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

    def test_openshift_rejects_user_namespaces_with_chart_persistence(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--api-versions",
            "security.openshift.io/v1",
            "--values",
            str(CHART_DIR / "values-openshift.yaml"),
        )
        for source in (
            "nemoclaw-openshell-kubernetes/templates/seed-job.yaml",
            "nemoclaw-openshell-kubernetes/templates/bootstrap-job.yaml",
        ):
            with self.subTest(source=source):
                job = self.rendered_from_source(rendered, source)
                self.assertIn("openshift.io/required-scc: restricted-v2", job)
                self.assertIn(
                    "serviceAccountName: nemoclaw-openshell-kubernetes-test-lifecycle",
                    job,
                )

    def test_install_seed_binds_wait_for_first_consumer_storage_before_bootstrap(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        bootstrap = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/bootstrap-job.yaml",
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
            "nemoclaw-openshell-kubernetes/templates/seed-job.yaml",
        )
        self.assertIn("name: nemoclaw-openshell-kubernetes-test-seed-1", seed)
        self.assertNotIn("helm.sh/hook:", seed)
        self.assertIn('name: RELEASE_REVISION\n              value: "1"', seed)

    def test_normal_upgrade_does_not_remount_live_sandbox_pvc(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--is-upgrade",
        )
        self.assertNotIn(
            "nemoclaw-openshell-kubernetes/templates/seed-job.yaml",
            rendered,
        )
        bootstrap = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/bootstrap-job.yaml",
        )
        self.assertNotIn("name: wait-for-state-seed", bootstrap)
        self.assertNotIn("mountPath: /state", bootstrap)

    def test_seed_job_name_preserves_revision_with_maximal_fullname(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set-string",
            f"fullnameOverride={'a' * 63}",
        )
        seed = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/seed-job.yaml",
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
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--is-upgrade",
            "--set",
            "lifecycle.seed.runOnUpgrade=true",
            expected="I_ACKNOWLEDGE_SANDBOX_STOPPED",
        )

        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--is-upgrade",
            "--set",
            "lifecycle.seed.runOnUpgrade=true",
            "--set-string",
            "lifecycle.seed.dangerousAcknowledgement=I_ACKNOWLEDGE_SANDBOX_STOPPED",
        )
        self.assertIn("nemoclaw-openshell-kubernetes/templates/seed-job.yaml", rendered)
        bootstrap = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/bootstrap-job.yaml",
        )
        self.assertIn("name: wait-for-state-seed", bootstrap)
        self.assertIn("mountPath: /state", bootstrap)

    def test_managed_bootstrap_uses_projected_service_account_oidc(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        bootstrap = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/bootstrap-job.yaml",
        )
        gateway = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/charts/openshell/templates/gateway-config.yaml",
        )

        self.assertIn("automountServiceAccountToken: false", bootstrap)
        self.assertIn('audience: "openshell-cli"', bootstrap)
        self.assertIn("expirationSeconds: 900", bootstrap)
        self.assertIn("path: token", bootstrap)
        self.assertIn("mountPath: /var/run/secrets/openshell-bootstrap", bootstrap)
        self.assertIn("mountPath: /client-tls", bootstrap)
        self.assertNotIn("mountPath: /cli-config/openshell/gateways/", bootstrap)
        self.assertIn('issuer        = "https://kubernetes.default.svc"', gateway)
        self.assertIn('audience      = "openshell-cli"', gateway)
        self.assertIn('roles_claim   = "aud"', gateway)
        self.assertIn('admin_role    = "openshell-cli"', gateway)
        self.assertIn('user_role     = "openshell-cli"', gateway)
        self.assertNotIn("allow_unauthenticated_users = true", gateway)

    def test_gateway_ingress_is_release_scoped(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        policy = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/gateway-networkpolicy.yaml",
        )

        self.assertIn("app.kubernetes.io/name: openshell", policy)
        self.assertIn("app.kubernetes.io/instance: nemoclaw-openshell-kubernetes-test", policy)
        self.assertIn("app.kubernetes.io/component: bootstrap", policy)
        self.assertIn("key: agents.x-k8s.io/sandbox-name-hash", policy)
        self.assertIn("operator: Exists", policy)
        self.assertNotIn("openshell.ai/managed-by: openshell", policy)
        self.assertIn("port: 8080", policy)

    def test_managed_gateway_rejects_anonymous_bootstrap(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "openshell.server.auth.allowUnauthenticatedUsers=true",
            expected="allowUnauthenticatedUsers must remain false",
        )

    def test_existing_gateway_client_tls_does_not_mount_service_account_token(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-existing-gateway.yaml"),
        )
        bootstrap = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/bootstrap-job.yaml",
        )

        self.assertNotIn("openshell-bootstrap-token", bootstrap)
        self.assertNotIn("OPENSHELL_OIDC_ISSUER", bootstrap)

    def test_openshift_profile_requires_openshift_api(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--values",
            str(CHART_DIR / "values-openshift.yaml"),
            expected="security.openshift.io/v1",
        )

    def test_kubernetes_mode_rejects_openshift_scc_binding(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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
        self.assertIn('arguments.extend(["--", "/usr/local/bin/nemoclaw-start"])', bootstrap)
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
            module.PROXY_TOKEN_DESTINATION = state / "hermes" / ".sre-proxy-token"
            module.RELEASE = "test/release"
            module.RELEASE_REVISION = 1
            module.main()

            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o775)
            self.assertEqual(stat.S_IMODE((state / "hermes").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((state / "workspace").stat().st_mode), 0o700)

    def test_default_excludes_sre_delivery_and_rbac(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        config = self.bootstrap_config(rendered)
        mounts = config["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
        self.assertNotIn("KUBERNETES_SRE_API", rendered)
        self.assertNotIn("kubernetes-sre-SKILL.md", rendered)
        self.assertNotIn("app.kubernetes.io/component: sre-proxy", rendered)
        self.assertNotIn("sre-proxy-auth", rendered)
        self.assertEqual([mount["mount_path"] for mount in mounts], ["/sandbox/workspace"])
        self.assertNotIn("/sandbox/.hermes", [mount["mount_path"] for mount in mounts])

    def test_safe_sre_proxy_has_no_delete_or_secret_access(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
        )
        rbac = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/sre-rbac.yaml",
        )
        proxy = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/sre-proxy.yaml",
        )
        config = self.bootstrap_config(rendered)
        mounts = config["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
        mounts_by_path = {mount["mount_path"]: mount for mount in mounts}
        self.assertNotIn('resources: ["*"]', rbac)
        self.assertNotRegex(rbac, r"(?m)^\s*- secrets\s*$")
        self.assertNotRegex(rbac, r'(?m)^\s*verbs:.*"delete"')
        self.assertIn('resources: ["deployments/scale", "statefulsets/scale"]', rbac)
        self.assertRegex(
            rbac,
            r'(?s)resources: \["deployments/scale", "statefulsets/scale"\].*?verbs: \["get", "patch", "update"\]',
        )
        self.assertIn(
            'resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]\n'
            '    verbs: ["get", "list", "watch"]',
            rbac,
        )
        self.assertIn("name: PROXY_ALLOWED_METHODS", proxy)
        self.assertIn("value: \"GET,PATCH\"", proxy)
        self.assertNotIn("GET,DELETE", proxy)
        self.assertIn("kubernetes-sre-SKILL.md", rendered)
        self.assertIn("/sandbox/.hermes/skills/kubernetes-sre", mounts_by_path)
        self.assertEqual(
            mounts_by_path["/sandbox/.hermes/skills/kubernetes-sre"]["sub_path"],
            "hermes/skills/kubernetes-sre",
        )
        self.assertIn("/sandbox/.hermes/.sre-proxy-token", mounts_by_path)
        self.assertTrue(mounts_by_path["/sandbox/.hermes/.sre-proxy-token"]["read_only"])
        self.assertNotIn("/sandbox/.hermes", mounts_by_path)

    def test_broad_sre_is_explicit_and_still_has_no_delete_verb(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
            "--set-string",
            "sre.rbac.mode=broad-no-delete",
            "--set-string",
            "sre.rbac.dangerousAcknowledgement=I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE",
        )
        rbac = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/sre-rbac.yaml",
        )
        self.assertIn('resources: ["*"]', rbac)
        self.assertIn('verbs: ["get", "list", "watch", "create", "patch", "update"]', rbac)
        self.assertNotRegex(rbac, r'(?m)^\s*verbs:.*"delete"')

    def test_model_delete_is_limited_to_acknowledged_namespace(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.deletion.enabled=true",
            "--set-string",
            "sre.openshiftLlmDeploy.deletion.namespace=models-eval",
            "--set-string",
            "sre.openshiftLlmDeploy.deletion.dangerousAcknowledgement=I_ACKNOWLEDGE_NAMESPACE_MODEL_DELETE",
            "--set-string",
            "sre.openshiftLlmDeploy.deletion.allowedResources[0].apiGroup=serving.kserve.io",
            "--set-string",
            "sre.openshiftLlmDeploy.deletion.allowedResources[0].resource=inferenceservices",
            "--set-string",
            "sre.openshiftLlmDeploy.deletion.allowedResources[0].name=owned-model",
        )
        rbac = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/model-delete-rbac.yaml",
        )
        self.assertIn("namespace: models-eval", rbac)
        self.assertIn('resources: ["inferenceservices"]', rbac)
        self.assertIn('resourceNames: ["owned-model"]', rbac)
        self.assertIn('verbs: ["delete"]', rbac)
        self.assertNotIn("kind: ClusterRole", rbac)
        self.assertNotRegex(rbac, r"(?m)^\s*- persistentvolumeclaims\s*$")
        self.assertNotRegex(rbac, r"(?m)^\s*- secrets\s*$")
        config = self.bootstrap_config(rendered)
        mounts = config["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
        mounts_by_path = {mount["mount_path"]: mount for mount in mounts}
        self.assertIn("/sandbox/.hermes/skills/kubernetes-sre", mounts_by_path)
        self.assertIn("/sandbox/.hermes/skills/openshift-llm-deploy", mounts_by_path)
        self.assertIn("/sandbox/.hermes/.sre-proxy-token", mounts_by_path)

    def test_model_delete_requires_exact_resource_allowlist(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.deletion.enabled=true",
            "--set-string",
            "sre.openshiftLlmDeploy.deletion.namespace=models-eval",
            "--set-string",
            "sre.openshiftLlmDeploy.deletion.dangerousAcknowledgement=I_ACKNOWLEDGE_NAMESPACE_MODEL_DELETE",
            expected="allowedResources",
        )

    def test_existing_gateway_rejects_plaintext_endpoint(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        changed = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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

    def test_sre_proxy_auth_secret_has_a_kubernetes_api_header(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
        )
        secret = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/proxy-auth-secret.yaml",
        )
        self.assertRegex(secret, r"(?m)^apiVersion: v1$")
        self.assertRegex(secret, r"(?m)^kind: Secret$")

    def test_sre_proxy_uses_bearer_authenticated_forwarder(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
        )
        proxy = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/sre-proxy.yaml",
        )
        self.assertIn("api_proxy.py", proxy)
        self.assertIn("PROXY_CLIENT_TOKEN_FILE", proxy)
        self.assertNotIn("kubectl\n", proxy)
        self.assertNotIn("--accept-hosts=", proxy)
        self.assertIn("kind: Secret", rendered)

    def test_api_proxy_rejects_missing_token_and_unsafe_target(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "api_proxy.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_api_proxy", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "token"
            secret.write_text("expected-token\n", encoding="utf-8")
            self.assertTrue(module.is_authorized("Bearer expected-token", secret))
            self.assertFalse(module.is_authorized("", secret))
            self.assertFalse(module.is_authorized("Bearer wrong", secret))
        self.assertEqual(
            module.validate_request_target("/apis/apps/v1/namespaces/demo/deployments"),
            "/apis/apps/v1/namespaces/demo/deployments",
        )
        for target in ("http://attacker.example/", "//attacker.example/api", "/apis/../secrets"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    module.validate_request_target(target)

    def test_existing_gateway_mode_does_not_install_openshell_subchart(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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
            main_body.index("reconcile_provider()"),
        )

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
            "nemoclaw-openshell-kubernetes/templates/serviceaccount-issuer-discovery.yaml",
        )
        binding_b = self.rendered_from_source(
            rendered_b,
            "nemoclaw-openshell-kubernetes/templates/serviceaccount-issuer-discovery.yaml",
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
                    "nemoclaw-openshell-kubernetes-test",
                    str(CHART_DIR),
                    "--set-string",
                    override,
                    expected=expected,
                )


if __name__ == "__main__":
    unittest.main()
