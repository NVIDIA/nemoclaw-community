# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render-level safety checks for the NemoClaw OpenShell chart."""

from pathlib import Path
import base64
import hashlib
import importlib.util
import io
import json
import lzma
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import time
import unittest
from unittest import mock


CHART_DIR = Path(__file__).resolve().parents[1]
INTERNAL_REGISTRY_MARKERS = (
    "localhost:32000",
    "urm.nvidia.com",
)

ALLOWED_SRE_BUNDLE_ROOTS = {
    "devops",
    "infrastructure",
    "kubernetes-sre",
    "openshift-llm-deploy",
}
REQUIRED_SRE_BUNDLE_FILES = {
    "devops/SKILL.md",
    "infrastructure/SKILL.md",
    "infrastructure/sre/SKILL.md",
    "kubernetes-sre/SKILL.md",
    "openshift-llm-deploy/SKILL.md",
}
RUNTIME_SUPPORT_DIRECTORIES = {
    "scripts",
    "templates",
    "tools",
    "workflows",
    "resources",
}
LEGAL_FILENAMES = {
    "LICENSE",
    "LICENSE.md",
    "NOTICE",
    "NOTICE.md",
    "SOURCE_NOTICES.md",
}
EXCLUDED_SRE_BUNDLE_PREFIXES = {
    "devops/automation/manage-skills/",
    "infrastructure/openshift/",
}
RUNTIME_SAFETY_MARKER = "<!-- nemoclaw-runtime-safety-v1 -->"


def reviewed_skill_source_files() -> set[str]:
    source = CHART_DIR / "files" / "skills"
    reviewed: set[str] = set()
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        name = relative.as_posix()
        if not path.is_file() or not relative.parts:
            continue
        if relative.parts[0] not in ALLOWED_SRE_BUNDLE_ROOTS:
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if name.endswith(".pyc") or any(
            name.startswith(prefix) for prefix in EXCLUDED_SRE_BUNDLE_PREFIXES
        ):
            continue
        lowered_parts = {part.lower() for part in relative.parts}
        if not (
            relative.name == "SKILL.md"
            or relative.name in LEGAL_FILENAMES
            or lowered_parts.intersection(RUNTIME_SUPPORT_DIRECTORIES)
            or (
                relative.parts[0] == "openshift-llm-deploy"
                and "references" in lowered_parts
            )
        ):
            continue
        reviewed.add(name)
    return reviewed


