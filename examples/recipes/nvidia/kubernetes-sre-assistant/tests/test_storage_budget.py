# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""A PVC API write must never precede its persistent global action reservation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import test_storage_autoheal as fixtures
from sre_autoheal.engine import Engine
from sre_autoheal.config import load_config
from sre_autoheal.memory import Memory, FileBackend, ConfigMapBackend
from sre_autoheal import kube as k


class StorageBudgetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StorageTests()
        self.fixture.setUp()
        self.fixture.cfg["mode"] = "automatic"
        self.fixture.cfg["targets"].append({"namespace": "test", "name": "other"})
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "memory.json"
        self.fixture.state = Memory(FileBackend(str(self.path)), {})
        self.original = copy.deepcopy(self.fixture.cluster.pvc)
        self.clock = mock.patch("sre_autoheal.policy.time.time", lambda: self.fixture.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def controller(self):
        config = load_config(environ={})
        config.data["policy"].update(mode="assisted", dry_run=False,
                                     max_actions_per_hour=1, max_actions_per_cycle=5)
        config.data["scope"]["include_namespaces"] = ["test"]
        engine = Engine(config, self.fixture.cluster, None, self.fixture.state, self.fixture.notify, None)
        controller = self.fixture.controller()
        controller.policy = engine.policy
        return controller

    def restart_on_other_pvc(self):
        self.fixture.state = Memory(FileBackend(str(self.path)), {})
        self.fixture.cluster.pvc = copy.deepcopy(self.original)
        self.fixture.cluster.pvc["metadata"].update(name="other", uid="uid-2")
        self.fixture.sample = {("test", "other"): {
            "used": fixtures.GIB * .9, "capacity": fixtures.GIB, "timestamp": self.fixture.now}}
        return self.controller()

    def test_crash_after_committed_patch_blocks_second_pvc_until_hour_expires(self):
        real_patch = self.fixture.cluster.patch

        def commit_then_stop(ref, body, **kwargs):
            real_patch(ref, body, **kwargs)
            raise SystemExit("process interrupted after API commit")

        with mock.patch.object(self.fixture.cluster, "patch", side_effect=commit_then_stop):
            with self.assertRaises(SystemExit):
                self.controller().run_cycle()
        self.assertEqual(len(self.fixture.cluster.writes), 1)
        restarted = self.restart_on_other_pvc()
        result = restarted.run_cycle()
        self.assertEqual(result[0]["outcome"], "blocked")
        self.assertIn("global action budget exhausted", result[0]["detail"])
        self.assertEqual(len(self.fixture.cluster.writes), 1)
        self.fixture.now += 3601
        self.fixture.sample[("test", "other")]["timestamp"] = self.fixture.now
        self.assertEqual(self.controller().run_cycle()[0]["outcome"], "expansion_requested")
        self.assertEqual(len(self.fixture.cluster.writes), 2)

    def test_success_reserves_once_and_persists_before_patch(self):
        real_patch = self.fixture.cluster.patch

        def check_reservation(ref, body, **kwargs):
            self.assertEqual(json.loads(self.path.read_text()).get("action_times"), [self.fixture.now])
            return real_patch(ref, body, **kwargs)

        controller = self.controller()
        with mock.patch.object(self.fixture.cluster, "patch", side_effect=check_reservation):
            self.assertEqual(controller.run_cycle()[0]["outcome"], "expansion_requested")
        self.assertEqual(controller.policy._actions_this_cycle, 1)
        self.assertEqual(controller.policy._action_times, [self.fixture.now])

    def test_failed_reservation_never_patches(self):
        with mock.patch.object(self.fixture.state.backend, "save", side_effect=OSError("disk unavailable")):
            result = self.controller().run_cycle()
        self.assertEqual(result[0]["outcome"], "blocked")
        self.assertFalse(self.fixture.cluster.writes)

    def test_uncertain_patch_keeps_reservation_across_restart(self):
        self.fixture.cluster.error = k.KubeError("timeout", status=0)
        self.assertEqual(self.controller().run_cycle()[0]["outcome"], "failed")
        self.fixture.cluster.error = None
        result = self.restart_on_other_pvc().run_cycle()
        self.assertEqual(result[0]["outcome"], "blocked")
        self.assertFalse(self.fixture.cluster.writes)

    def test_corrupt_memory_blocks_storage_mutation(self):
        self.path.write_text("not json")
        self.fixture.state = Memory(FileBackend(str(self.path)), {})
        result = self.controller().run_cycle()
        self.assertEqual(result[0]["outcome"], "blocked")
        self.assertFalse(self.fixture.cluster.writes)

    def test_permission_denied_memory_preserves_budget_after_access_recovers(self):
        original = '{"version":1,"action_times":[123]}'
        self.path.write_text(original)
        with mock.patch.object(Path, "is_file", return_value=False), \
             mock.patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            self.fixture.state = Memory(FileBackend(str(self.path)), {})
        self.assertTrue(self.fixture.state.load_failed)
        self.assertEqual(self.controller().run_cycle()[0]["outcome"], "blocked")
        self.assertFalse(self.fixture.cluster.writes)
        self.fixture.state.save()
        self.assertEqual(self.path.read_text(), original)

    def test_unreadable_configmap_blocks_storage_mutation(self):
        client = mock.Mock()
        client.get.side_effect = [k.KubeError("forbidden", status=403), {}]
        backend = ConfigMapBackend(client, "test", "memory")
        self.fixture.state = Memory(backend, {})
        result = self.controller().run_cycle()
        self.assertEqual(result[0]["outcome"], "blocked")
        self.assertFalse(self.fixture.cluster.writes)
        client.patch.assert_not_called()

    def test_unknown_memory_schema_does_not_restore_empty_budget(self):
        self.path.write_text(json.dumps({"version": -1}))
        self.fixture.state = Memory(FileBackend(str(self.path)), {})
        self.assertEqual(self.controller().run_cycle()[0]["outcome"], "blocked")
        self.assertFalse(self.fixture.cluster.writes)

    def test_ordinary_remediation_cannot_overwrite_unrecovered_budget(self):
        from types import SimpleNamespace
        from sre_autoheal.models import ActionResult, Diagnosis, Finding, Resource
        from sre_autoheal.notify import Notifier
        self.path.write_text("not json")
        memory = Memory(FileBackend(str(self.path)), {})
        config = load_config(environ={})
        config.data["policy"].update(mode="safe", dry_run=False, tier_overrides={"restart_pod": "SAFE"})
        config.data["scope"]["include_namespaces"] = ["test"]
        engine = Engine(config, object(), None, memory, Notifier([], []), None)
        engine.diagnose = lambda finding, history: Diagnosis("transient", 1.0, "restart_pod")
        finding = Finding("pod-crashloop", "high", Resource("Pod", "p", "test"), "CrashLoop",
                          owner=Resource("Deployment", "model", "test"))
        snapshot = SimpleNamespace(errors=[], workload_labels=lambda subject: ({}, {}))
        with mock.patch.object(engine.executor, "execute", return_value=ActionResult(False, "uncertain")) as execute:
            result = engine.handle_finding(finding, snapshot)
        self.assertEqual(result.decision, "heal_failed")
        execute.assert_not_called()
        self.assertEqual(self.path.read_text(), "not json")


if __name__ == "__main__":
    unittest.main()
