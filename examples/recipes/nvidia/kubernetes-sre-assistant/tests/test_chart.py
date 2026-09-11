# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render-level and runtime checks for the kubernetes-sre-assistant recipe.

The recipe is an umbrella chart over examples/tools/kubernetes-deployer. The
fixture materializes that dependency once per test run with
``helm dependency update`` so the rendered umbrella always reflects the
sibling chart's current source.
"""

from pathlib import Path
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
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


CHART_DIR = Path(__file__).resolve().parents[1]
DEPLOYER_DIR = CHART_DIR.parents[2] / "tools" / "kubernetes-deployer"
DEPLOYER_SCRIPTS = DEPLOYER_DIR / "files" / "scripts"
RECIPE_SOURCE = "kubernetes-sre-assistant/templates"
DEPLOYER_SOURCE = "kubernetes-sre-assistant/charts/deployer/templates"

ALLOWED_SRE_BUNDLE_ROOTS = {"kubernetes-sre", "openshift-llm-deploy"}
REQUIRED_SRE_BUNDLE_FILES = {"kubernetes-sre/SKILL.md", "openshift-llm-deploy/SKILL.md"}
RUNTIME_SUPPORT_DIRECTORIES = {"scripts", "templates", "tools", "workflows", "resources"}
LEGAL_FILENAMES = {"LICENSE", "LICENSE.md", "NOTICE", "NOTICE.md", "SOURCE_NOTICES.md"}
EXCLUDED_SRE_BUNDLE_PREFIXES: set[str] = set()
RUNTIME_SAFETY_MARKER = "<!-- nemoclaw-runtime-safety-v1 -->"
BROAD_MODE = (
    "--set-string",
    "global.sre.rbac.mode=broad-no-delete",
    "--set-string",
    "global.sre.rbac.dangerousAcknowledgement=I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE",
)
MODEL_SKILL = (*BROAD_MODE, "--set", "global.sre.openshiftLlmDeploy.enabled=true")


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
            or (relative.parts[0] == "openshift-llm-deploy" and "references" in lowered_parts)
        ):
            continue
        reviewed.add(name)
    return reviewed


EXPECTED_SRE_BUNDLE_FILES = reviewed_skill_source_files()


class RecipeTest(unittest.TestCase):
    """Exercise the umbrella chart through Helm's public command-line interface."""

    @classmethod
    def setUpClass(cls) -> None:
        completed = subprocess.run(
            ["helm", "dependency", "update", str(CHART_DIR)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise AssertionError(f"helm dependency update failed:\n{completed.stdout}\n{completed.stderr}")

    @staticmethod
    def helm_arguments(*arguments: str) -> list[str]:
        resolved = list(arguments)
        if arguments and arguments[0] == "template":
            resolved.extend(["--api-versions", "agents.x-k8s.io/v1alpha1"])
        openshift = any(argument.endswith("values-openshift.yaml") for argument in arguments)
        if openshift:
            resolved.extend(
                [
                    "--set",
                    "deployer.openshell.server.openshift.gatewayUid.value=1001200001",
                    "--set",
                    "deployer.openshell.server.openshift.sandboxUid.value=1001200002",
                ]
            )
        profile_files = ("values-openshift.yaml", "values-kubernetes.yaml")
        if arguments and arguments[0] in {"template", "lint"} and not any(
            "serviceAccountIssuerDiscovery" in argument or argument.endswith(profile_files)
            for argument in arguments
        ):
            resolved.extend(
                ["--set", "deployer.platform.serviceAccountIssuerDiscovery.preexistingAnonymousAccess=true"]
            )
        return resolved

    def run_helm(self, *arguments: str) -> str:
        resolved = self.helm_arguments(*arguments)
        completed = subprocess.run(["helm", *resolved], check=False, capture_output=True, text=True)
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"helm {' '.join(arguments)} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        return completed.stdout

    def assert_helm_rejected(self, command: str, *arguments: str, expected: str) -> None:
        resolved = self.helm_arguments(command, *arguments)
        completed = subprocess.run(["helm", *resolved], check=False, capture_output=True, text=True)
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, msg=f"helm {command} unexpectedly accepted invalid values:\n{output}")
        self.assertIn(expected, output, msg=f"helm {command} failed for the wrong reason\nexpected fragment: {expected}\noutput:\n{output}")

    def render(self, *arguments: str) -> str:
        return self.run_helm("template", "sre", str(CHART_DIR), "--namespace", "ops", *arguments)

    @staticmethod
    def rendered_from_source(rendered: str, source: str) -> str:
        documents = rendered.split("\n---\n")
        selected = [document for document in documents if f"# Source: {source}" in document]
        if not selected:
            raise AssertionError(f"no rendered documents found for {source}")
        return "\n---\n".join(selected)

    @classmethod
    def bootstrap_config(cls, rendered: str) -> dict[str, object]:
        runtime = cls.rendered_from_source(rendered, f"{DEPLOYER_SOURCE}/runtime-configmap.yaml")
        lines = runtime.splitlines()
        start = lines.index("  bootstrap-config.json: |") + 1
        body_lines: list[str] = []
        for line in lines[start:]:
            if not line.startswith("    "):
                break
            body_lines.append(line[4:])
        return json.loads("\n".join(body_lines))

    @classmethod
    def rendered_policy(cls, rendered: str) -> str:
        runtime = cls.rendered_from_source(rendered, f"{DEPLOYER_SOURCE}/runtime-configmap.yaml")
        return runtime.split("  policy.yaml: |", 1)[1]

    @staticmethod
    def network_policy_block(policy: str, name: str) -> str:
        """Return one rendered network_policies entry (the ConfigMap nests it at six spaces)."""
        lines = policy.splitlines()
        start = lines.index(f"      {name}:")
        block = [lines[start]]
        for line in lines[start + 1:]:
            if line.strip() and not line.startswith("        "):
                break
            block.append(line)
        return "\n".join(block)

    @staticmethod
    def mounts_by_path(config: dict[str, object]) -> dict[str, dict[str, object]]:
        return {
            mount["mount_path"]: mount
            for mount in config["driverConfig"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
        }

    def load_plugin(self, name: str, state: Path, plugin_root: Path):
        """Load seed_sre.py against a scratch state volume and plugin mount."""
        environment = {
            "RELEASE_ID": "test/release",
            "RELEASE_REVISION": "1",
            "SEED_STATE": str(state),
            "SEED_PLUGIN_ROOT": str(plugin_root),
            "SEED_CORE_MODULE_PATH": str(DEPLOYER_SCRIPTS),
        }
        sys.modules.pop("seed", None)
        with mock.patch.dict(os.environ, environment, clear=False):
            spec = importlib.util.spec_from_file_location(name, CHART_DIR / "files" / "scripts" / "seed_sre.py")
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        sys.modules.pop("seed", None)
        self.assertEqual(module.seed.STATE, state)
        return module

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
        payloads = files or {name: f"fixture for {name}\n".encode("utf-8") for name in EXPECTED_SRE_BUNDLE_FILES}
        manifest_lines = [f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}" for name in sorted(payloads)]
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
        destination.write_bytes(lzma.compress(uncompressed.getvalue(), format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME))
        payload = destination.read_bytes()
        parts_json = json.dumps(
            {"parts": [{"name": destination.name, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}], "version": 1},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload).hexdigest(), hashlib.sha256(manifest).hexdigest(), parts_json

    # --- Chart shape ---------------------------------------------------------

    def test_chart_lints(self) -> None:
        self.run_helm("lint", str(CHART_DIR), "--set", "deployer.openshell.agentSandbox.preflight.enabled=false")

    def test_recipe_depends_on_the_sibling_deployer_chart(self) -> None:
        chart_yaml = CHART_DIR.joinpath("Chart.yaml").read_text(encoding="utf-8")
        self.assertIn("name: kubernetes-deployer", chart_yaml)
        self.assertIn("alias: deployer", chart_yaml)
        self.assertIn("repository: file://../../../tools/kubernetes-deployer", chart_yaml)
        deployer_chart = DEPLOYER_DIR.joinpath("Chart.yaml").read_text(encoding="utf-8")
        version = re.search(r"(?m)^version: (\S+)$", deployer_chart).group(1)
        self.assertIn(f'version: "{version}"', chart_yaml)
        self.assertTrue(CHART_DIR.joinpath("Chart.lock").is_file())
        self.assertIn("/charts/*.tgz", CHART_DIR.joinpath(".gitignore").read_text(encoding="utf-8"))

    def test_packaged_chart_excludes_review_only_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.run_helm("package", str(CHART_DIR), "--destination", directory)
            packages = list(Path(directory).glob("*.tgz"))
            self.assertEqual(len(packages), 1)
            with tarfile.open(packages[0], mode="r:gz") as archive:
                members = {member.name for member in archive.getmembers()}
            prefix = f"{CHART_DIR.name}/"
            self.assertIn(f"{prefix}LICENSE", members)
            self.assertIn(f"{prefix}THIRD-PARTY-NOTICES", members)
            self.assertIn(f"{prefix}files/sre-skills.part-000", members)
            self.assertIn(f"{prefix}charts/kubernetes-deployer/Chart.yaml", members)
            self.assertFalse(any(name.startswith(f"{prefix}files/skills/") for name in members))
            self.assertFalse(any(name.startswith(f"{prefix}scripts/") for name in members))
            self.assertFalse(any(name.startswith(f"{prefix}tests/") for name in members))

    def test_openshift_profile_mirrors_the_deployer_profile(self) -> None:
        def meaningful(text: str) -> list[str]:
            return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]

        # Each recipe profile nests the deployer profile under `deployer:` and
        # the vendored auto-heal profile under `autoheal:`. Both halves must
        # stay line-for-line identical to the subchart file they mirror, so a
        # platform fix in either subchart cannot silently miss the recipe.
        autoheal_dir = CHART_DIR / "charts" / "sre-autoheal-agent"

        def split_profile(path: str) -> tuple[list[str], list[str]]:
            lines = meaningful(CHART_DIR.joinpath(path).read_text(encoding="utf-8"))
            self.assertEqual(lines[0], "deployer:")
            index = lines.index("autoheal:")
            return lines[1:index], lines[index + 1 :]

        for platform in ("openshift", "kubernetes"):
            with self.subTest(platform=platform):
                filename = f"values-{platform}.yaml"
                deployer_part, autoheal_part = split_profile(filename)
                self.assertEqual(
                    [line[2:] for line in deployer_part],
                    meaningful(DEPLOYER_DIR.joinpath(filename).read_text(encoding="utf-8")),
                )
                self.assertEqual(
                    [line[2:] for line in autoheal_part],
                    meaningful(autoheal_dir.joinpath(filename).read_text(encoding="utf-8")),
                )

    def test_autoheal_is_opt_in_and_renders_nothing_by_default(self) -> None:
        rendered = self.run_helm(
            "template",
            "sre",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-kubernetes.yaml"),
        )
        self.assertNotIn("charts/autoheal/templates", rendered)
        contract = self.rendered_from_source(
            rendered,
            "kubernetes-sre-assistant/templates/000-validate.yaml",
        )
        self.assertIn('autoheal: "false"', contract)

    def test_autoheal_enabled_renders_its_controller_and_records_the_posture(self) -> None:
        rendered = self.run_helm(
            "template",
            "sre",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-kubernetes.yaml"),
            "--set",
            "autoheal.enabled=true",
            "--set",
            "autoheal.llm.baseUrl=https://model.example/v1",
            "--set",
            "autoheal.llm.model=example-model",
        )
        self.assertIn("charts/autoheal/templates/deployment.yaml", rendered)
        self.assertIn("charts/autoheal/templates/rbac.yaml", rendered)
        contract = self.rendered_from_source(
            rendered,
            "kubernetes-sre-assistant/templates/000-validate.yaml",
        )
        self.assertIn('autoheal: "true"', contract)
        self.assertIn('autohealMode: "observe"', contract)
        self.assertIn('autohealRbacProfile: "safe"', contract)
        # The controller must never be granted cluster-admin by this recipe.
        self.assertNotIn("cluster-admin", rendered.lower())
        # The subchart defaults to a mutable tag; this repository pins digests.
        controller = self.rendered_from_source(
            rendered,
            "kubernetes-sre-assistant/charts/autoheal/templates/deployment.yaml",
        )
        image = next(
            line.split("image:", 1)[1].strip()
            for line in controller.splitlines()
            if line.strip().startswith("image:")
        )
        self.assertIn("@sha256:", image, msg=f"agent image is not digest-pinned: {image}")

    def test_autoheal_refuses_an_unpinned_agent_image(self) -> None:
        # `helm upgrade --reuse-values` restored the subchart's mutable tag on a
        # live cluster; the guard turns that into an install-time failure.
        self.assert_helm_rejected(
            "template",
            "sre",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-kubernetes.yaml"),
            "--set",
            "autoheal.enabled=true",
            "--set",
            "autoheal.llm.baseUrl=https://model.example/v1",
            "--set",
            "autoheal.llm.model=example-model",
            "--set",
            "autoheal.image.digest=",
            expected="autoheal.image.digest must be set",
        )

    def test_autoheal_remediating_modes_require_an_acknowledgement(self) -> None:
        for mode in ("safe", "assisted"):
            with self.subTest(mode=mode):
                self.assert_helm_rejected(
                    "template",
                    "sre",
                    str(CHART_DIR),
                    "-f",
                    str(CHART_DIR / "values-kubernetes.yaml"),
                    "--set",
                    "autoheal.enabled=true",
                    "--set",
                    "autoheal.llm.baseUrl=https://model.example/v1",
                    "--set",
                    "autoheal.llm.model=example-model",
                    "--set",
                    f"autoheal.agentConfig.policy.mode={mode}",
                    expected="I_ACKNOWLEDGE_CLUSTER_REMEDIATION",
                )

    def test_autoheal_rejects_incoherent_or_unsafe_configuration(self) -> None:
        base = [
            "template",
            "sre",
            str(CHART_DIR),
            "-f",
            str(CHART_DIR / "values-kubernetes.yaml"),
            "--set",
            "autoheal.enabled=true",
        ]
        good_llm = [
            "--set",
            "autoheal.llm.baseUrl=https://model.example/v1",
            "--set",
            "autoheal.llm.model=example-model",
        ]
        acting = [
            "--set",
            "autoheal.dangerousAcknowledgement=I_ACKNOWLEDGE_CLUSTER_REMEDIATION",
            "--set",
            "autoheal.agentConfig.policy.mode=assisted",
        ]
        # A remediating mode cannot run on a read-only role.
        self.assert_helm_rejected(
            *base,
            *good_llm,
            *acting,
            "--set",
            "autoheal.rbac.profile=read-only",
            expected="cannot remediate",
        )
        # An unknown mode or profile is refused rather than silently defaulted.
        self.assert_helm_rejected(
            *base, *good_llm, "--set", "autoheal.agentConfig.policy.mode=yolo",
            expected="autoheal.agentConfig.policy.mode must be one of",
        )
        self.assert_helm_rejected(
            *base, *good_llm, "--set", "autoheal.rbac.profile=admin",
            expected="autoheal.rbac.profile must be one of",
        )
        # Diagnosis carries cluster state, so the endpoint must exist and be TLS.
        self.assert_helm_rejected(
            *base, expected="requires autoheal.llm.baseUrl and autoheal.llm.model"
        )
        self.assert_helm_rejected(
            *base,
            "--set",
            "autoheal.llm.baseUrl=http://model.example/v1",
            "--set",
            "autoheal.llm.model=example-model",
            expected="must use https://",
        )

    def test_values_bundle_identity_must_match_committed_files(self) -> None:
        digest = CHART_DIR.joinpath("files", "sre-skills.tar.xz.sha256").read_text(encoding="utf-8").strip()
        values = CHART_DIR.joinpath("values.yaml").read_text(encoding="utf-8")
        self.assertIn(f"sha256: {digest}", values)
        self.assert_helm_rejected(
            "template", "sre", str(CHART_DIR), "--set-string", f"global.sre.bundle.sha256={'0' * 64}",
            expected="global.sre.bundle.sha256 must equal",
        )
        self.assert_helm_rejected(
            "template", "sre", str(CHART_DIR), "--set", "global.sre.bundle.parts[0]=sre-skills.part-001",
            expected="global.sre.bundle.parts must list",
        )

    def test_release_and_deployer_naming_are_constrained(self) -> None:
        self.assert_helm_rejected("template", "x" * 41, str(CHART_DIR), expected="at most 40 characters")
        self.assert_helm_rejected("template", "cluster-api-helper", str(CHART_DIR), expected="NemoClaw rejects")
        self.assert_helm_rejected(
            "template", "sre", str(CHART_DIR), "--set-string", "deployer.nameOverride=other", expected="nameOverride",
        )
        self.assert_helm_rejected(
            "template", "sre", str(CHART_DIR), "--set-string", "deployer.fullnameOverride=custom", expected="fullnameOverride",
        )
        self.assert_helm_rejected(
            "template", "sre", str(CHART_DIR), "--set-string", "deployer.openshell.mode=existing", expected="openshell.mode",
        )

    # --- Wiring into the deployer -------------------------------------------

    def test_default_render_wires_skills_proxy_and_policy_into_the_deployer(self) -> None:
        rendered = self.render("--set", "deployer.operatorClient.enabled=true")
        config = self.bootstrap_config(rendered)
        mounts = self.mounts_by_path(config)
        digest = CHART_DIR.joinpath("files", "sre-skills.tar.xz.sha256").read_text(encoding="utf-8").strip()

        self.assertEqual(config["agentEnv"]["KUBERNETES_SRE_ENDPOINT"], "https://sre-sre-proxy.ops.svc.cluster.local:8001")
        self.assertEqual(config["agentEnv"]["KUBECONFIG"], "/sandbox/.hermes/sre-kubeconfig")
        self.assertEqual(config["agentEnv"]["SRE_KUBECONFIG"], "/sandbox/.hermes/sre-kubeconfig")
        self.assertNotIn("KUBERNETES_SRE_API", config["agentEnv"])
        for path, sub_path in (
            ("/sandbox/.hermes/skills/kubernetes-sre", "hermes/skills/kubernetes-sre"),
            ("/sandbox/.hermes/.sre-proxy-token", "hermes/.sre-proxy-token"),
            ("/sandbox/.hermes/sre-kubeconfig", "hermes/sre-kubeconfig"),
            ("/chart-bin", "hermes/bin"),
        ):
            self.assertEqual(mounts[path]["sub_path"], sub_path)
            self.assertTrue(mounts[path]["read_only"])
        self.assertNotIn("/sandbox/.hermes", mounts)
        self.assertNotIn("/sandbox/.hermes/skills/openshift-llm-deploy", mounts)
        self.assertEqual(config["seedPlugins"], [{"name": "sre", "identity": digest}])
        self.assertEqual(config["sandboxName"], "sre-hermes")

        seed = self.rendered_from_source(rendered, f"{DEPLOYER_SOURCE}/seed-job.yaml")
        self.assertIn("name: stage-sre-cli", seed)
        self.assertIn("/plugins/sre/stage_sre_cli.py", seed)
        self.assertIn("name: OPENSHIFT_CLI_AMD64_URL", seed)
        self.assertIn("name: OPENSHIFT_CLI_ARM64_SHA256", seed)
        self.assertIn("mountPath: /plugins/sre", seed)
        self.assertIn("name: sre-sre-runtime", seed)
        self.assertIn("name: sre-sre-skills-000", seed)
        self.assertIn("mountPath: /skills-bundle", seed)
        self.assertIn("mountPath: /cli-staging", seed)
        self.assertIn("mountPath: /proxy-auth", seed)
        self.assertIn("mountPath: /proxy-tls-ca", seed)
        self.assertIn("path: ca.crt", seed)
        self.assertIn('value: "https://sre-sre-proxy.ops.svc.cluster.local:8001"', seed)
        self.assertNotIn("http://", seed)

        policy = self.rendered_policy(rendered)
        self.assertIn("      - /chart-bin\n", policy)
        block = self.network_policy_block(policy, "kubernetes_sre")
        for fragment in ("host: sre-sre-proxy.ops.svc.cluster.local", "port: 8001", "protocol: rest", "tls: skip", "method: PATCH", "path: /chart-bin/oc"):
            self.assertIn(fragment, block)
        self.assertNotIn("method: POST", block)
        self.assertNotIn("openshift_llm_delete", policy)
        self.assertNotIn("model_release_metadata", policy)

        client = self.rendered_from_source(rendered, f"{DEPLOYER_SOURCE}/operator-client.yaml")
        self.assertIn('value: "kubernetes-sre"', client)
        contract = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/000-validate.yaml")
        self.assertIn('rbacMode: "safe"', contract)
        self.assertIn('deployer: "sre-deployer"', contract)
        runtime = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/runtime-configmap.yaml")
        for key in ("seed_sre.py:", "stage_sre_cli.py:", "api_proxy.py:", "sre-skills.parts.json:", "sre-skills.tar.xz.sha256:", "sre-skills.manifest.sha256:"):
            self.assertIn(key, runtime)

    def test_deployer_alone_carries_no_sre_material(self) -> None:
        completed = subprocess.run(
            [
                "helm", "template", "plain", str(DEPLOYER_DIR), "--api-versions", "agents.x-k8s.io/v1alpha1",
                "--set", "platform.serviceAccountIssuerDiscovery.preexistingAnonymousAccess=true",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        rendered = completed.stdout
        self.assertNotIn("/chart-bin", rendered)
        self.assertNotIn("kubernetes_sre", rendered)
        self.assertNotIn("sre-proxy", rendered)
        self.assertNotIn("stage-sre-cli", rendered)
        self.assertFalse(list(DEPLOYER_DIR.glob("files/sre-skills.*")))
        self.assertFalse((DEPLOYER_DIR / "files" / "skills").exists())

    def test_safe_sre_proxy_has_no_delete_or_secret_access(self) -> None:
        rendered = self.render()
        rbac = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/sre-rbac.yaml")
        proxy = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/sre-proxy.yaml")
        tls_secret = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/proxy-tls-secret.yaml")
        network_policy = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/networkpolicy.yaml")
        proxy_script = (CHART_DIR / "files" / "scripts" / "api_proxy.py").read_text(encoding="utf-8")
        self.assertNotIn('resources: ["*"]', rbac)
        self.assertNotRegex(rbac, r"(?m)^\s*- secrets\s*$")
        self.assertNotRegex(rbac, r'(?m)^\s*verbs:.*"delete"')
        self.assertIn('resources: ["deployments/scale", "statefulsets/scale"]', rbac)
        self.assertRegex(rbac, r'(?s)resources: \["deployments/scale", "statefulsets/scale"\].*?verbs: \["get", "patch", "update"\]')
        self.assertIn("name: sre-sre-proxy", rbac)
        self.assertIn("name: ops-sre-sre-", rbac)
        self.assertIn("name: PROXY_ALLOWED_METHODS", proxy)
        self.assertIn('value: "GET,PATCH"', proxy)
        self.assertIn('name: PROXY_MAX_REQUEST_BYTES\n              value: "10485760"', proxy)
        self.assertIn("value: /proxy-tls/tls.crt", proxy)
        self.assertIn("image: \"docker.io/library/python:3.13.7-slim@sha256:", proxy)
        self.assertIn("name: sre-sre-runtime", proxy)
        self.assertIn("type: kubernetes.io/tls", tls_secret)
        self.assertIn('"ca.crt":', tls_secret)
        self.assertIn("ssl.PROTOCOL_TLS_SERVER", proxy_script)
        self.assertNotIn("GET,DELETE", proxy)
        self.assertIn("key: agents.x-k8s.io/sandbox-name-hash", network_policy)
        self.assertIn("operator: Exists", network_policy)
        self.assertIn("port: 8001", network_policy)
        self.assertIn("sre-skills.part-000:", rendered)
        self.assertNotIn(f"# Source: {RECIPE_SOURCE}/networkpolicy.yaml", self.render("--set", "global.sre.networkPolicy.enabled=false"))

    def test_values_require_broad_access_acknowledgement(self) -> None:
        self.assert_helm_rejected(
            "template", "sre", str(CHART_DIR), "--set-string", "global.sre.rbac.mode=broad-no-delete",
            expected="global.sre.rbac.dangerousAcknowledgement",
        )

    def test_broad_sre_is_explicit_and_still_has_no_delete_verb(self) -> None:
        rendered = self.render(*BROAD_MODE)
        rbac = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/sre-rbac.yaml")
        proxy = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/sre-proxy.yaml")
        self.assertIn('resources: ["*"]', rbac)
        self.assertIn('verbs: ["get", "list", "watch", "create", "patch", "update"]', rbac)
        self.assertNotRegex(rbac, r'(?m)^\s*verbs:.*"delete"')
        self.assertIn('value: "GET,POST,PUT,PATCH"', proxy)
        block = self.network_policy_block(self.rendered_policy(rendered), "kubernetes_sre")
        self.assertIn("method: POST", block)
        self.assertIn("method: PUT", block)
        profile = self.render("-f", str(CHART_DIR / "values-broad-no-delete.yaml"))
        self.assertIn('rbacMode: "broad-no-delete"', self.rendered_from_source(profile, f"{RECIPE_SOURCE}/000-validate.yaml"))

    def test_full_model_skill_requires_broad_no_delete_mode(self) -> None:
        self.assert_helm_rejected(
            "template", "sre", str(CHART_DIR), "--set", "global.sre.openshiftLlmDeploy.enabled=true",
            expected="global.sre.rbac.mode=broad-no-delete",
        )
        rendered = self.render(*MODEL_SKILL, "--set", "deployer.operatorClient.enabled=true")
        config = self.bootstrap_config(rendered)
        mounts = self.mounts_by_path(config)
        self.assertIn("/sandbox/.hermes/skills/openshift-llm-deploy", mounts)
        self.assertEqual(config["agentEnv"]["KUBECONFIG"], "/sandbox/.hermes/sre-kubeconfig")
        self.assertEqual(config["agentEnv"]["OPENSHIFT_LLM_TARGET_NAMESPACE"], "ops")
        self.assertEqual(config["agentEnv"]["OPENSHIFT_LLM_RUNNER_SERVICE_ACCOUNT"], "sre-sre-llm-runner")
        self.assertNotIn("OPENSHIFT_LLM_HF_SECRET_NAME", config["agentEnv"])
        self.assertNotIn("OPENSHIFT_LLM_HF_SECRET_KEY", config["agentEnv"])
        seed = self.rendered_from_source(rendered, f"{DEPLOYER_SOURCE}/seed-job.yaml")
        self.assertIn("name: HF_TOKEN_INTAKE_JSON", seed)
        self.assertIn("name: DYNAMO_DEFAULTS_JSON", seed)
        self.assertIn("model_release_metadata", self.rendered_policy(rendered))
        client = self.rendered_from_source(rendered, f"{DEPLOYER_SOURCE}/operator-client.yaml")
        self.assertIn('value: "kubernetes-sre,openshift-llm-deploy"', client)
        runner = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/model-runner-serviceaccount.yaml")
        self.assertIn("name: sre-sre-llm-runner", runner)
        self.assertIn("automountServiceAccountToken: false", runner)

    def test_values_require_model_deletion_namespace(self) -> None:
        self.assert_helm_rejected(
            "template", "sre", str(CHART_DIR), *MODEL_SKILL, "--set", "global.sre.openshiftLlmDeploy.deletion.enabled=true",
            expected="global.sre.openshiftLlmDeploy.deletion.namespace",
        )

    def test_model_delete_is_limited_to_acknowledged_namespace(self) -> None:
        rendered = self.render(
            *MODEL_SKILL,
            "--set", "global.sre.openshiftLlmDeploy.deletion.enabled=true",
            "--set-string", "global.sre.openshiftLlmDeploy.targetNamespace=models-eval",
            "--set-string", "global.sre.openshiftLlmDeploy.deletion.namespace=models-eval",
            "--set-string", "global.sre.openshiftLlmDeploy.deletion.dangerousAcknowledgement=I_ACKNOWLEDGE_NAMESPACE_MODEL_DELETE",
            "--set-string", "global.sre.openshiftLlmDeploy.deletion.allowedResources[0].apiGroup=serving.kserve.io",
            "--set-string", "global.sre.openshiftLlmDeploy.deletion.allowedResources[0].resource=inferenceservices",
            "--set-string", "global.sre.openshiftLlmDeploy.deletion.allowedResources[0].name=owned-model",
        )
        rbac = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/model-delete-rbac.yaml")
        proxy = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/model-delete-proxy.yaml")
        self.assertIn("namespace: models-eval", rbac)
        self.assertIn('resources: ["inferenceservices"]', rbac)
        self.assertIn('resourceNames: ["owned-model"]', rbac)
        self.assertIn('verbs: ["delete"]', rbac)
        self.assertNotIn("kind: ClusterRole", rbac)
        self.assertIn("value: exact-delete", proxy)
        self.assertIn("value: DELETE", proxy)
        config = self.bootstrap_config(rendered)
        self.assertEqual(config["agentEnv"]["OPENSHIFT_LLM_DELETE_ENDPOINT"], "https://sre-sre-model-delete-proxy.ops.svc.cluster.local:8001")
        self.assertEqual(config["agentEnv"]["OPENSHIFT_LLM_DELETE_NAMESPACE"], "models-eval")
        self.assertNotIn("OPENSHIFT_LLM_DELETE_API", config["agentEnv"])
        mounts = self.mounts_by_path(config)
        self.assertIn("/sandbox/.hermes/model-delete-kubeconfig", mounts)
        self.assertIn("method: DELETE", self.network_policy_block(self.rendered_policy(rendered), "openshift_llm_delete"))
        seed = self.rendered_from_source(rendered, f"{DEPLOYER_SOURCE}/seed-job.yaml")
        self.assertIn("name: MODEL_DELETE_PROXY_ENDPOINT", seed)
        network_policy = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/networkpolicy.yaml")
        self.assertIn("component: model-delete-proxy", network_policy)

    def test_model_delete_requires_exact_resource_allowlist(self) -> None:
        self.assert_helm_rejected(
            "template", "sre", str(CHART_DIR), *MODEL_SKILL,
            "--set", "global.sre.openshiftLlmDeploy.deletion.enabled=true",
            "--set-string", "global.sre.openshiftLlmDeploy.targetNamespace=models-eval",
            "--set-string", "global.sre.openshiftLlmDeploy.deletion.namespace=models-eval",
            "--set-string", "global.sre.openshiftLlmDeploy.deletion.dangerousAcknowledgement=I_ACKNOWLEDGE_NAMESPACE_MODEL_DELETE",
            expected="allowedResources",
        )

    def test_metrics_proxy_is_an_exact_read_only_opt_in(self) -> None:
        rendered = self.render(*MODEL_SKILL, "--set", "global.sre.openshiftLlmDeploy.metrics.enabled=true")
        proxy = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/metrics-proxy.yaml")
        rbac = self.rendered_from_source(rendered, f"{RECIPE_SOURCE}/metrics-rbac.yaml")
        config = self.bootstrap_config(rendered)
        self.assertIn("value: exact-service-proxy", proxy)
        self.assertIn("value: GET", proxy)
        self.assertNotIn("PATCH", proxy)
        self.assertNotIn("kind: ClusterRoleBinding", rbac)
        self.assertEqual(config["agentEnv"]["METRICS_KUBECONFIG"], "/sandbox/.hermes/metrics-kubeconfig")
        metrics_block = self.network_policy_block(self.rendered_policy(rendered), "cluster_metrics")
        self.assertIn("protocol: rest", metrics_block)
        self.assertIn("tls: skip", metrics_block)
        self.assertNotIn("method: POST", metrics_block)
        openshift = self.render(
            "-f", str(CHART_DIR / "values-openshift.yaml"), *MODEL_SKILL,
            "--set", "global.sre.openshiftLlmDeploy.metrics.enabled=true",
            "--api-versions", "security.openshift.io/v1",
        )
        self.assertIn("name: PROXY_UPSTREAM_CA_FILE", self.rendered_from_source(openshift, f"{RECIPE_SOURCE}/metrics-proxy.yaml"))
        self.assertIn('service.beta.openshift.io/inject-cabundle: "true"', self.rendered_from_source(openshift, f"{RECIPE_SOURCE}/metrics-service-ca.yaml"))
        self.assertIn("kind: ClusterRoleBinding", self.rendered_from_source(openshift, f"{RECIPE_SOURCE}/metrics-rbac.yaml"))

    def test_sre_proxy_auth_secret_has_a_kubernetes_api_header(self) -> None:
        secret = self.rendered_from_source(self.render(), f"{RECIPE_SOURCE}/proxy-auth-secret.yaml")
        self.assertRegex(secret, r"(?m)^apiVersion: v1$")
        self.assertRegex(secret, r"(?m)^kind: Secret$")
        self.assertIn("name: sre-sre-proxy-auth", secret)

    def test_sre_proxy_uses_bearer_authenticated_forwarder(self) -> None:
        proxy = self.rendered_from_source(self.render(), f"{RECIPE_SOURCE}/sre-proxy.yaml")
        self.assertIn("api_proxy.py", proxy)
        self.assertIn("PROXY_CLIENT_TOKEN_FILE", proxy)
        self.assertNotIn("kubectl\n", proxy)
        self.assertNotIn("--accept-hosts=", proxy)

    def test_templates_emit_only_valid_resource_manifests(self) -> None:
        empty: list[str] = []
        invalid: list[str] = []
        for profile, rendered in {"safe": self.render(), "model": self.render(*MODEL_SKILL)}.items():
            for document in rendered.split("\n---\n"):
                source = next((line for line in document.splitlines() if line.startswith("# Source:")), None)
                if source is None:
                    continue
                meaningful = [line for line in document.splitlines() if line.strip() and line.strip() != "---" and not line.lstrip().startswith("#")]
                if not meaningful:
                    empty.append(f"{profile}: {source}")
                elif not meaningful[0].startswith("apiVersion:"):
                    invalid.append(f"{profile}: {source}")
        self.assertFalse(empty, msg="\n".join(empty))
        self.assertFalse(invalid, msg="\n".join(invalid))

    # --- Bundle and builder ---------------------------------------------------

    def test_sre_bundle_scope_is_focused_and_reviewable(self) -> None:
        builder_spec = importlib.util.spec_from_file_location("sre_builder", CHART_DIR / "scripts" / "build-sre-skills-bundle.py")
        builder = importlib.util.module_from_spec(builder_spec)
        builder_spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            plugin = self.load_plugin("sre_plugin_scope", Path(directory), Path(directory))
        expected_roots = frozenset({"kubernetes-sre", "openshift-llm-deploy"})
        expected_required = frozenset({"kubernetes-sre/SKILL.md", "openshift-llm-deploy/SKILL.md"})
        self.assertEqual(builder.ALLOWED_ROOTS, expected_roots)
        self.assertEqual(builder.REQUIRED_FILES, expected_required)
        self.assertEqual(plugin.ALLOWED_SRE_BUNDLE_ROOTS, expected_roots)
        self.assertEqual(plugin.REQUIRED_SRE_BUNDLE_FILES, expected_required)
        self.assertEqual(frozenset(path.name for path in (CHART_DIR / "files" / "skills").iterdir() if path.is_dir()), expected_roots)

    def test_builder_keeps_values_bundle_identity_in_step(self) -> None:
        builder_spec = importlib.util.spec_from_file_location("sre_builder_values", CHART_DIR / "scripts" / "build-sre-skills-bundle.py")
        builder = importlib.util.module_from_spec(builder_spec)
        builder_spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            values = Path(directory) / "values.yaml"
            values.write_text(CHART_DIR.joinpath("values.yaml").read_text(encoding="utf-8"), encoding="utf-8")
            builder.update_values_bundle(values, "f" * 64, ["sre-skills.part-000", "sre-skills.part-001"])
            updated = values.read_text(encoding="utf-8")
            self.assertIn(f"      sha256: {'f' * 64}\n", updated)
            self.assertIn("      parts:\n        - sre-skills.part-000\n        - sre-skills.part-001\n", updated)

    def test_committed_sre_bundle_has_exact_reviewed_contents_and_manifest(self) -> None:
        parts_index = json.loads(CHART_DIR.joinpath("files", "sre-skills.parts.json").read_text(encoding="utf-8"))
        digest_file = CHART_DIR / "files" / "sre-skills.tar.xz.sha256"
        manifest_digest_file = CHART_DIR / "files" / "sre-skills.manifest.sha256"
        self.assertTrue(REQUIRED_SRE_BUNDLE_FILES.issubset(EXPECTED_SRE_BUNDLE_FILES))
        self.assertEqual(set(parts_index), {"parts", "version"})
        self.assertEqual(parts_index["version"], 1)
        payloads: list[bytes] = []
        for index, part in enumerate(parts_index["parts"]):
            self.assertEqual(part["name"], f"sre-skills.part-{index:03d}")
            payload = CHART_DIR.joinpath("files", part["name"]).read_bytes()
            self.assertEqual(len(payload), part["size"])
            self.assertLessEqual(len(payload), 500_000)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), part["sha256"])
            payloads.append(payload)
        bundle = b"".join(payloads)
        self.assertEqual(hashlib.sha256(bundle).hexdigest(), digest_file.read_text(encoding="utf-8").strip())
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:xz") as archive:
            members = archive.getmembers()
            files = {member.name for member in members if member.isfile()}
            self.assertTrue(all(member.isfile() for member in members))
            self.assertEqual(files, EXPECTED_SRE_BUNDLE_FILES | {"MANIFEST.sha256"})
            manifest_payload = archive.extractfile("MANIFEST.sha256").read()
            self.assertEqual(hashlib.sha256(manifest_payload).hexdigest(), manifest_digest_file.read_text(encoding="utf-8").strip())
            entries = manifest_payload.decode("utf-8").splitlines()
            self.assertEqual({line.split("  ", 1)[1] for line in entries}, EXPECTED_SRE_BUNDLE_FILES)
            for line in entries:
                expected, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256(archive.extractfile(name).read()).hexdigest(), expected)
            for name in ("kubernetes-sre/SKILL.md", "openshift-llm-deploy/SKILL.md"):
                skill_text = archive.extractfile(name).read().decode("utf-8")
                self.assertIn(RUNTIME_SAFETY_MARKER, skill_text)
                self.assertIn("Never build or publish custom images", skill_text)
                self.assertIn("never use mutable image tags", skill_text)
        self.assertTrue(any(name.startswith("openshift-llm-deploy/scripts/") for name in files))
        self.assertFalse(any(name.startswith(("devops/", "infrastructure/")) for name in files))
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in files))

    def test_bundled_skills_have_valid_unique_hermes_metadata(self) -> None:
        skills = CHART_DIR / "files" / "skills"
        names: dict[str, Path] = {}
        skill_files = sorted(path for root in (skills / "kubernetes-sre", skills / "openshift-llm-deploy") for path in root.rglob("SKILL.md"))
        self.assertEqual(len(skill_files), 2)
        for path in skill_files:
            content = path.read_text(encoding="utf-8")
            frontmatter = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
            self.assertIsNotNone(frontmatter, f"missing frontmatter: {path}")
            name_match = re.search(r"(?m)^name:\s*([a-z][a-z0-9_-]*)\s*$", frontmatter.group(1))
            self.assertIsNotNone(name_match, f"invalid skill name: {path}")
            self.assertIsNotNone(re.search(r"(?m)^description:\s*\S", frontmatter.group(1)), f"missing description: {path}")
            self.assertNotIn(name_match.group(1), names)
            names[name_match.group(1)] = path

    # --- Seed plugin runtime --------------------------------------------------

    def test_seed_plugin_refuses_to_run_before_the_core_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir()
            plugin = self.load_plugin("sre_plugin_unclaimed", state, Path(directory))
            with self.assertRaisesRegex(SystemExit, "core seed must claim"):
                plugin.main()
            self.assertEqual(sorted(path.name for path in state.iterdir()), [])

    def test_seed_plugin_validates_bundle_and_rejects_unsafe_archives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = self.load_plugin("sre_plugin_bundle", root / "state", root / "plugin")
            valid_root = root / "valid"
            valid = valid_root / "sre-skills.part-000"
            digest, manifest_digest, parts_json = self.write_test_skill_bundle(valid)
            self.assertEqual(set(module.load_sre_bundle(valid_root, digest, manifest_digest, parts_json)), EXPECTED_SRE_BUNDLE_FILES)

            projection = root / "projection"
            revision = projection / "..2026_09_02_17_00_00.000000000"
            revision.mkdir(parents=True)
            (revision / "sre-skills.part-000").write_bytes(valid.read_bytes())
            (projection / "..data").symlink_to(revision.name)
            (projection / "sre-skills.part-000").symlink_to("..data/sre-skills.part-000")
            self.assertEqual(set(module.load_sre_bundle(projection, digest, manifest_digest, parts_json)), EXPECTED_SRE_BUNDLE_FILES)

            escaping_root = root / "escaping"
            escaping_root.mkdir()
            (escaping_root / "sre-skills.part-000").symlink_to(valid)
            with self.assertRaisesRegex(SystemExit, "invalid SRE bundle part"):
                module.load_sre_bundle(escaping_root, digest, manifest_digest, parts_json)
            with self.assertRaisesRegex(SystemExit, "archive SHA-256 mismatch"):
                module.load_sre_bundle(valid_root, "0" * 64, manifest_digest, parts_json)

            corrupt_root = root / "corrupt"
            corrupt_digest, corrupt_manifest_digest, corrupt_parts = self.write_test_skill_bundle(corrupt_root / "sre-skills.part-000", corrupt_manifest=True)
            with self.assertRaisesRegex(SystemExit, "manifest SHA-256 mismatch"):
                module.load_sre_bundle(corrupt_root, corrupt_digest, corrupt_manifest_digest, corrupt_parts)

            traversal_root = root / "traversal"
            traversal_member = tarfile.TarInfo("../escape")
            traversal_member.size = len(b"payload")
            traversal_digest, traversal_manifest_digest, traversal_parts = self.write_test_skill_bundle(traversal_root / "sre-skills.part-000", extra_members=[traversal_member])
            with self.assertRaisesRegex(SystemExit, "unsafe archive member"):
                module.load_sre_bundle(traversal_root, traversal_digest, traversal_manifest_digest, traversal_parts)

            linked_root = root / "linked"
            link_member = tarfile.TarInfo("openshift-llm-deploy/scripts/link")
            link_member.type = tarfile.SYMTYPE
            link_member.linkname = "/etc/passwd"
            link_digest, link_manifest_digest, link_parts = self.write_test_skill_bundle(linked_root / "sre-skills.part-000", extra_members=[link_member])
            with self.assertRaisesRegex(SystemExit, "unsafe archive member"):
                module.load_sre_bundle(linked_root, link_digest, link_manifest_digest, link_parts)

    def test_seed_plugin_installs_and_replaces_read_only_skill_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            skills = state / "hermes" / "skills"
            skills.mkdir(parents=True)
            module = self.load_plugin("sre_plugin_reconcile", state, Path(directory))
            module.seed.write_owner_marker("seeding")
            payloads = {name: f"payload:{name}\n".encode("utf-8") for name in EXPECTED_SRE_BUNDLE_FILES}
            module.reconcile_sre_skills(False, payloads)
            installed = skills / "kubernetes-sre" / "SKILL.md"
            self.assertTrue(installed.is_file())
            self.assertEqual(stat.S_IMODE(installed.parent.stat().st_mode), 0o555)
            self.assertFalse((skills / "openshift-llm-deploy").exists())
            for name in ("devops", "infrastructure"):
                (skills / name).mkdir()
                (skills / name / "SKILL.md").write_text("legacy\n", encoding="utf-8")
            payloads["kubernetes-sre/SKILL.md"] = b"updated\n"
            module.reconcile_sre_skills(False, payloads)
            self.assertEqual(installed.read_bytes(), b"updated\n")
            self.assertEqual(stat.S_IMODE(installed.parent.stat().st_mode), 0o555)
            self.assertFalse((skills / "devops").exists())
            self.assertFalse((skills / "infrastructure").exists())
            with mock.patch.dict(
                os.environ,
                {
                    "DYNAMO_DEFAULTS_JSON": json.dumps(
                        {
                            "enabled": True, "apiVersion": "nvidia.com/v1beta1", "vllmRuntimeImage": "img@sha256:" + "a" * 64,
                            "vllmRuntimeVersion": "1.4.1", "tensorrtllmRuntimeImage": "img@sha256:" + "b" * 64,
                            "tensorrtllmRuntimeVersion": "1.4.1", "standardVllmImage": "img@sha256:" + "c" * 64,
                            "modelRuntimeOverrides": {}, "observationTimeoutSeconds": 150, "downloadObservationTimeoutSeconds": 300,
                            "downloadTimeoutSeconds": 7200, "verificationTimeoutSeconds": 300, "terminalTimeoutSeconds": 420,
                            "imagePullSecretName": "",
                        }
                    ),
                    "HF_TOKEN_INTAKE_JSON": json.dumps(
                        {
                            "enabled": False, "namespace": "ops", "secretName": "hf-token", "secretKey": "HF_TOKEN",
                            "deleteAfterDownload": False, "requireTokenForHuggingFaceModels": True,
                            "modelRunnerServiceAccount": "sre-sre-llm-runner",
                        }
                    ),
                },
                clear=False,
            ):
                module.reconcile_sre_skills(True, payloads)
            self.assertTrue((skills / "openshift-llm-deploy" / "dynamo-defaults.yaml").is_file())
            self.assertIn("secretName: \"hf-token\"", (skills / "openshift-llm-deploy" / "hf-token-intake.yaml").read_text(encoding="utf-8"))

    def test_seed_plugin_accepts_kubernetes_secret_projection_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            (state / "hermes").mkdir(parents=True)
            module = self.load_plugin("sre_plugin_symlink", state, root)
            module.seed.write_owner_marker("seeding")
            projected_data = root / "..2026_09_01_20_34_00.000000000"
            projected_data.write_bytes(b"proxy-token")
            projected_token = root / "token"
            projected_token.symlink_to(projected_data.name)
            module.PROXY_TOKEN_SOURCE = projected_token
            self.assertEqual(module.reconcile_proxy_token(), "proxy-token")
            self.assertEqual(module.PROXY_TOKEN_DESTINATION.read_bytes(), b"proxy-token")
            self.assertEqual(stat.S_IMODE(module.PROXY_TOKEN_DESTINATION.stat().st_mode), 0o600)

    def test_seed_plugin_embeds_runtime_token_in_private_proxy_kubeconfig(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            (state / "hermes").mkdir(parents=True)
            module = self.load_plugin("sre_plugin_kubeconfig", state, Path(directory))
            module.seed.write_owner_marker("seeding")
            destination = state / "hermes" / "sre-kubeconfig"
            module.write_kubeconfig(destination, "https://sre-proxy.test.svc.cluster.local:8443", "test", "runtime-proxy-token", b"test-proxy-ca")
            content = destination.read_text(encoding="utf-8")
            self.assertIn("    certificate-authority-data: dGVzdC1wcm94eS1jYQ==", content)
            self.assertNotIn("insecure-skip-tls-verify", content)
            self.assertIn('    token: "runtime-proxy-token"', content)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            with self.assertRaisesRegex(SystemExit, "invalid SRE proxy endpoint"):
                module.write_kubeconfig(destination, "http://sre-proxy.test.svc.cluster.local:8443", "test", "t", b"ca")

    def test_seed_plugin_failure_leaves_the_core_marker_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            (state / "hermes" / "skills").mkdir(parents=True)
            plugin_root = root / "plugin"
            plugin_root.mkdir()
            module = self.load_plugin("sre_plugin_retry", state, plugin_root)
            module.seed.write_owner_marker("seeding")
            payloads = {name: f"payload:{name}\n".encode("utf-8") for name in EXPECTED_SRE_BUNDLE_FILES}
            original = module.reconcile_sre_skills

            def fail_after_install(*args: object) -> None:
                original(*args)
                raise RuntimeError("simulated post-install failure")

            with mock.patch.object(module, "read_trust_metadata", return_value="0" * 64), mock.patch.object(
                module, "load_sre_bundle", return_value=payloads
            ), mock.patch.object(module, "reconcile_sre_skills", side_effect=fail_after_install):
                with self.assertRaisesRegex(RuntimeError, "simulated post-install failure"):
                    module.main()
            marker = json.loads(module.seed.MARKER.read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "seeding")
            module.reconcile_sre_skills(False, payloads)
            self.assertTrue((state / "hermes" / "skills" / "kubernetes-sre" / "SKILL.md").is_file())

    # --- Proxy and skill scripts ---------------------------------------------

    def load_script(self, name: str, *parts: str):
        script = CHART_DIR.joinpath(*parts)
        spec = importlib.util.spec_from_file_location(name, script)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_api_proxy_rejects_missing_token_and_unsafe_target(self) -> None:
        module = self.load_script("sre_api_proxy", "files", "scripts", "api_proxy.py")
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "token"
            secret.write_text("expected-token\n", encoding="utf-8")
            self.assertTrue(module.is_authorized("Bearer expected-token", secret))
            self.assertFalse(module.is_authorized("", secret))
            self.assertFalse(module.is_authorized("Bearer wrong", secret))
        self.assertEqual(module.validate_request_target("/apis/apps/v1/namespaces/demo/deployments"), "/apis/apps/v1/namespaces/demo/deployments")
        for target in ("http://attacker.example/", "//attacker.example/api", "/apis/../secrets"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    module.validate_request_target(target)

    def test_api_proxy_rejection_closes_connection_before_unread_body(self) -> None:
        module = self.load_script("sre_api_proxy_reject", "files", "scripts", "api_proxy.py")

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
        module = self.load_script("sre_api_proxy_policy", "files", "scripts", "api_proxy.py")
        self.assertTrue(module.request_allowed("/apis/apps/v1/namespaces/models/deployments/example", "PATCH", "general"))
        for target in (
            "/api/v1/namespaces/models/secrets",
            "/api/v1/namespaces/models/serviceaccounts/privileged/token",
            "/api/v1/namespaces/models/pods/example/exec",
            "/api/v1/namespaces/models/pods/example/ephemeralcontainers",
            "/api/v1/nodes/worker/proxy",
            "/api/v1/watch/namespaces/models/secrets",
        ):
            with self.subTest(target=target):
                self.assertFalse(module.request_allowed(target, "GET", "general"))
        for target in ("/api/v1/namespaces/models/secrets%2Fcredential", "/api/v1/nodes%5Cworker%5Cproxy"):
            with self.subTest(encoded_target=target):
                with self.assertRaises(ValueError):
                    module.validate_request_target(target)
        with mock.patch.dict(os.environ, {"PROXY_SERVICE_PROXY_NAMESPACE": "models"}, clear=False):
            self.assertTrue(module.request_allowed("/api/v1/namespaces/models/services/http:model:8000/proxy/health", "GET", "general"))
            self.assertFalse(module.request_allowed("/api/v1/namespaces/other/services/http:model:8000/proxy/health", "GET", "general"))
        with mock.patch.dict(
            os.environ,
            {"PROXY_SERVICE_NAMESPACE": "openshift-monitoring", "PROXY_SERVICE_NAME": "thanos-querier", "PROXY_SERVICE_PORT": "9091", "PROXY_SERVICE_SCHEME": "https"},
            clear=False,
        ):
            self.assertTrue(module.request_allowed("/api/v1/query?query=up", "GET", "exact-service-proxy"))
            self.assertEqual(module.direct_service_url("/api/v1/query?query=up"), "https://thanos-querier.openshift-monitoring.svc:9091/api/v1/query?query=up")
            self.assertFalse(module.request_allowed("/api/v1/labels?match[]=up", "GET", "exact-service-proxy"))
            self.assertFalse(module.request_allowed("/api/v1/query?query=up", "POST", "exact-service-proxy"))
        allowlist = json.dumps([{"apiGroup": "apps", "resource": "deployments", "name": "owned-model"}])
        with mock.patch.dict(os.environ, {"PROXY_DELETE_NAMESPACE": "models", "PROXY_DELETE_ALLOWED_RESOURCES": allowlist}, clear=False):
            self.assertTrue(module.request_allowed("/apis/apps/v1/namespaces/models/deployments/owned-model", "DELETE", "exact-delete"))
            self.assertFalse(module.request_allowed("/apis/apps/v1/namespaces/models/deployments/other", "DELETE", "exact-delete"))
            self.assertFalse(module.request_allowed("/apis/apps/v1/namespaces/other/deployments/owned-model", "DELETE", "exact-delete"))
            self.assertFalse(module.request_allowed("/apis/apps/v1/namespaces/models/deployments", "DELETE", "exact-delete"))

    def test_model_skill_uses_external_secret_reference_without_webui_cleanup(self) -> None:
        skill = CHART_DIR / "files" / "skills" / "openshift-llm-deploy"
        payload = (skill / "templates" / "model-download-job.yaml").read_text(encoding="utf-8")
        self.assertIn("serviceAccountName: ${MODEL_RUNNER_SERVICE_ACCOUNT}", payload)
        self.assertIn("automountServiceAccountToken: false", payload)
        self.assertIn("key: ${HF_SECRET_KEY}", payload)
        self.assertNotIn("/var/run/secrets/kubernetes.io/serviceaccount", payload)
        deployer = (skill / "scripts" / "deploy-model.sh").read_text(encoding="utf-8")
        self.assertIn("OPENSHIFT_LLM_TARGET_NAMESPACE", deployer)
        self.assertIn("OPENSHIFT_LLM_RUNNER_SERVICE_ACCOUNT", deployer)
        verifier = (skill / "scripts" / "verify-openai-endpoint.sh").read_text(encoding="utf-8")
        self.assertIn("service-proxy", verifier)
        self.assertNotIn("port-forward", verifier)

    def test_metrics_skill_calls_the_direct_exact_proxy_path(self) -> None:
        script = CHART_DIR / "files" / "skills" / "openshift-llm-deploy" / "scripts" / "query-metrics.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_oc = root / "oc"
            arguments_log = root / "oc-arguments"
            kubeconfig = root / "metrics-kubeconfig"
            fake_oc.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >"$OC_ARGUMENTS_LOG"\n', encoding="utf-8")
            fake_oc.chmod(0o755)
            kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{root}:{environment['PATH']}", "OC_ARGUMENTS_LOG": str(arguments_log), "MONITORING_ENABLED": "true",
                    "METRICS_KUBECONFIG": str(kubeconfig), "MONITORING_NAMESPACE": "openshift-monitoring",
                    "MONITORING_SERVICE": "thanos-querier", "MONITORING_SERVICE_PORT": "9091",
                }
            )
            completed = subprocess.run(["sh", str(script), "--query", "up"], check=False, capture_output=True, text=True, env=environment)
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("/api/v1/query?query=up", arguments_log.read_text(encoding="utf-8"))
            self.assertNotIn("/services/", arguments_log.read_text(encoding="utf-8"))

    def test_model_renderer_rejects_multiline_scalars_and_quotes_trtllm_args(self) -> None:
        module = self.load_script("sre_model_renderer", "files", "skills", "openshift-llm-deploy", "scripts", "render-template.py")
        with self.assertRaisesRegex(Exception, "line break"):
            module.parse_assignment("PVC_SIZE=20Gi\n---\nkind: ConfigMap")
        key, value = module.parse_assignment("TRTLLM_ENGINE_ARGS=--engine-name $(touch /tmp/should-not-run)")
        self.assertEqual(key, "TRTLLM_ENGINE_ARGS")
        self.assertEqual(shlex.split(value), ["--engine-name", "$(touch", "/tmp/should-not-run)"])

    def test_model_deployer_rejects_manifest_injection_before_cluster_access(self) -> None:
        script = CHART_DIR / "files" / "skills" / "openshift-llm-deploy" / "scripts" / "deploy-model.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_oc = root / "oc"
            access_log = root / "cluster-access"
            fake_oc.write_text('#!/bin/sh\nprintf "called\\n" >"$CLUSTER_ACCESS_LOG"\nexit 1\n', encoding="utf-8")
            fake_oc.chmod(0o755)
            environment = os.environ.copy()
            environment.update({"PATH": f"{root}:{environment['PATH']}", "CLUSTER_ACCESS_LOG": str(access_log)})
            completed = subprocess.run(
                [
                    "sh", str(script), "--namespace", "models", "--release", "model-a", "--model", "org/model", "--node", "worker-a",
                    "--gpus", "1", "--storage-class", "fast-rwo", "--pvc-size", "20Gi\n---\nkind: ConfigMap", "--memory-request", "16Gi",
                    "--memory-limit", "32Gi", "--hf-secret", "hf-token", "--platform", "kubernetes",
                ],
                check=False, capture_output=True, text=True, env=environment,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertIn("DEPLOYMENT_REASON=invalid-pvc-size", completed.stdout)
            self.assertFalse(access_log.exists())

    def test_openshift_cli_stager_is_multiarch_and_archive_safe(self) -> None:
        module = self.load_script("sre_stage_cli", "files", "scripts", "stage_sre_cli.py")
        environment = {
            "OPENSHIFT_CLI_AMD64_URL": "https://example.invalid/amd64.tar.gz", "OPENSHIFT_CLI_AMD64_SHA256": "a" * 64,
            "OPENSHIFT_CLI_ARM64_URL": "https://example.invalid/arm64.tar.gz", "OPENSHIFT_CLI_ARM64_SHA256": "b" * 64,
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            self.assertEqual(module.selected_artifact("x86_64"), (environment["OPENSHIFT_CLI_AMD64_URL"], "a" * 64))
            self.assertEqual(module.selected_artifact("aarch64"), (environment["OPENSHIFT_CLI_ARM64_URL"], "b" * 64))
            with self.assertRaisesRegex(SystemExit, "unsupported node architecture"):
                module.selected_artifact("ppc64le")
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
            for name, payload in (("oc", b"oc-binary"), ("kubectl", b"kubectl-binary")):
                member = tarfile.TarInfo(name)
                member.mode = 0o755
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
        binaries = module.load_binaries(archive.getvalue())
        self.assertEqual(binaries, {"oc": b"oc-binary", "kubectl": b"kubectl-binary"})
        official_shape = io.BytesIO()
        with tarfile.open(fileobj=official_shape, mode="w:gz") as bundle:
            oc_member = tarfile.TarInfo("oc")
            oc_member.mode = 0o755
            oc_member.size = len(b"shared-client-binary")
            bundle.addfile(oc_member, io.BytesIO(b"shared-client-binary"))
            kubectl_member = tarfile.TarInfo("kubectl")
            kubectl_member.type = tarfile.LNKTYPE
            kubectl_member.linkname = "oc"
            bundle.addfile(kubectl_member)
        self.assertEqual(module.load_binaries(official_shape.getvalue()), {"oc": b"shared-client-binary", "kubectl": b"shared-client-binary"})
        payload = archive.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {
                "OPENSHIFT_CLI_AMD64_URL": "https://example.invalid/amd64.tar.gz", "OPENSHIFT_CLI_AMD64_SHA256": digest,
                "OPENSHIFT_CLI_ARM64_URL": "https://example.invalid/arm64.tar.gz", "OPENSHIFT_CLI_ARM64_SHA256": digest,
                "OPENSHIFT_CLI_VERSION": "test",
            },
            clear=False,
        ), mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(
            module.urllib.request, "urlopen", side_effect=lambda *_args, **_kwargs: io.BytesIO(payload)
        ):
            destination = Path(directory)
            module.main(destination)
            for name in ("oc", "kubectl"):
                self.assertEqual((destination / name).read_bytes(), binaries[name])
                self.assertEqual(stat.S_IMODE((destination / name).stat().st_mode), 0o555)
            os.environ["OPENSHIFT_CLI_AMD64_SHA256"] = "0" * 64
            with self.assertRaisesRegex(SystemExit, "SHA-256 mismatch"):
                module.main(destination)
        unsafe = io.BytesIO()
        with tarfile.open(fileobj=unsafe, mode="w:gz") as bundle:
            member = tarfile.TarInfo("../oc")
            member.size = 1
            bundle.addfile(member, io.BytesIO(b"x"))
        with self.assertRaisesRegex(SystemExit, "unsafe archive member"):
            module.load_binaries(unsafe.getvalue())

    # --- Documentation ---------------------------------------------------------

    def test_readme_catalog_metadata_and_teardown_are_documented(self) -> None:
        readme = CHART_DIR.joinpath("README.md").read_text(encoding="utf-8")
        self.assertIn("| NemoClaw | N/A |", readme)
        self.assertIn("| Harness | Hermes 0.19.0 |", readme)
        self.assertIn("| OpenShell | 0.0.116 |", readme)
        self.assertIn("helm dependency build", readme)
        self.assertIn("global.sre.rbac.mode", readme)
        self.assertIn("I_ACKNOWLEDGE_CLUSTER_WIDE_NO_DELETE", readme)
        self.assertIn("deployer.lifecycle.sandbox.desiredState=absent", readme)
        notes = CHART_DIR.joinpath("templates", "NOTES.txt").read_text(encoding="utf-8")
        self.assertIn("desiredState=absent", notes)
        self.assertIn("gateway-token", notes)


if __name__ == "__main__":
    unittest.main()
