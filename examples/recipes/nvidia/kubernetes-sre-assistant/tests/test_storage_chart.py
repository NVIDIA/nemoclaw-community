# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Exercise storage configuration and privilege boundaries in rendered manifests."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

CHART = Path(__file__).resolve().parents[1] / 'charts/sre-autoheal-agent'


class StorageChartTests(unittest.TestCase):
    def render(self, config=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'values.json'
            path.write_text(json.dumps(config or {}))
            return subprocess.run(['helm', 'template', 'storage-test', str(CHART), '-n', 'test', '-f', str(path)],
                                  text=True, capture_output=True)

    def test_recommendation_does_not_grant_storage_write_role(self):
        rendered = self.render({'agentConfig': {'storage': {'enabled': True}}})
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertNotIn('# Source: sre-autoheal-agent/templates/storage-rbac.yaml', rendered.stdout)
        config_doc = next(doc for doc in rendered.stdout.split('\n---\n') if 'config.json: |-' in doc)
        config = json.loads(config_doc.split('config.json: |-\n', 1)[1])
        self.assertEqual(config['storage']['mode'], 'recommendation')

    def test_automatic_role_is_namespaced_and_exact_resource(self):
        rendered = self.render({'rbac': {'profile': 'read-only'}, 'agentConfig': {
            'scope': {'include_namespaces': ['test']}, 'storage': {'enabled': True, 'mode': 'automatic',
                'targets': [{'namespace': 'test', 'name': 'exact-data'}]}}})
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        roles = [doc for doc in rendered.stdout.split('\n---\n') if 'templates/storage-rbac.yaml' in doc]
        self.assertEqual(len(roles), 2)
        self.assertIn('resourceNames: ["exact-data"]', roles[0])
        self.assertIn('namespace: "test"', roles[0])
        cluster_role = next(doc for doc in rendered.stdout.split('\n---\n') if '\nkind: ClusterRole\n' in doc)
        self.assertNotIn('verbs: [patch]', cluster_role)
        self.assertNotIn('verbs: [get, patch]', cluster_role)

    def test_automatic_without_targets_or_scope_refuses_install(self):
        for targets in ([], [{'namespace': 'other', 'name': 'data'}]):
            with self.subTest(targets=targets):
                rendered = self.render({'agentConfig': {'scope': {'include_namespaces': ['test']},
                    'storage': {'enabled': True, 'mode': 'automatic', 'targets': targets}}})
                self.assertNotEqual(rendered.returncode, 0)

    def test_automatic_rejects_ephemeral_or_disabled_memory(self):
        for memory in ({'backend': 'none'}, {'backend': 'file', 'persistence': {'enabled': False}}):
            with self.subTest(memory=memory):
                rendered = self.render({'memory': memory, 'agentConfig': {
                    'scope': {'include_namespaces': ['test']},
                    'storage': {'enabled': True, 'mode': 'automatic',
                                'targets': [{'namespace': 'test', 'name': 'data'}]}}})
                self.assertNotEqual(rendered.returncode, 0)

    def test_metrics_custom_ca_is_mounted_read_only(self):
        rendered = self.render({'metricsCA': {'configMapName': 'metrics-serving-ca', 'key': 'service-ca.crt'}})
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        pod = next(doc for doc in rendered.stdout.split('\n---\n') if '\nkind: Deployment\n' in doc)
        self.assertIn('mountPath: /etc/sre-autoheal/metrics-ca', pod)
        self.assertIn('name: "metrics-serving-ca"', pod)
        self.assertIn('key: "service-ca.crt"', pod)

    def test_disabled_rbac_does_not_create_storage_write_roles(self):
        rendered = self.render({'rbac': {'create': False}, 'agentConfig': {
            'scope': {'include_namespaces': ['test']}, 'storage': {
                'enabled': True, 'mode': 'automatic', 'targets': [{'namespace': 'test', 'name': 'data'}]}}})
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertNotIn('kind: RoleBinding', rendered.stdout)


if __name__ == '__main__':
    unittest.main()
