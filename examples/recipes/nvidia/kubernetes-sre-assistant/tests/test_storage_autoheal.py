# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Behavioral regression coverage for the shipped storage controller."""
import copy
import io
import json
from pathlib import Path
import sys
import time
import unittest
from unittest import mock
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / 'charts/sre-autoheal-agent/files/agent'
sys.path.insert(0, str(SOURCE))
from sre_autoheal import kube as k
from sre_autoheal.storage import StorageController, PrometheusMetrics, quantity_bytes, growth_target, validate_samples
from sre_autoheal.config import load_config
from sre_autoheal.policy import Policy
from sre_autoheal.engine import Engine
from sre_autoheal.notify import EmailSink

GIB = 1073741824


class State:
    def __init__(self):
        self.data = {}
        self.saved = 0

    def save(self):
        self.saved += 1


class Sink:
    name = 'email'

    def __init__(self):
        self.messages = []
        self.ok = True

    def send(self, message):
        self.messages.append(message)
        return self.ok


class Notifications:
    def __init__(self):
        self.sinks = [Sink()]

    def wants(self, event):
        return True


class Cluster:
    """API-boundary double retaining resourceVersion/UID conflict semantics."""
    def __init__(self):
        self.pvc = {'metadata': {'name': 'data', 'namespace': 'test', 'uid': 'uid-1',
                                'resourceVersion': '1', 'labels': {'sre-autoheal.nvidia.com/storage': 'true'}},
                    'spec': {'storageClassName': 'csi', 'volumeMode': 'Filesystem',
                             'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': '1Gi'}}},
                    'status': {'phase': 'Bound', 'capacity': {'storage': '1Gi'}}}
        self.sc = {'metadata': {'name': 'csi'}, 'allowVolumeExpansion': True}
        self.quotas = []
        self.vmis = []
        self.kvs = [{'spec': {'configuration': {'developerConfiguration': {'featureGates': ['ExpandDisks']}}}}]
        self.fs = {'items': [{'diskName': 'vda1', 'mountPoint': '/', 'fileSystemType': 'ext4',
                              'usedBytes': 900, 'totalBytes': 1000}]}
        self.writes = []
        self.error = None

    def has_api(self, group, version):
        return bool(self.vmis)

    def get(self, ref):
        if ref.resource == 'persistentvolumeclaims':
            return copy.deepcopy(self.pvc)
        if ref.resource == 'storageclasses':
            return copy.deepcopy(self.sc)
        if ref.subresource == 'filesystemlist':
            return copy.deepcopy(self.fs)
        raise AssertionError(ref)

    def list(self, ref, **kwargs):
        if ref.resource == 'persistentvolumeclaims':
            return [copy.deepcopy(self.pvc)]
        if ref.resource == 'resourcequotas':
            return copy.deepcopy(self.quotas)
        if ref.resource == 'virtualmachineinstances':
            return copy.deepcopy(self.vmis)
        if ref.resource == 'kubevirts':
            return copy.deepcopy(self.kvs)
        if ref.resource == 'datavolumes':
            return [{'spec': {'storage': {'resources': {'requests': {'storage': '1Gi'}}}}}]
        raise AssertionError(ref)

    def patch(self, ref, body, **kwargs):
        if self.error:
            raise self.error
        if body['metadata']['uid'] != self.pvc['metadata']['uid'] or body['metadata']['resourceVersion'] != self.pvc['metadata']['resourceVersion']:
            raise k.KubeError('conflict', status=409)
        self.writes.append((ref, copy.deepcopy(body)))
        self.pvc['metadata'].setdefault('annotations', {}).update(body['metadata']['annotations'])
        self.pvc['metadata']['resourceVersion'] = str(int(self.pvc['metadata']['resourceVersion']) + 1)
        if 'spec' in body:
            self.pvc['spec']['resources']['requests'].update(body['spec']['resources']['requests'])
        return copy.deepcopy(self.pvc)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.cluster = Cluster()
        self.state = State()
        self.notify = Notifications()
        self.sample = {('test', 'data'): {'used': GIB * .9, 'capacity': GIB, 'timestamp': self.now}}
        self.cfg = {'enabled': True, 'sustain_seconds': 0,
                    'allowed_storage_classes': ['csi'], 'targets': [{'namespace': 'test', 'name': 'data'}]}

    def controller(self):
        return StorageController(self.cfg, self.cluster, self.state, self.notify,
                                 namespaces=['test'], metrics=lambda: self.sample, clock=lambda: self.now)

    def cycle(self, **kwargs):
        return self.controller().run_cycle(**kwargs)

    def test_quantity_and_fifteen_percent_rounding(self):
        self.assertEqual(quantity_bytes('1Gi'), GIB)
        self.assertEqual(quantity_bytes('1.5G'), 1500000000)
        self.assertEqual(growth_target('1Gi', 15, '2Ti'), '1178Mi')
        for value in ('-1Gi', 'NaN', 'inf', '1Gi garbage', '0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                quantity_bytes(value)
        with self.assertRaises(ValueError):
            growth_target('2Ti', 15, '2Ti')

    def test_default_recommends_without_mutation(self):
        records = self.cycle()
        self.assertEqual(records[0]['outcome'], 'recommended')
        self.assertEqual(records[0]['target'], '1178Mi')
        self.assertFalse(self.cluster.writes)
        self.assertIn('1178Mi', self.notify.sinks[0].messages[0].text)

    def test_prometheus_rejects_foreign_cluster_and_mismatched_sources(self):
        def row(cluster, node, value):
            return {'metric': {'namespace': 'test', 'persistentvolumeclaim': 'data',
                              'cluster': cluster, 'node': node}, 'value': [1000, str(value)]}
        for rows in ([row('foreign', 'a', 90)] * 4,
                     [row('local', 'a', 90), row('local', 'b', 100),
                      row('local', 'a', 1000), row('local', 'b', 1000)]):
            metrics = PrometheusMetrics({'url': 'https://metrics.example', 'cluster_label': 'cluster', 'cluster_value': 'local'})
            replies = [io.BytesIO(json.dumps({'status': 'success', 'data': {
                'resultType': 'vector', 'result': [r]}}).encode()) for r in rows]
            with mock.patch('sre_autoheal.storage.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = replies
                with self.assertRaises(ValueError):
                    metrics()

    def test_prometheus_consistent_cluster_sources_are_joined(self):
        metrics = PrometheusMetrics({'url': 'https://metrics.example', 'cluster_label': 'cluster', 'cluster_value': 'local'})
        replies = [io.BytesIO(json.dumps({'status': 'success', 'data': {'resultType': 'vector', 'result': [
            {'metric': {'namespace': 'test', 'persistentvolumeclaim': 'data', 'cluster': 'local', 'node': 'a'},
             'value': [1000, str(value)]}]}}).encode()) for value in (90, 100, 999, 998)]
        with mock.patch('sre_autoheal.storage.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = replies
            samples = metrics()
            self.assertEqual(samples[('test', 'data')]['timestamp'], 998)
            self.assertEqual(samples[('test', 'data')]['capacity'], 100)

    def test_watch_engine_uses_configured_namespace_without_cli_override(self):
        self.sample[('test', 'data')]['timestamp'] = time.time()
        config = load_config(environ={})
        config.data['storage'] = {**config.data['storage'], **self.cfg}
        config.data['scope']['include_namespaces'] = ['test']
        self.state.data['fingerprints'] = {}
        engine = Engine(config, self.cluster, None, self.state, self.notify, None)
        snap = SimpleNamespace(errors=[])
        with mock.patch('sre_autoheal.engine.Snapshot.load', return_value=snap), \
             mock.patch.object(engine, 'describe_cluster', return_value={}), \
             mock.patch('sre_autoheal.engine.Detector') as detector, \
             mock.patch('sre_autoheal.storage.PrometheusMetrics.__call__', return_value=self.sample):
            detector.return_value.run.return_value = []
            result = engine.run_cycle()
        self.assertEqual(result['storage'][0]['outcome'], 'recommended')

    def test_collector_failure_escalates_after_three_cycles_without_raw_error(self):
        config = load_config(environ={})
        config.data['storage'] = {**config.data['storage'], **self.cfg}
        config.data['scope']['include_namespaces'] = ['test']
        self.state.data['fingerprints'] = {}
        engine = Engine(config, self.cluster, None, self.state, self.notify, None)
        with mock.patch('sre_autoheal.engine.Snapshot.load', return_value=SimpleNamespace(errors=[])), \
             mock.patch.object(engine, 'describe_cluster', return_value={}), \
             mock.patch('sre_autoheal.engine.Detector') as detector, \
             mock.patch('sre_autoheal.engine.StorageController.run_cycle', side_effect=RuntimeError('secret-provider-body')):
            detector.return_value.run.return_value = []
            for _ in range(2):
                engine.run_cycle()
            self.assertFalse(self.notify.sinks[0].messages)
            engine.run_cycle()
            self.assertEqual(len(self.notify.sinks[0].messages), 1)
            self.assertNotIn('secret-provider-body', self.notify.sinks[0].messages[0].text)
            engine.run_cycle()
            self.assertEqual(len(self.notify.sinks[0].messages), 1)

    def test_storage_namespace_scope_does_not_narrow_general_detection(self):
        self.sample[('test', 'data')]['timestamp'] = time.time()
        config = load_config(environ={})
        config.data['storage'] = {**config.data['storage'], **self.cfg, 'namespaces': ['test']}
        config.data['scope']['include_namespaces'] = []
        self.state.data['fingerprints'] = {}
        engine = Engine(config, self.cluster, None, self.state, self.notify, None)
        with mock.patch('sre_autoheal.engine.Snapshot.load', return_value=SimpleNamespace(errors=[])) as snapshot, \
             mock.patch.object(engine, 'describe_cluster', return_value={}), \
             mock.patch('sre_autoheal.engine.Detector') as detector, \
             mock.patch('sre_autoheal.storage.PrometheusMetrics.__call__', return_value=self.sample):
            detector.return_value.run.return_value = []
            result = engine.run_cycle()
        self.assertEqual(result['storage'][0]['outcome'], 'recommended')
        self.assertIsNone(snapshot.call_args.kwargs['namespaces'])

    def test_storage_scope_rejects_wildcards_before_controller_reads(self):
        config = load_config(environ={})
        config.data['storage'] = {**config.data['storage'], **self.cfg, 'namespaces': ['*']}
        self.state.data['fingerprints'] = {}
        engine = Engine(config, self.cluster, None, self.state, self.notify, None)
        with mock.patch('sre_autoheal.engine.Snapshot.load', return_value=SimpleNamespace(errors=[])), \
             mock.patch.object(engine, 'describe_cluster', return_value={}), \
             mock.patch('sre_autoheal.engine.Detector') as detector, \
             mock.patch('sre_autoheal.engine.StorageController') as controller:
            detector.return_value.run.return_value = []
            result = engine.run_cycle()
        self.assertEqual(result['storage'][0]['outcome'], 'controller_error')
        controller.assert_not_called()

    def test_persistence_failure_refuses_expansion(self):
        class BrokenBackend:
            def save(self, data):
                raise OSError('unavailable')
        self.cfg['mode'] = 'automatic'
        self.state.backend = BrokenBackend()
        self.assertEqual(self.cycle()[0]['outcome'], 'blocked')
        self.assertFalse(self.cluster.writes)

    def test_healed_notification_retains_original_size(self):
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.sample[('test', 'data')].update(capacity=1178 * 1048576, used=GIB * .9)
        result = self.cycle()[0]
        self.assertEqual(result['outcome'], 'healed')
        self.assertEqual(result['original'], '1Gi')
        self.assertIn('1Gi', self.notify.sinks[0].messages[-1].text)

    def test_pending_cannot_verify_from_unrelated_larger_filesystem(self):
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.sample[('test', 'data')].update(capacity=10 * GIB, used=GIB * .9)
        self.assertEqual(self.cycle()[0]['outcome'], 'expansion_pending')
        self.now += 301
        self.sample[('test', 'data')]['timestamp'] = self.now
        self.assertEqual(self.cycle()[0]['outcome'], 'failed')

    def test_explicit_csi_rounding_allows_verified_filesystem_not_node_capacity(self):
        self.cfg.update(mode='automatic', capacity_rounding={'csi': '1Gi'})
        self.cycle()
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.sample[('test', 'data')].update(capacity=2 * GIB * .97, used=GIB * .9)
        self.assertEqual(self.cycle()[0]['outcome'], 'healed')

    def test_explicit_rounding_handles_existing_fractional_pvc(self):
        self.cfg.update(mode='automatic', capacity_rounding={'csi': '1Gi'})
        self.cluster.pvc['spec']['resources']['requests']['storage'] = '1536Mi'
        self.cluster.pvc['status']['capacity']['storage'] = '1536Mi'
        self.sample[('test', 'data')].update(capacity=GIB * 1.94, used=GIB * 1.75)
        self.assertEqual(self.cycle()[0]['outcome'], 'expansion_requested')

    def test_below_threshold_and_sustain_window_do_not_act(self):
        self.cfg.update(mode='automatic', sustain_seconds=300)
        self.assertEqual(self.cycle(), [])
        self.now += 299
        self.sample[('test', 'data')]['timestamp'] = self.now
        self.assertEqual(self.cycle(), [])
        self.sample[('test', 'data')]['used'] = GIB * .84
        self.assertEqual(self.cycle(), [])

    def test_unobserved_gap_restarts_sustain_window(self):
        self.cfg.update(mode='automatic', sustain_seconds=300)
        self.cycle()
        self.now += 3600
        self.sample[('test', 'data')]['timestamp'] = self.now
        self.assertEqual(self.cycle(), [])
        self.assertFalse(self.cluster.writes)

    def test_inventory_failure_restarts_sustain_window(self):
        self.cfg.update(mode='automatic', sustain_seconds=300)
        self.cycle()
        with mock.patch.object(self.cluster, 'list', side_effect=k.KubeError('unavailable', status=503)):
            with self.assertRaises(k.KubeError):
                self.cycle()
        self.now += 301
        self.sample[('test', 'data')]['timestamp'] = self.now
        self.assertEqual(self.cycle(), [])
        self.assertFalse(self.cluster.writes)

    def test_revoked_opt_in_disallows_completion_patch(self):
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.sample[('test', 'data')].update(capacity=1178 * 1048576, used=GIB * .9)
        self.cfg['targets'] = []
        self.cluster.pvc['metadata']['labels'].clear()
        self.cycle()
        self.assertEqual(len(self.cluster.writes), 1)

    def test_guest_response_without_source_timestamp_cannot_prove_recovery(self):
        self.vm()
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.cluster.fs['items'][0]['usedBytes'] = 230
        self.now += 10
        self.assertNotEqual(self.cycle()[0]['outcome'], 'healed')

    def test_automatic_exact_target_patches_once_and_verifies(self):
        self.cfg['mode'] = 'automatic'
        self.assertEqual(self.cycle()[0]['outcome'], 'expansion_requested')
        ref, body = self.cluster.writes[0]
        self.assertEqual((ref.namespace, ref.name), ('test', 'data'))
        self.assertEqual(body['spec'], {'resources': {'requests': {'storage': '1178Mi'}}})
        self.assertEqual(self.cycle()[0]['outcome'], 'expansion_pending')
        self.assertEqual(len(self.cluster.writes), 1)
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.sample[('test', 'data')]['capacity'] = 1178 * 1048576
        self.now += 10
        self.sample[('test', 'data')]['timestamp'] = self.now
        self.assertEqual(self.cycle()[0]['outcome'], 'healed')
        self.assertEqual(sum('spec' in body for _, body in self.cluster.writes), 1)

    def test_disabled_or_missing_expansion_class_fails_closed(self):
        self.cfg['mode'] = 'automatic'
        self.cluster.sc['allowVolumeExpansion'] = False
        self.assertEqual(self.cycle()[0]['outcome'], 'blocked')
        self.assertFalse(self.cluster.writes)

    def test_read_only_global_gates_override_storage_mode(self):
        self.cfg['mode'] = 'automatic'
        for kwargs in ({'act': False}, {'act': True, 'writes_allowed': False}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.cycle(**kwargs)[0]['outcome'], 'recommended')
        self.assertFalse(self.cluster.writes)

    def test_exact_target_and_label_required(self):
        self.cfg['mode'] = 'automatic'
        self.cfg['targets'] = [{'namespace': 'test', 'name': 'different'}]
        self.assertEqual(self.cycle()[0]['outcome'], 'blocked')
        self.cfg['targets'] = [{'namespace': 'test', 'name': 'data'}]
        self.cluster.pvc['metadata']['labels'].clear()
        self.assertEqual(self.cycle()[0]['outcome'], 'blocked')
        self.assertFalse(self.cluster.writes)

    def test_quota_and_pending_resize_block(self):
        self.cfg['mode'] = 'automatic'
        self.cluster.quotas = [{'status': {'hard': {'requests.storage': '1Gi'}, 'used': {'requests.storage': '1Gi'}}}]
        self.assertEqual(self.cycle()[0]['outcome'], 'blocked')
        self.cluster.quotas = []
        self.cluster.pvc['status']['conditions'] = [{'type': 'FileSystemResizePending', 'status': 'True'}]
        self.assertEqual(self.cycle()[0]['outcome'], 'blocked')
        self.assertFalse(self.cluster.writes)

    def test_timeout_never_repatches_even_after_controller_restart(self):
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.now += 301
        self.assertEqual(self.cycle()[0]['outcome'], 'failed')
        self.state = State()
        self.cycle()
        self.assertEqual(sum('spec' in b for _, b in self.cluster.writes), 1)

    def test_failed_notification_retries_without_another_resize(self):
        self.cfg['mode'] = 'automatic'
        self.notify.sinks[0].ok = False
        self.cycle()
        self.notify.sinks[0].ok = True
        self.now += 61
        self.sample[('test', 'data')]['timestamp'] = self.now
        self.cycle()
        self.assertGreaterEqual(len(self.notify.sinks[0].messages), 2)
        self.assertEqual(sum('spec' in b for _, b in self.cluster.writes), 1)

    def test_conflict_or_patch_error_is_not_success(self):
        self.cfg['mode'] = 'automatic'
        self.cluster.error = k.KubeError('forbidden', status=403)
        self.assertEqual(self.cycle()[0]['outcome'], 'failed')
        self.assertFalse(self.cluster.writes)

    def test_failed_submission_is_not_retried_on_later_cycle(self):
        self.cfg['mode'] = 'automatic'
        self.cluster.error = k.KubeError('timeout', status=0)
        self.cycle()
        self.cluster.error = None
        self.now += 60
        self.sample[('test', 'data')]['timestamp'] = self.now
        self.assertEqual(self.cycle()[0]['outcome'], 'blocked')
        self.assertFalse(self.cluster.writes)

    def test_global_policy_budget_counts_storage_action(self):
        self.cfg['mode'] = 'automatic'
        policy = Policy({'mode': 'safe', 'max_actions_per_cycle': 1}, {'include_namespaces': ['test']})
        controller = self.controller()
        controller.policy = policy
        self.assertEqual(controller.run_cycle()[0]['outcome'], 'expansion_requested')
        self.assertEqual(policy._actions_this_cycle, 1)

    def test_nonpersistent_memory_cannot_expand(self):
        from sre_autoheal.memory import Memory, NullBackend
        self.cfg['mode'] = 'automatic'
        self.state = Memory(NullBackend(), {})
        self.assertEqual(self.cycle()[0]['outcome'], 'blocked')
        self.assertFalse(self.cluster.writes)

    def test_sample_capacity_not_matching_pvc_is_blocked(self):
        self.cfg['mode'] = 'automatic'
        self.sample[('test', 'data')].update(used=GIB * 9, capacity=GIB * 10)
        self.assertEqual(self.cycle()[0]['outcome'], 'blocked')
        self.assertFalse(self.cluster.writes)

    def test_global_pause_and_observe_win_even_for_direct_controller(self):
        self.cfg['mode'] = 'automatic'
        for cfg in ({'mode': 'observe'}, {'mode': 'safe', 'paused': True}):
            with self.subTest(cfg=cfg):
                controller = self.controller()
                controller.policy = Policy(cfg, {'include_namespaces': ['test']})
                self.assertEqual(controller.run_cycle()[0]['outcome'], 'recommended')
        self.assertFalse(self.cluster.writes)

    def test_shipped_defaults_are_recommendation_and_disabled(self):
        config = load_config(environ={})
        self.assertFalse(config.get('storage.enabled'))
        self.assertEqual(config.get('storage.mode'), 'recommendation')
        self.assertEqual(config.get('storage.threshold_percent'), 85)
        self.assertEqual(config.get('storage.growth_percent'), 15)

    def test_stale_nan_and_missing_metrics_are_unknown(self):
        for sample in ({}, {('test', 'data'): {'used': float('nan'), 'capacity': GIB, 'timestamp': self.now}},
                       {('test', 'data'): {'used': 100, 'capacity': GIB, 'timestamp': 1}}):
            with self.subTest(sample=sample):
                self.sample = sample
                self.assertEqual(self.cycle()[0]['outcome'], 'unknown')
        self.assertFalse(self.cluster.writes)

    def test_prometheus_sample_validation_rejects_duplicates(self):
        series = [{'metric': {'namespace': 'test', 'persistentvolumeclaim': 'data'}, 'value': [1000, '90']}]
        self.assertEqual(validate_samples(series), {('test', 'data'): 90.0})
        with self.assertRaises(ValueError):
            validate_samples(series + series)

    def vm(self):
        self.cluster.vmis = [{'metadata': {'name': 'vm', 'namespace': 'test', 'uid': 'vm-uid'},
                              'spec': {'volumes': [{'name': 'root', 'persistentVolumeClaim': {'claimName': 'data'}}]},
                              'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'},
                                         {'type': 'AgentConnected', 'status': 'True'}],
                                         'volumeStatus': [{'name': 'root', 'target': 'vda'}]}}]

    def test_vm_uses_guest_usage_not_disk_image_host_usage(self):
        self.vm()
        self.cluster.fs['items'][0]['usedBytes'] = 230
        self.assertEqual(self.cycle(), [])
        self.cluster.fs['items'][0]['usedBytes'] = 900
        self.assertEqual(self.cycle()[0]['outcome'], 'recommended')

    def test_vm_missing_agent_or_mapping_does_not_expand(self):
        self.vm()
        self.cfg['mode'] = 'automatic'
        self.cluster.vmis[0]['status']['conditions'] = []
        self.assertEqual(self.cycle()[0]['outcome'], 'unknown')
        self.assertFalse(self.cluster.writes)

    def test_vm_pvc_success_without_guest_growth_is_partial(self):
        self.vm()
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.now += 10
        self.assertEqual(self.cycle()[0]['outcome'], 'guest_growth_needed')
        self.assertEqual(sum('spec' in b for _, b in self.cluster.writes), 1)

    def expanded_vm(self):
        self.vm()
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.now += 10
        return self.cycle()[0]

    def test_vm_followup_email_has_identity_and_conditional_ext4_steps(self):
        record = self.expanded_vm()
        self.assertEqual(record.get('guest_device'), 'vda1')
        self.assertEqual(record.get('guest_filesystem'), 'ext4')
        message = self.notify.sinks[0].messages[-1]
        self.assertIn('VM: vm', message.text)
        self.assertIn('PVC expanded', message.text)
        self.assertIn('cat /etc/os-release', message.text)
        self.assertIn('findmnt', message.text)
        self.assertIn('Only after', message.text)
        self.assertIn('sudo growpart /dev/vda 1', message.text)
        self.assertIn('sudo resize2fs /dev/vda1', message.text)
        self.assertIn('snapshot', message.text)
        self.assertNotIn('sudo xfs_growfs', message.text)
        self.assertNotIn('virtctl stop', message.text)

    def test_xfs_followup_uses_mount_not_ext4_resizer(self):
        self.cluster.fs['items'][0].update(fileSystemType='xfs', mountPoint='/data')
        self.expanded_vm()
        message = self.notify.sinks[0].messages[-1]
        self.assertIn('sudo xfs_growfs /data', message.text)
        self.assertNotIn('sudo resize2fs', message.text)

    def test_unknown_layout_gets_inspection_not_resize_commands(self):
        self.cluster.fs['items'][0]['fileSystemType'] = 'unknown'
        self.expanded_vm()
        message = self.notify.sinks[0].messages[-1]
        self.assertIn('admin-approved', message.text)
        self.assertIn('lsblk', message.text)
        self.assertNotIn('sudo growpart', message.text)
        self.assertNotIn('sudo resize2fs', message.text)
        self.assertNotIn('sudo xfs_growfs', message.text)

    def test_completed_pvc_with_guest_agent_unavailable_preserves_vm_identity(self):
        self.vm()
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.cluster.vmis[0]['status']['conditions'] = []
        self.now += 301
        record = self.cycle()[0]
        self.assertEqual(record['outcome'], 'guest_growth_needed')
        self.assertEqual(record['vm'], 'vm')
        message = self.notify.sinks[0].messages[-1]
        self.assertIn('PVC expanded', message.text)
        self.assertIn('unavailable', message.text)

    def test_manual_followup_keeps_monitoring_without_second_expansion(self):
        self.expanded_vm()
        self.cluster.fs['items'][0]['usedBytes'] = 230
        self.now += 86401
        record = self.cycle()[0]
        self.assertEqual(record['outcome'], 'guest_verification_needed')
        self.assertEqual(record['vm'], 'vm')
        self.assertEqual(record['utilization_percent'], 23)
        self.assertEqual(sum('spec' in b for _, b in self.cluster.writes), 1)
        self.assertIn('source timestamp', record['detail'])

    def test_partial_vm_operation_keeps_manual_context_after_restart(self):
        self.expanded_vm()
        self.cluster.vmis[0]['status']['conditions'] = []
        self.now += 60
        record = self.cycle()[0]
        self.assertEqual(record['outcome'], 'guest_growth_needed')
        self.assertEqual(record['vm'], 'vm')
        self.assertEqual(sum('spec' in b for _, b in self.cluster.writes), 1)

    def test_legacy_pending_operation_caches_guest_context_on_completion(self):
        self.vm()
        self.cfg['mode'] = 'automatic'
        self.cycle()
        annotation = 'sre-autoheal.nvidia.com/storage-expansion'
        operation = json.loads(self.cluster.pvc['metadata']['annotations'][annotation])
        for key in ('vm', 'vm_uid', 'guest_device', 'guest_mount', 'guest_filesystem'):
            operation.pop(key, None)
        self.cluster.pvc['metadata']['annotations'][annotation] = json.dumps(operation)
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.now += 10
        self.cycle()
        self.cluster.vmis[0]['status']['conditions'] = []
        self.now += 10
        self.assertEqual(self.cycle()[0]['vm'], 'vm')

    def test_vm_resize_timeout_reports_vm_without_claiming_pvc_success(self):
        self.vm()
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.now += 301
        record = self.cycle()[0]
        self.assertEqual(record['outcome'], 'failed')
        self.assertEqual(record['vm'], 'vm')
        message = self.notify.sinks[0].messages[-1]
        self.assertNotIn('sudo growpart', message.text)
        self.assertNotIn('sudo resize2fs', message.text)
        self.assertIn('Do not grow', message.text)

    def test_vm_followup_mime_has_no_attachments(self):
        self.expanded_vm()
        message = self.notify.sinks[0].messages[-1]
        captured = []

        class SMTP:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def send_message(self, mail):
                captured.append(mail)

        sink = EmailSink({'smtp_host': 'test-only.invalid', 'smtp_port': 2525,
                          'starttls': False, 'from_addr': 'sre@example.test',
                          'to_addrs': ['admin@example.test']}, None, None)
        with mock.patch('sre_autoheal.notify.smtplib.SMTP', SMTP):
            self.assertTrue(sink.send(message))
        mail = captured[0]
        self.assertEqual(list(mail.iter_attachments()), [])
        self.assertIn('sudo resize2fs /dev/vda1', mail.get_body(preferencelist=('plain',)).get_content())
        self.assertIn('VM: vm', mail.get_body(preferencelist=('plain',)).get_content())

    def test_historical_guest_mapping_never_supplies_resize_commands(self):
        self.expanded_vm()
        self.cluster.vmis[0]['status']['conditions'] = []
        self.now += 86401
        self.cycle()
        message = self.notify.sinks[0].messages[-1]
        self.assertIn('VM: vm', message.text)
        self.assertNotIn('sudo growpart', message.text)
        self.assertNotIn('sudo resize2fs', message.text)

    def test_reassigned_vmi_does_not_reuse_guest_mapping(self):
        self.vm()
        self.cluster.vmis[0]['metadata']['uid'] = 'original-vmi'
        self.cfg['mode'] = 'automatic'
        self.cycle()
        self.cluster.pvc['status']['capacity']['storage'] = '1178Mi'
        self.cluster.vmis[0]['metadata']['uid'] = 'replacement-vmi'
        self.now += 10
        record = self.cycle()[0]
        self.assertFalse(record['guest_mapping_current'])
        self.assertIn('reassigned', record['detail'])
        self.assertNotIn('sudo growpart', self.notify.sinks[0].messages[-1].text)

    def test_control_char_mount_does_not_supply_guest_resize_commands(self):
        self.cluster.fs['items'][0].update(fileSystemType='xfs', mountPoint='/data\nreboot')
        self.expanded_vm()
        self.assertNotIn('sudo xfs_growfs', self.notify.sinks[0].messages[-1].text)


if __name__ == '__main__':
    unittest.main()
