# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The recipe policy and compose file keep inference on this machine."""

import json
import re
import unittest
from pathlib import Path

from localonly import policy_facts

EXAMPLE_DIR = Path(__file__).resolve().parents[2]
POLICY = (EXAMPLE_DIR / "policies" / "local-only.yaml").read_text(encoding="utf-8")
COMPOSE = (EXAMPLE_DIR / "docker-compose.yml").read_text(encoding="utf-8")
COMPOSE_GPU = (EXAMPLE_DIR / "docker-compose.gpu.yml").read_text(encoding="utf-8")
DOCKERFILE = (EXAMPLE_DIR / "Dockerfile").read_text(encoding="utf-8")


class RecipePolicyTests(unittest.TestCase):
    def test_recipe_policy_passes_the_check(self):
        self.assertEqual(policy_facts.check_policy(POLICY), [])

    def test_only_egress_host_is_the_local_inference_route(self):
        self.assertEqual(set(policy_facts.egress_hosts(POLICY)), {"inference.local"})

    def test_filesystem_lists_are_read(self):
        paths = policy_facts.filesystem_paths(POLICY)
        self.assertEqual(paths["read_write"], ["/sandbox", "/tmp", "/dev/null"])
        self.assertIn("/usr", paths["read_only"])

    def test_canary_location_is_outside_the_allowlist(self):
        paths = policy_facts.filesystem_paths(POLICY)
        for path in paths["read_only"] + paths["read_write"]:
            self.assertFalse("/srv/conformance".startswith(path.rstrip("/") + "/"), path)


class PolicyCheckRejectsTests(unittest.TestCase):
    def _problems(self, old, new):
        self.assertIn(old, POLICY)
        return policy_facts.check_policy(POLICY.replace(old, new))

    def test_rejects_a_remote_inference_host(self):
        problems = self._problems("host: inference.local", "host: integrate.api.nvidia.com")
        self.assertTrue(any("integrate.api.nvidia.com" in item for item in problems))

    def test_rejects_an_added_endpoint_in_flow_style(self):
        added = POLICY + "\n  extra:\n    endpoints:\n      - { host: example.com, port: 443, enforcement: enforce }\n"
        self.assertTrue(any("example.com" in item for item in policy_facts.check_policy(added)))

    def test_rejects_audit_only_enforcement(self):
        problems = self._problems("enforcement: enforce", "enforcement: audit")
        self.assertTrue(any("audit" in item for item in problems))

    def test_rejects_a_windows_drive_mount(self):
        problems = self._problems("    - /sandbox\n", "    - /sandbox\n    - /mnt/c\n")
        self.assertTrue(any("/mnt/c" in item for item in problems))

    def test_rejects_the_filesystem_root(self):
        problems = self._problems("    - /usr\n", "    - /\n")
        self.assertTrue(any("not accepted: /" in item for item in problems))

    def test_rejects_yaml_that_the_scanner_cannot_read(self):
        for extra in ("base: &base\n  host: example.com\n", "copy:\n  <<: *base\n", "text: |\n  host: x\n"):
            with self.subTest(extra=extra):
                self.assertTrue(policy_facts.unsupported_constructs(POLICY + extra))

    def test_rejects_a_policy_without_an_endpoint(self):
        self.assertTrue(policy_facts.check_policy("version: 1\n"))


class EffectivePolicyTests(unittest.TestCase):
    def test_accepts_only_the_local_route(self):
        document = json.dumps({"network_policies": {"a": {"endpoints": [{"host": "inference.local"}]}}})
        self.assertEqual(policy_facts.check_effective_policy(document), [])

    def test_rejects_a_remote_host_at_any_depth(self):
        document = json.dumps({"x": [{"y": {"endpoints": [
            {"host": "inference.local"}, {"host": "integrate.api.nvidia.com"},
        ]}}]})
        problems = policy_facts.check_effective_policy(document)
        self.assertEqual(len(problems), 1)
        self.assertIn("integrate.api.nvidia.com", problems[0])

    def test_rejects_a_policy_that_cannot_be_read_back(self):
        for document in ("", "   \n", "not json", "{}"):
            with self.subTest(document=document):
                self.assertTrue(policy_facts.check_effective_policy(document))


class ComposeAndImageTests(unittest.TestCase):
    def test_inference_port_defaults_to_loopback(self):
        self.assertIn('"${OLLAMA_PUBLISH_HOST:-127.0.0.1}:${OLLAMA_PORT:-11434}:11434"', COMPOSE)

    def test_no_port_is_published_without_a_host_address(self):
        for line in COMPOSE.splitlines():
            entry = line.strip()
            if re.match(r'^-\s*"?\d+:\d+"?$', entry):
                self.fail("port published on every interface: " + entry)

    def test_images_are_pinned_by_digest(self):
        self.assertRegex(COMPOSE, r"ollama/ollama:[\w.]+@sha256:[0-9a-f]{64}")
        self.assertRegex(DOCKERFILE, r"ARG BASE_IMAGE=\S+@sha256:[0-9a-f]{64}")

    def test_base_compose_file_starts_without_an_nvidia_gpu(self):
        self.assertNotIn("driver: nvidia", COMPOSE)
        self.assertNotIn("capabilities:", COMPOSE)

    def test_gpu_file_only_adds_the_reservation(self):
        self.assertIn("driver: nvidia", COMPOSE_GPU)
        for key in ("image:", "ports:", "volumes:", "environment:"):
            self.assertNotIn(key, COMPOSE_GPU)

    def test_image_bakes_the_canary_outside_the_allowlist(self):
        self.assertIn("/srv/conformance/outside-canary.txt", DOCKERFILE)
        canary = (EXAMPLE_DIR / "fixtures" / "image" / "outside-canary.txt").read_text(encoding="utf-8")
        self.assertIn("CANARY-OUTSIDE-WORKSPACE", canary)


if __name__ == "__main__":
    unittest.main()