EXPECTED_SRE_BUNDLE_FILES = reviewed_skill_source_files()


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

    @staticmethod
    def write_test_skill_bundle(
        destination: Path,
        *,
        files: dict[str, bytes] | None = None,
        extra_members: list[tarfile.TarInfo] | None = None,
        corrupt_manifest: bool = False,
    ) -> tuple[str, str, str]:
        """Create a one-part test bundle and return its trust metadata."""
        if destination.name != "sre-skills.part-000":
            raise AssertionError("test bundle part must use the production naming contract")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payloads = files or {
            name: f"fixture for {name}\n".encode("utf-8")
            for name in EXPECTED_SRE_BUNDLE_FILES
        }
        manifest_lines = [
            f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}"
            for name in sorted(payloads)
        ]
        if corrupt_manifest:
            manifest_lines[0] = "0" * 64 + manifest_lines[0][64:]
        manifest = ("\n".join(manifest_lines) + "\n").encode("utf-8")
        uncompressed = io.BytesIO()
        with tarfile.open(fileobj=uncompressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name in sorted(payloads):
                info = tarfile.TarInfo(name)
                info.size = len(payloads[name])
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(payloads[name]))
            info = tarfile.TarInfo("MANIFEST.sha256")
            info.size = len(manifest)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(manifest))
            for member in extra_members or []:
                archive.addfile(member, io.BytesIO(b"payload") if member.isfile() else None)
        destination.write_bytes(
            lzma.compress(
                uncompressed.getvalue(),
                format=lzma.FORMAT_XZ,
                preset=9 | lzma.PRESET_EXTREME,
            )
        )
        payload = destination.read_bytes()
        parts_json = json.dumps(
            {
                "parts": [
                    {
                        "name": destination.name,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "size": len(payload),
                    }
                ],
                "version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return (
            hashlib.sha256(payload).hexdigest(),
            hashlib.sha256(manifest).hexdigest(),
            parts_json,
        )

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
            "--set-string",
            "sre.rbac.mode=broad-no-delete",
            "--set-string",
            "sre.rbac.dangerousAcknowledgement=I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE",
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

    def test_openshift_profile_isolates_gateway_uid_from_sandbox_uid(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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
            "nemoclaw-openshell-kubernetes/charts/openshell/templates/statefulset.yaml",
        )
        gateway_config = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/charts/openshell/templates/gateway-config.yaml",
        )
        seed = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/seed-job.yaml",
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
            "nemoclaw-openshell-kubernetes-test",
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
            "nemoclaw-openshell-kubernetes-test",
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
        self.assertIn("restartPolicy: Never", seed)
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
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        rbac = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/lifecycle-tokenrequest-rbac.yaml",
        )

        self.assertIn('resources: ["serviceaccounts/token"]', rbac)
        self.assertIn(
            'resourceNames: ["nemoclaw-openshell-kubernetes-test-lifecycle"]',
            rbac,
        )
        self.assertIn('verbs: ["create"]', rbac)
        self.assertNotIn("ClusterRole", rbac)

    def test_operator_client_is_opt_in(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        self.assertNotIn("templates/operator-client.yaml", rendered)
        self.assertNotIn("app.kubernetes.io/component: operator-client", rendered)

    def test_templates_emit_only_valid_resource_manifests(self) -> None:
        rendered_profiles = {
            "defaults": self.run_helm(
                "template",
                "nemoclaw-openshell-kubernetes-test",
                str(CHART_DIR),
            ),
            "operator-sre": self.run_helm(
                "template",
                "nemoclaw-openshell-kubernetes-test",
                str(CHART_DIR),
                "--set",
                "operatorClient.enabled=true",
                "--set",
                "sre.enabled=true",
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
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "operatorClient.enabled=true",
            "--set",
            "sre.enabled=true",
        )
        client = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/operator-client.yaml",
        )
        gateway_policy = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/gateway-networkpolicy.yaml",
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
            "system:serviceaccount:default:nemoclaw-openshell-kubernetes-test-operator-client",
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
            "nemoclaw-openshell-kubernetes/templates/operator-client.yaml",
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
            "nemoclaw-openshell-kubernetes-test",
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
                "nemoclaw-openshell-kubernetes-test",
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
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        gateway = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/charts/openshell/templates/statefulset.yaml",
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
            module.PROXY_TOKEN_DESTINATION = state / "hermes" / ".sre-proxy-token"
            module.RELEASE = "test/release"
            module.RELEASE_REVISION = 1
            module.main()

            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o775)
            self.assertEqual(stat.S_IMODE((state / "hermes").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((state / "workspace").stat().st_mode), 0o700)

    def test_seed_refuses_unowned_existing_skill_before_claiming_pvc(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "seed.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_seed_unowned", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        with mock.patch.dict(
            os.environ,
            {
                "RELEASE_ID": "test/release",
                "RELEASE_REVISION": "1",
                "SRE_ENABLED": "false",
                "OPENSHIFT_LLM_DEPLOY_ENABLED": "false",
                "MODEL_DELETE_ENABLED": "false",
                "METRICS_ENABLED": "false",
            },
            clear=False,
        ):
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            skill = state / "hermes" / "skills" / "kubernetes-sre" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("operator-owned\n", encoding="utf-8")

            module.STATE = state
            module.MARKER = state / ".nemoclaw-helm-owner.json"
            module.PROXY_TOKEN_DESTINATION = state / "hermes" / ".sre-proxy-token"
            module.SRE_KUBECONFIG_DESTINATION = state / "hermes" / "sre-kubeconfig"
            module.MODEL_DELETE_KUBECONFIG_DESTINATION = (
                state / "hermes" / "model-delete-kubeconfig"
            )
            module.METRICS_KUBECONFIG_DESTINATION = state / "hermes" / "metrics-kubeconfig"
            module.RELEASE = "test/release"
            module.RELEASE_REVISION = 1

            with self.assertRaisesRegex(SystemExit, "refusing to replace unowned"):
                module.main()

            self.assertEqual(skill.read_text(encoding="utf-8"), "operator-owned\n")
            self.assertFalse(module.MARKER.exists())

    def test_seed_accepts_kubernetes_secret_projection_symlink(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "seed.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_seed_symlink", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        os.environ["RELEASE_ID"] = "test/release"
        os.environ["RELEASE_REVISION"] = "1"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            hermes = state / "hermes"
            state.mkdir()
            hermes.mkdir()
            projected_data = root / "..2026_09_01_20_34_00.000000000"
            projected_data.write_bytes(b"proxy-token")
            projected_token = root / "token"
            projected_token.symlink_to(projected_data.name)

            module.STATE = state
            module.MARKER = state / ".nemoclaw-helm-owner.json"
            module.PROXY_TOKEN_SOURCE = projected_token
            module.PROXY_TOKEN_DESTINATION = hermes / ".sre-proxy-token"
            module.RELEASE = "test/release"
            module.reconcile_proxy_token(True)

            self.assertEqual(module.PROXY_TOKEN_DESTINATION.read_bytes(), b"proxy-token")
            self.assertEqual(stat.S_IMODE(module.PROXY_TOKEN_DESTINATION.stat().st_mode), 0o600)

    def test_seed_embeds_runtime_token_in_private_proxy_kubeconfig(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "seed.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_seed_kubeconfig", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        os.environ["RELEASE_ID"] = "test/release"
        os.environ["RELEASE_REVISION"] = "1"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            hermes = state / "hermes"
            hermes.mkdir(parents=True)
            destination = hermes / "sre-kubeconfig"
            module.STATE = state
            module.MARKER = state / ".nemoclaw-helm-owner.json"
            module.RELEASE = "test/release"

            module.write_kubeconfig(
                destination,
                "https://sre-proxy.test.svc.cluster.local:8443",
                "test",
                "runtime-proxy-token",
                b"test-proxy-ca",
            )

            content = destination.read_text(encoding="utf-8")
            self.assertIn("    certificate-authority-data: dGVzdC1wcm94eS1jYQ==", content)
            self.assertNotIn("insecure-skip-tls-verify", content)
            self.assertIn('    token: "runtime-proxy-token"', content)
            self.assertNotIn("tokenFile:", content)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_default_excludes_sre_delivery_and_rbac(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )
        config = self.bootstrap_config(rendered)
        mounts = config["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
        self.assertNotIn("KUBERNETES_SRE_ENDPOINT", config["agentEnv"])
        self.assertNotIn("SRE_KUBECONFIG", config["agentEnv"])
        self.assertNotIn("templates/sre-skills-bundle.yaml", rendered)
        self.assertNotIn("stage-sre-cli", rendered)
        self.assertNotIn("app.kubernetes.io/component: sre-proxy", rendered)
        self.assertNotIn("sre-proxy-auth", rendered)
        self.assertNotIn("authenticated-internal-api-proxy-tls", rendered)
        self.assertEqual([mount["mount_path"] for mount in mounts], ["/sandbox/workspace"])
        self.assertNotIn("/sandbox/.hermes", [mount["mount_path"] for mount in mounts])

    def test_sre_renders_verified_bundle_cli_and_proxy_kubeconfig(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
        )
        bundle = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/sre-skills-bundle.yaml",
        )
        seed = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/seed-job.yaml",
        )
        runtime = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/runtime-configmap.yaml",
        )
        config = self.bootstrap_config(rendered)
        mounts = {
            mount["mount_path"]: mount
            for mount in config["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
        }

        self.assertIn("binaryData:", bundle)
        self.assertIn("sre-skills.part-000:", bundle)
        self.assertIn("sre-skills.part-001:", bundle)
        self.assertIn("nemoclaw.nvidia.com/archive-sha256:", bundle)
        self.assertIn("nemoclaw.nvidia.com/manifest-sha256:", bundle)
        self.assertIn("nemoclaw.nvidia.com/part-sha256:", bundle)
        self.assertIn("name: stage-sre-cli", seed)
        self.assertIn(
            "quay.io/openshift/origin-cli@sha256:ebd858bafa7fe3bf04eda2753d47f74be9608c867f41567cea4af1b1b4189fac",
            seed,
        )
        self.assertIn("name: SRE_BUNDLE_SHA256", seed)
        self.assertIn("name: SRE_BUNDLE_MANIFEST_SHA256", seed)
        self.assertIn("name: SRE_BUNDLE_PARTS_JSON", seed)
        self.assertIn("projected:", seed)
        self.assertIn("mountPath: /skills-bundle", seed)
        self.assertIn("mountPath: /cli-staging", seed)
        self.assertIn("mountPath: /proxy-tls-ca", seed)
        self.assertIn("path: ca.crt", seed)
        self.assertIn("https://", seed)
        self.assertNotIn("http://", seed)
        self.assertIn("SRE_KUBECONFIG", config["agentEnv"])
        self.assertRegex(
            runtime,
            r"(?s)kubernetes_sre:.*?protocol: rest.*?tls: skip",
        )
        self.assertEqual(
            config["sreBundleSha256"],
            (CHART_DIR / "files" / "sre-skills.tar.xz.sha256")
            .read_text(encoding="utf-8")
            .strip(),
        )
        self.assertIn("/chart-bin", mounts)
        self.assertTrue(mounts["/chart-bin"]["read_only"])
        self.assertIn("/sandbox/.hermes/sre-kubeconfig", mounts)
        self.assertIn("/sandbox/.hermes/skills/devops", mounts)
        self.assertIn("/sandbox/.hermes/skills/infrastructure", mounts)
        self.assertNotIn("/sandbox/.hermes/skills/openshift-llm-deploy", mounts)
        runtime_template = (CHART_DIR / "templates" / "runtime-configmap.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn('"sreBundleSha256" $sreBundleDigest', runtime_template)
        self.assertIn(
            '"sreBundleManifestSha256" $sreBundleManifestDigest',
            runtime_template,
        )

    def test_full_model_skill_requires_broad_no_delete_mode(self) -> None:
        self.assert_helm_rejected(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.enabled=true",
            expected="sre.rbac.mode=broad-no-delete",
        )

        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.enabled=true",
            "--set-string",
            "sre.rbac.mode=broad-no-delete",
            "--set-string",
            "sre.rbac.dangerousAcknowledgement=I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE",
        )
        config = self.bootstrap_config(rendered)
        mounts = {
            mount["mount_path"]: mount
            for mount in config["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
        }
        self.assertIn("/sandbox/.hermes/skills/openshift-llm-deploy", mounts)
        self.assertEqual(
            config["agentEnv"]["KUBECONFIG"],
            "/sandbox/.hermes/sre-kubeconfig",
        )

    def test_full_model_skill_keeps_secret_references_out_of_process_environment(self) -> None:
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.enabled=true",
            "--set-string",
            "sre.rbac.mode=broad-no-delete",
            "--set-string",
            "sre.rbac.dangerousAcknowledgement=I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE",
        )
        config = self.bootstrap_config(rendered)

        self.assertNotIn("OPENSHIFT_LLM_HF_SECRET_NAME", config["agentEnv"])
        self.assertNotIn("OPENSHIFT_LLM_HF_SECRET_KEY", config["agentEnv"])
        seed = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/seed-job.yaml",
        )
        self.assertIn("name: HF_TOKEN_INTAKE_JSON", seed)

    def test_committed_sre_bundle_has_exact_reviewed_contents_and_manifest(self) -> None:
        parts_index_file = CHART_DIR / "files" / "sre-skills.parts.json"
        digest_file = CHART_DIR / "files" / "sre-skills.tar.xz.sha256"
        manifest_digest_file = CHART_DIR / "files" / "sre-skills.manifest.sha256"
        self.assertTrue(parts_index_file.is_file(), "committed SRE parts index is missing")
        self.assertTrue(digest_file.is_file(), "committed SRE archive digest is missing")
        self.assertTrue(
            manifest_digest_file.is_file(),
            "committed SRE manifest digest is missing",
        )
        self.assertTrue(REQUIRED_SRE_BUNDLE_FILES.issubset(EXPECTED_SRE_BUNDLE_FILES))
        parts_index = json.loads(parts_index_file.read_text(encoding="utf-8"))
        self.assertEqual(set(parts_index), {"parts", "version"})
        self.assertEqual(parts_index["version"], 1)
        self.assertGreater(len(parts_index["parts"]), 1)
        bundle_payloads: list[bytes] = []
        for index, part in enumerate(parts_index["parts"]):
            self.assertEqual(part["name"], f"sre-skills.part-{index:03d}")
            payload = CHART_DIR.joinpath("files", part["name"]).read_bytes()
            self.assertEqual(len(payload), part["size"])
            self.assertLessEqual(len(payload), 500_000)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), part["sha256"])
            bundle_payloads.append(payload)
        bundle = b"".join(bundle_payloads)
        self.assertEqual(
            hashlib.sha256(bundle).hexdigest(),
            digest_file.read_text(encoding="utf-8").strip(),
        )
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:xz") as archive:
            members = archive.getmembers()
            files = {member.name for member in members if member.isfile()}
            self.assertTrue(all(member.isfile() for member in members))
            self.assertTrue(all(not member.issym() and not member.islnk() for member in members))
            self.assertEqual(files, EXPECTED_SRE_BUNDLE_FILES | {"MANIFEST.sha256"})
            manifest = archive.extractfile("MANIFEST.sha256")
            self.assertIsNotNone(manifest)
            manifest_payload = manifest.read()
            self.assertEqual(
                hashlib.sha256(manifest_payload).hexdigest(),
                manifest_digest_file.read_text(encoding="utf-8").strip(),
            )
            entries = manifest_payload.decode("utf-8").splitlines()
            self.assertEqual(
                {line.split("  ", 1)[1] for line in entries},
                EXPECTED_SRE_BUNDLE_FILES,
            )
            for line in entries:
                expected, name = line.split("  ", 1)
                payload = archive.extractfile(name)
                self.assertIsNotNone(payload)
                self.assertEqual(hashlib.sha256(payload.read()).hexdigest(), expected)
        self.assertIn("devops/SKILL.md", EXPECTED_SRE_BUNDLE_FILES)
        self.assertIn("infrastructure/SKILL.md", EXPECTED_SRE_BUNDLE_FILES)
        self.assertIn("infrastructure/sre/SKILL.md", EXPECTED_SRE_BUNDLE_FILES)
        source_skill_files = {
            path.relative_to(CHART_DIR / "files" / "skills").as_posix()
            for root in (
                CHART_DIR / "files" / "skills" / "devops",
                CHART_DIR / "files" / "skills" / "infrastructure",
            )
            for path in root.rglob("SKILL.md")
            if not any(
                path.relative_to(CHART_DIR / "files" / "skills")
                .as_posix()
                .startswith(prefix)
                for prefix in EXCLUDED_SRE_BUNDLE_PREFIXES
            )
        }
        self.assertTrue(source_skill_files.issubset(files))
        self.assertTrue(
            any(name.startswith("devops/") and "/scripts/" in name for name in files)
        )
        self.assertTrue(
            any(name.startswith("infrastructure/") and "/templates/" in name for name in files)
        )
        self.assertNotIn(
            "infrastructure/kubernetes/kubernetes-skill/docs/package-lock.json",
            files,
        )
        self.assertNotIn("devops/automation/manage-skills/SKILL.md", files)
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:xz") as archive:
            for name in source_skill_files | {
                "kubernetes-sre/SKILL.md",
                "openshift-llm-deploy/SKILL.md",
            }:
                payload = archive.extractfile(name)
                self.assertIsNotNone(payload)
                skill_text = payload.read().decode("utf-8")
                self.assertIn(RUNTIME_SAFETY_MARKER, skill_text)
                self.assertIn("Never build or publish custom images", skill_text)
                self.assertIn("never use mutable image tags", skill_text)
        self.assertFalse(any("skillspector" in name.lower() for name in files))
        self.assertFalse(any("managed-skill-install" in name for name in files))
        self.assertFalse(any(name.startswith("infrastructure/openshift/") for name in files))
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in files))

    def test_bundled_skills_have_valid_unique_hermes_metadata(self) -> None:
        skills = CHART_DIR / "files" / "skills"
        names: dict[str, Path] = {}
        skill_files = sorted(
            path
            for root in (skills / "devops", skills / "infrastructure")
            for path in root.rglob("SKILL.md")
        )
        self.assertGreater(len(skill_files), 100)
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            frontmatter = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
            self.assertIsNotNone(frontmatter, f"missing frontmatter: {path}")
            name_match = re.search(
                r"(?m)^name:\s*([a-z][a-z0-9_-]*)\s*$",
                frontmatter.group(1),
            )
            description_match = re.search(r"(?m)^description:\s*\S", frontmatter.group(1))
            self.assertIsNotNone(name_match, f"invalid skill name: {path}")
            self.assertIsNotNone(description_match, f"missing skill description: {path}")
            name = name_match.group(1)
            self.assertNotIn(name, names, f"duplicate skill name in {path} and {names.get(name)}")
            names[name] = path

    def test_seed_validates_bundle_and_rejects_unsafe_archives(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "seed.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_seed_bundle", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        os.environ["RELEASE_ID"] = "test/release"
        os.environ["RELEASE_REVISION"] = "1"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, "load_sre_bundle"), "seed bundle loader is missing")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid_root = root / "valid"
            valid = valid_root / "sre-skills.part-000"
            digest, manifest_digest, parts_json = self.write_test_skill_bundle(valid)
            loaded = module.load_sre_bundle(
                valid_root,
                digest,
                manifest_digest,
                parts_json,
            )
            self.assertEqual(set(loaded), EXPECTED_SRE_BUNDLE_FILES)

            projection = root / "projection"
            revision = projection / "..2026_09_02_17_00_00.000000000"
            revision.mkdir(parents=True)
            projected_payload = revision / "sre-skills.part-000"
            projected_payload.write_bytes(valid.read_bytes())
            (projection / "..data").symlink_to(revision.name)
            projected_key = projection / "sre-skills.part-000"
            projected_key.symlink_to("..data/sre-skills.part-000")
            projected = module.load_sre_bundle(
                projection,
                digest,
                manifest_digest,
                parts_json,
            )
            self.assertEqual(set(projected), EXPECTED_SRE_BUNDLE_FILES)

            escaping_root = root / "escaping"
            escaping_root.mkdir()
            (escaping_root / "sre-skills.part-000").symlink_to(valid)
            with self.assertRaisesRegex(SystemExit, "invalid SRE bundle part"):
                module.load_sre_bundle(
                    escaping_root,
                    digest,
                    manifest_digest,
                    parts_json,
                )

            with self.assertRaisesRegex(SystemExit, "archive SHA-256 mismatch"):
                module.load_sre_bundle(
                    valid_root,
                    "0" * 64,
                    manifest_digest,
                    parts_json,
                )

            corrupt_root = root / "corrupt"
            corrupt = corrupt_root / "sre-skills.part-000"
            corrupt_digest, corrupt_manifest_digest, corrupt_parts_json = self.write_test_skill_bundle(
                corrupt,
                corrupt_manifest=True,
            )
            with self.assertRaisesRegex(SystemExit, "manifest SHA-256 mismatch"):
                module.load_sre_bundle(
                    corrupt_root,
                    corrupt_digest,
                    corrupt_manifest_digest,
                    corrupt_parts_json,
                )

            traversal_root = root / "traversal"
            traversal = traversal_root / "sre-skills.part-000"
            traversal_member = tarfile.TarInfo("../escape")
            traversal_member.size = len(b"payload")
            traversal_digest, traversal_manifest_digest, traversal_parts_json = self.write_test_skill_bundle(
                traversal,
                extra_members=[traversal_member],
            )
            with self.assertRaisesRegex(SystemExit, "unsafe archive member"):
                module.load_sre_bundle(
                    traversal_root,
                    traversal_digest,
                    traversal_manifest_digest,
                    traversal_parts_json,
                )

            linked_root = root / "linked"
            linked = linked_root / "sre-skills.part-000"
            link_member = tarfile.TarInfo("openshift-llm-deploy/scripts/link")
            link_member.type = tarfile.SYMTYPE
            link_member.linkname = "/etc/passwd"
            link_digest, link_manifest_digest, link_parts_json = self.write_test_skill_bundle(
                linked,
                extra_members=[link_member],
            )
            with self.assertRaisesRegex(SystemExit, "unsafe archive member"):
                module.load_sre_bundle(
                    linked_root,
                    link_digest,
                    link_manifest_digest,
                    link_parts_json,
                )

    def test_seed_installs_and_replaces_read_only_skill_directories(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "seed.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_seed_reconcile", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        os.environ["RELEASE_ID"] = "test/release"
        os.environ["RELEASE_REVISION"] = "1"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            skills = state / "hermes" / "skills"
            skills.mkdir(parents=True)
            module.STATE = state
            module.MARKER = state / ".nemoclaw-helm-owner.json"
            module.RELEASE = "test/release"
            module.RELEASE_REVISION = 1
            payloads = {
                name: f"payload:{name}\n".encode("utf-8")
                for name in EXPECTED_SRE_BUNDLE_FILES
            }

            module.reconcile_sre_skills(True, False, payloads)
            installed = skills / "kubernetes-sre" / "SKILL.md"
            self.assertTrue(installed.is_file())
            self.assertEqual(stat.S_IMODE(installed.parent.stat().st_mode), 0o555)
            for name in ("devops", "infrastructure"):
                root = skills / name
                self.assertTrue(root.joinpath("SKILL.md").is_file())
                self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o555)

            module.write_owner_marker()
            payloads["kubernetes-sre/SKILL.md"] = b"updated\n"
            module.reconcile_sre_skills(True, False, payloads)
            self.assertEqual(installed.read_bytes(), b"updated\n")
            self.assertEqual(stat.S_IMODE(installed.parent.stat().st_mode), 0o555)

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
        tls_secret = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/proxy-tls-secret.yaml",
        )
        network_policy = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/networkpolicy.yaml",
        )
        config = self.bootstrap_config(rendered)
        proxy_script = (CHART_DIR / "files" / "scripts" / "api_proxy.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("KUBERNETES_SRE_ENDPOINT", config["agentEnv"])
        self.assertNotIn("KUBERNETES_SRE_API", config["agentEnv"])
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
        self.assertIn("name: PROXY_MAX_REQUEST_BYTES\n              value: \"10485760\"", proxy)
        self.assertIn("name: PROXY_MAX_RESPONSE_BYTES\n              value: \"33554432\"", proxy)
        self.assertIn("name: PROXY_TLS_CERT_FILE", proxy)
        self.assertIn("value: /proxy-tls/tls.crt", proxy)
        self.assertIn("name: PROXY_TLS_KEY_FILE", proxy)
        self.assertIn("value: /proxy-tls/tls.key", proxy)
        self.assertIn("mountPath: /proxy-tls", proxy)
        self.assertIn("type: kubernetes.io/tls", tls_secret)
        self.assertIn('"ca.crt":', tls_secret)
        self.assertIn("ssl.PROTOCOL_TLS_SERVER", proxy_script)
        self.assertIn("context.wrap_socket(server.socket, server_side=True)", proxy_script)
        self.assertNotIn("GET,DELETE", proxy)
        self.assertIn("key: agents.x-k8s.io/sandbox-name-hash", network_policy)
        self.assertIn("operator: Exists", network_policy)
        self.assertNotIn("openshell.ai/managed-by: openshell", network_policy)
        self.assertIn("sre-skills.part-000:", rendered)
        self.assertNotIn("kubernetes-sre-SKILL.md", rendered)
        self.assertIn("/sandbox/.hermes/skills/kubernetes-sre", mounts_by_path)
        self.assertIn("/sandbox/.hermes/skills/devops", mounts_by_path)
        self.assertIn("/sandbox/.hermes/skills/infrastructure", mounts_by_path)
        self.assertEqual(
            mounts_by_path["/sandbox/.hermes/skills/kubernetes-sre"]["sub_path"],
            "hermes/skills/kubernetes-sre",
        )
        self.assertIn("/sandbox/.hermes/.sre-proxy-token", mounts_by_path)
        self.assertTrue(mounts_by_path["/sandbox/.hermes/.sre-proxy-token"]["read_only"])
        self.assertNotIn("/sandbox/.hermes", mounts_by_path)

    def test_sre_policy_allows_only_read_access_to_chart_cli_mount(self) -> None:
        sre_rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--set",
            "sre.enabled=true",
        )
        default_rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
        )

        sre_runtime = self.rendered_from_source(
            sre_rendered,
            "nemoclaw-openshell-kubernetes/templates/runtime-configmap.yaml",
        )
        default_runtime = self.rendered_from_source(
            default_rendered,
            "nemoclaw-openshell-kubernetes/templates/runtime-configmap.yaml",
        )
        self.assertIn("      read_only:\n        - /chart-bin\n", sre_runtime)
        self.assertNotIn("      read_only:\n        - /chart-bin\n", default_runtime)

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
            "--set-string",
            "sre.rbac.mode=broad-no-delete",
            "--set-string",
            "sre.rbac.dangerousAcknowledgement=I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE",
            "--set",
            "sre.openshiftLlmDeploy.deletion.enabled=true",
            "--set-string",
            "sre.openshiftLlmDeploy.targetNamespace=models-eval",
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
        proxy = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/model-delete-proxy.yaml",
        )
        self.assertIn("namespace: models-eval", rbac)
        self.assertIn('resources: ["inferenceservices"]', rbac)
        self.assertIn('resourceNames: ["owned-model"]', rbac)
        self.assertIn('verbs: ["delete"]', rbac)
        self.assertNotIn("kind: ClusterRole", rbac)
        self.assertNotRegex(rbac, r"(?m)^\s*- persistentvolumeclaims\s*$")
        self.assertNotRegex(rbac, r"(?m)^\s*- secrets\s*$")
        self.assertIn("name: PROXY_MAX_REQUEST_BYTES\n              value: \"10485760\"", proxy)
        self.assertIn("name: PROXY_MAX_RESPONSE_BYTES\n              value: \"33554432\"", proxy)
        config = self.bootstrap_config(rendered)
        self.assertIn("OPENSHIFT_LLM_DELETE_ENDPOINT", config["agentEnv"])
        self.assertNotIn("OPENSHIFT_LLM_DELETE_API", config["agentEnv"])
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
            "--set-string",
            "sre.rbac.mode=broad-no-delete",
            "--set-string",
            "sre.rbac.dangerousAcknowledgement=I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE",
            "--set",
            "sre.openshiftLlmDeploy.deletion.enabled=true",
            "--set-string",
            "sre.openshiftLlmDeploy.targetNamespace=models-eval",
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

    def test_api_proxy_rejection_closes_connection_before_unread_body(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "api_proxy.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_api_proxy_reject", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class Handler:
            command = "DELETE"
            close_connection = False
            wfile = io.BytesIO()

            def __init__(self) -> None:
                self.status = 0
                self.headers: dict[str, str] = {}

            def send_response(self, status: int) -> None:
                self.status = status

            def send_header(self, name: str, value: str) -> None:
                self.headers[name] = value

            def end_headers(self) -> None:
                return None

        handler = Handler()
        module.ProxyHandler.reject(handler, 405, "method_not_allowed")
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.status, 405)
        self.assertEqual(handler.headers["Connection"], "close")
        self.assertEqual(handler.wfile.getvalue(), b'{"error":"method_not_allowed"}\n')

    def test_api_proxy_blocks_sensitive_general_paths_and_exactly_scopes_delete(self) -> None:
        script = CHART_DIR / "files" / "scripts" / "api_proxy.py"
        spec = importlib.util.spec_from_file_location("nemoclaw_api_proxy_policy", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(
            module.request_allowed(
                "/apis/apps/v1/namespaces/models/deployments/example", "PATCH", "general"
            )
        )
        for target in (
            "/api/v1/namespaces/models/secrets",
            "/api/v1/namespaces/models/secrets/credential/unexpected",
            "/api/v1/namespaces/models/serviceaccounts/privileged/token",
            "/api/v1/namespaces/models/pods/example/exec",
            "/api/v1/namespaces/models/pods/example/ephemeralcontainers",
            "/api/v1/nodes/worker/proxy",
        ):
            with self.subTest(target=target):
                self.assertFalse(module.request_allowed(target, "GET", "general"))

        with mock.patch.dict(
            os.environ,
            {"PROXY_SERVICE_PROXY_NAMESPACE": "models"},
            clear=False,
        ):
            self.assertTrue(
                module.request_allowed(
                    "/api/v1/namespaces/models/services/http:model:8000/proxy/health",
                    "GET",
                    "general",
                )
            )

        with mock.patch.dict(
            os.environ,
            {
                "PROXY_SERVICE_NAMESPACE": "openshift-monitoring",
                "PROXY_SERVICE_NAME": "thanos-querier",
                "PROXY_SERVICE_PORT": "9091",
                "PROXY_SERVICE_SCHEME": "https",
            },
            clear=False,
        ):
            metrics_path = "/api/v1/query?query=up"
            self.assertTrue(
                module.request_allowed(metrics_path, "GET", "exact-service-proxy")
            )
            self.assertEqual(
                module.direct_service_url(metrics_path),
                "https://thanos-querier.openshift-monitoring.svc:9091/api/v1/query?query=up",
            )
            self.assertFalse(
                module.request_allowed(
                    "/api/v1/labels?match[]=up",
                    "GET",
                    "exact-service-proxy",
                )
            )
            self.assertFalse(
                module.request_allowed(
                    "/api/v1/namespaces/openshift-monitoring/services/https:thanos-querier:9091/proxy/api/v1/query?query=up",
                    "GET",
                    "exact-service-proxy",
                )
            )
            self.assertFalse(
                module.request_allowed(metrics_path, "POST", "exact-service-proxy")
            )
            self.assertFalse(
                module.request_allowed(
                    "/api/v1/namespaces/other/services/http:model:8000/proxy/health",
                    "GET",
                    "general",
                )
            )

        allowlist = json.dumps(
            [{"apiGroup": "apps", "resource": "deployments", "name": "owned-model"}]
        )
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_DELETE_NAMESPACE": "models",
                "PROXY_DELETE_ALLOWED_RESOURCES": allowlist,
            },
            clear=False,
        ):
            self.assertTrue(
                module.request_allowed(
                    "/apis/apps/v1/namespaces/models/deployments/owned-model",
                    "DELETE",
                    "exact-delete",
                )
            )
            self.assertFalse(
                module.request_allowed(
                    "/apis/apps/v1/namespaces/models/deployments/other",
                    "DELETE",
                    "exact-delete",
                )
            )
            self.assertFalse(
                module.request_allowed(
                    "/apis/apps/v1/namespaces/other/deployments/owned-model",
                    "DELETE",
                    "exact-delete",
                )
            )
            self.assertFalse(
                module.request_allowed(
                    "/apis/apps/v1/namespaces/models/deployments",
                    "DELETE",
                    "exact-delete",
                )
            )

    def test_model_skill_uses_external_secret_reference_without_webui_cleanup(self) -> None:
        template = CHART_DIR / "files" / "skills" / "openshift-llm-deploy" / "templates" / "model-download-job.yaml"
        payload = template.read_text(encoding="utf-8")
        self.assertIn("serviceAccountName: ${MODEL_RUNNER_SERVICE_ACCOUNT}", payload)
        self.assertIn("automountServiceAccountToken: false", payload)
        self.assertIn("key: ${HF_SECRET_KEY}", payload)
        self.assertNotIn("DELETE_TOKEN_AFTER_DOWNLOAD", payload)
        self.assertNotIn("/var/run/secrets/kubernetes.io/serviceaccount", payload)
        self.assertNotIn("masked", payload.lower())

        deployer = (template.parents[1] / "scripts" / "deploy-model.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("OPENSHIFT_LLM_TARGET_NAMESPACE", deployer)
        self.assertIn("OPENSHIFT_LLM_RUNNER_SERVICE_ACCOUNT", deployer)
        self.assertNotIn("DELETE_TOKEN_AFTER_DOWNLOAD", deployer)
        self.assertNotIn("masked token", deployer.lower())

        verifier = (template.parents[1] / "scripts" / "verify-openai-endpoint.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("service-proxy", verifier)
        self.assertNotIn("port-forward", verifier)

    def test_metrics_proxy_is_an_exact_read_only_opt_in(self) -> None:
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
            "--set",
            "sre.openshiftLlmDeploy.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.metrics.enabled=true",
        )
        proxy = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/metrics-proxy.yaml",
        )
        rbac = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/metrics-rbac.yaml",
        )
        runtime = self.rendered_from_source(
            rendered,
            "nemoclaw-openshell-kubernetes/templates/runtime-configmap.yaml",
        )
        config = self.bootstrap_config(rendered)
        self.assertIn("value: exact-service-proxy", proxy)
        self.assertIn("value: GET", proxy)
        self.assertNotIn("PATCH", proxy)
        self.assertNotIn('resources: ["services/proxy"]', rbac)
        self.assertNotIn("kind: Role", rbac)
        self.assertNotIn("kind: ClusterRoleBinding", rbac)
        self.assertEqual(
            config["agentEnv"]["METRICS_KUBECONFIG"],
            "/sandbox/.hermes/metrics-kubeconfig",
        )
        self.assertRegex(
            runtime,
            r"(?s)cluster_metrics:.*?protocol: rest\s+tls: skip",
        )

        openshift_rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
            str(CHART_DIR),
            "--values",
            str(CHART_DIR / "values-openshift.yaml"),
            "--set",
            "sre.enabled=true",
            "--set-string",
            "sre.rbac.mode=broad-no-delete",
            "--set-string",
            "sre.rbac.dangerousAcknowledgement=I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE",
            "--set",
            "sre.openshiftLlmDeploy.enabled=true",
            "--set",
            "sre.openshiftLlmDeploy.metrics.enabled=true",
            "--api-versions",
            "security.openshift.io/v1",
        )
        openshift_proxy = self.rendered_from_source(
            openshift_rendered,
            "nemoclaw-openshell-kubernetes/templates/metrics-proxy.yaml",
        )
        service_ca = self.rendered_from_source(
            openshift_rendered,
            "nemoclaw-openshell-kubernetes/templates/metrics-service-ca.yaml",
        )
        openshift_rbac = self.rendered_from_source(
            openshift_rendered,
            "nemoclaw-openshell-kubernetes/templates/metrics-rbac.yaml",
        )
        self.assertIn("name: PROXY_UPSTREAM_CA_FILE", openshift_proxy)
        self.assertIn("mountPath: /upstream-ca", openshift_proxy)
        self.assertIn('service.beta.openshift.io/inject-cabundle: "true"', service_ca)
        self.assertIn("kind: ClusterRoleBinding", openshift_rbac)

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

    def test_bootstrap_hardens_injected_uid_paths_before_nemoclaw_start(self) -> None:
        bootstrap = CHART_DIR.joinpath("files", "scripts", "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("test -d /sandbox && test ! -L /sandbox", bootstrap)
        self.assertIn("chmod u=rwx,g=rwx,o=,g-s,o-t /sandbox", bootstrap)
        self.assertIn("chmod u=rwx,g=,o=,g-s,o-t /sandbox/.hermes", bootstrap)
        self.assertIn("exec /usr/local/bin/nemoclaw-start", bootstrap)
        rendered = self.run_helm(
            "template",
            "nemoclaw-openshell-kubernetes-test",
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
