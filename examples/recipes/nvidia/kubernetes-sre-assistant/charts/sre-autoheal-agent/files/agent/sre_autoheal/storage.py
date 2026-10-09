# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Opt-in, deterministic PVC expansion; no guest exec, VM stop or DV mutation.

PVC operation annotations survive agent restarts and separate releases. A single
resourceVersion-guarded patch records intent AND increases the request. Pending
or failed operations are never resized a second time automatically.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import math
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from . import kube as k
from .notify import Message, Section
from .memory import NullBackend
from .storage_runbook import guest_steps

OPERATION = 'sre-autoheal.nvidia.com/storage-expansion'
OPT_IN = 'sre-autoheal.nvidia.com/storage'
STORAGECLASSES = k.ResourceRef('storage.k8s.io', 'v1', 'storageclasses')
VMIS = k.ResourceRef('kubevirt.io', 'v1', 'virtualmachineinstances')
KUBEVIRTS = k.ResourceRef('kubevirt.io', 'v1', 'kubevirts')
MIB = 1048576

DEFAULTS = {
    'enabled': False, 'mode': 'recommendation', 'threshold_percent': 85,
    'growth_percent': 15, 'sustain_seconds': 300, 'max_size': '2Ti',
    'verification_seconds': 300, 'cooldown_seconds': 86400,
    'notification_dedupe_seconds': 3600, 'notification_retry_seconds': 60,
    'notification_max_attempts': 3, 'max_expansions_per_cycle': 1,
    'allowed_storage_classes': [], 'targets': [], 'capacity_rounding': {}, 'metrics': {
        'url': '', 'ca_file': '', 'token_file': '', 'timeout_seconds': 15,
        'cluster_label': 'cluster', 'cluster_value': '',
        'max_age_seconds': 180, 'allow_http': False,
    },
}


def quantity_bytes(value):
    """Parse positive Kubernetes decimal/binary/exponent quantities exactly."""
    match = re.fullmatch(r'([+]?(?:\d+(?:\.\d*)?|\.\d+))([KMGTPE]i|[kKMGTPE]|[mun]|[eE][+-]?\d+)?', str(value))
    if not match:
        raise ValueError('invalid positive storage quantity')
    number, suffix = Decimal(match[1]), match[2] or ''
    if suffix.endswith('i'):
        factor = Decimal(1024) ** ('KMGTPE'.index(suffix[0]) + 1)
    elif suffix.startswith(('e', 'E')) and len(suffix) > 1:
        factor = Decimal(10) ** int(suffix[1:])
    else:
        factors = {'': 0, 'n': -9, 'u': -6, 'm': -3, 'k': 3, 'K': 3,
                   'M': 6, 'G': 9, 'T': 12, 'P': 15, 'E': 18}
        factor = Decimal(10) ** factors[suffix]
    result = (number * factor).to_integral_value(rounding=ROUND_CEILING)
    if not result.is_finite() or result <= 0 or result > 2 ** 63 - 1:
        raise ValueError('storage quantity outside valid range')
    return int(result)


def growth_target(current, growth_percent=15, cap='2Ti'):
    growth = Decimal(str(growth_percent))
    if not growth.is_finite() or not 10 <= growth <= 15:
        raise ValueError('growth must be between 10 and 15 percent')
    old = quantity_bytes(current)
    target = int((Decimal(old) * (1 + growth / 100) / MIB).to_integral_value(rounding=ROUND_CEILING))
    limit = min(quantity_bytes(cap), quantity_bytes('2Ti'))
    if target * MIB > limit or target * MIB <= old:
        raise ValueError('proposed expansion exceeds cap or is not growth')
    return f'{target}Mi'


def validate_samples(series):
    """Reject ambiguous series instead of aggregating duplicated PVC usage."""
    result = {}
    for row in series:
        labels = row['metric']
        key = (labels.get('namespace'), labels.get('persistentvolumeclaim'))
        if not all(key):
            continue
        value = float(row['value'][1])
        if key in result or not math.isfinite(value) or value < 0:
            raise ValueError('duplicate or invalid PVC metric')
        result[key] = value
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('metrics redirects are refused')


class PrometheusMetrics:
    """Use source sample timestamps, not instant-query evaluation timestamps."""
    def __init__(self, config):
        self.cfg = config
        self.sources = {}

    def query(self, expression):
        url = self.cfg.get('url', '').rstrip('/')
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('configure an authenticated metrics base URL without credentials')
        if parsed.scheme != 'https' and not self.cfg.get('allow_http', False):
            raise ValueError('metrics requires HTTPS; plaintext is explicit test-only opt-in')
        headers = {'Accept': 'application/json'}
        token_file = self.cfg.get('token_file')
        if token_file:
            if parsed.scheme != 'https':
                raise ValueError('bearer credentials must not be sent over HTTP')
            headers['Authorization'] = 'Bearer ' + Path(token_file).read_text().strip()
        ctx = ssl.create_default_context(cafile=self.cfg.get('ca_file') or None)
        opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ctx))
        request = urllib.request.Request(url + '/api/v1/query?' + urllib.parse.urlencode({'query': expression}), headers=headers)
        with opener.open(request, timeout=int(self.cfg.get('timeout_seconds', 15))) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('metrics response exceeds safety limit')
        data = json.loads(raw)
        if data.get('status') != 'success' or data.get('data', {}).get('resultType') != 'vector':
            raise ValueError('metrics response is not a successful vector')
        series = data['data']['result']
        values = validate_samples(series)
        sources = {}
        for row in series:
            labels = row['metric']
            key = (labels.get('namespace'), labels.get('persistentvolumeclaim'))
            if key not in values:
                continue
            if labels.get(self.cfg.get('cluster_label', 'cluster')) != self.cfg.get('cluster_value'):
                raise ValueError('metrics source cluster does not match configured cluster identity')
            sources[key] = {label: value for label, value in labels.items() if label != '__name__'}
        self.sources[expression] = sources
        return values

    def __call__(self):
        label, cluster = self.cfg.get('cluster_label', 'cluster'), self.cfg.get('cluster_value')
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', label) or not isinstance(cluster, str) or not cluster:
            raise ValueError('configure an explicit cluster label/value for storage metrics')
        selector = '{' + label + '=' + json.dumps(cluster) + '}'
        expressions = ['kubelet_volume_stats_used_bytes' + selector,
                       'kubelet_volume_stats_capacity_bytes' + selector,
                       'timestamp(kubelet_volume_stats_used_bytes' + selector + ')',
                       'timestamp(kubelet_volume_stats_capacity_bytes' + selector + ')']
        self.sources = {}
        used, capacity, used_time, capacity_time = [self.query(expression) for expression in expressions]
        keys = used.keys() & capacity.keys() & used_time.keys() & capacity_time.keys()
        for key in keys:
            if any(self.sources[expression][key] != self.sources[expressions[0]][key] for expression in expressions[1:]):
                raise ValueError('PVC metric queries have mismatched source identities')
        return {key: {'used': used[key], 'capacity': capacity[key],
                      'timestamp': min(used_time[key], capacity_time[key])} for key in keys}


class StorageController:
    def __init__(self, config, client, memory, notifier, namespaces, metrics=None,
                 clock=time.time, policy=None):
        self.cfg = {**DEFAULTS, **config}
        self.cfg['metrics'] = {**DEFAULTS['metrics'], **config.get('metrics', {})}
        self.client, self.memory, self.notifier = client, memory, notifier
        self.namespaces, self.clock, self.policy = namespaces, clock, policy
        self.metrics = metrics or PrometheusMetrics(self.cfg['metrics'])
        self.state = memory.data.setdefault('storage', {'observations': {}, 'deliveries': {}, 'records': []})
        self.expansions = 0

    def _sample(self, sample):
        if not sample:
            raise ValueError('PVC utilization unavailable; no capacity decision is possible')
        used, total, stamp = (float(sample[key]) for key in ('used', 'capacity', 'timestamp'))
        age = self.clock() - stamp
        if (not all(math.isfinite(v) for v in (used, total, stamp)) or total <= 0
                or used < 0 or used > total or age < -30
                or age > self.cfg['metrics']['max_age_seconds']):
            raise ValueError('PVC utilization is stale, ambiguous or invalid')
        return {**sample, 'used': used, 'capacity': total, 'timestamp': stamp,
                'utilization': used * 100 / total}

    def _guest(self, pvc, vmis):
        """Resolve VMI volume -> target -> guest partition without assuming vda1."""
        name, ns = pvc['metadata']['name'], pvc['metadata']['namespace']
        matches = []
        for vmi in vmis:
            for volume in vmi.get('spec', {}).get('volumes', []):
                claim = (volume.get('persistentVolumeClaim') or {}).get('claimName')
                dv = (volume.get('dataVolume') or {}).get('name')
                if claim == name or dv == name:
                    matches.append((vmi, volume['name']))
        # Owner hints must not let an inactive VM disk be treated as an app PVC.
        refs = pvc['metadata'].get('ownerReferences', [])
        vm_hint = any(ref.get('kind') in ('DataVolume', 'VirtualMachine') for ref in refs)
        if not matches:
            if vm_hint:
                raise ValueError('VM/DataVolume PVC has no unambiguous running VMI mapping')
            return None
        if len(matches) != 1:
            raise ValueError('PVC is attached to multiple VMI volumes; human review required')
        vmi, volume = matches[0]
        conditions = {c['type']: c.get('status') for c in vmi.get('status', {}).get('conditions', [])}
        if vmi.get('status', {}).get('phase') != 'Running' or conditions.get('Ready') != 'True' or conditions.get('AgentConnected') != 'True':
            raise ValueError('VM must be Running, Ready and AgentConnected; no guest usage inferred')
        targets = [v.get('target') for v in vmi['status'].get('volumeStatus', []) if v.get('name') == volume]
        if len(targets) != 1 or not targets[0] or not re.fullmatch(r'[a-z]+[a-z0-9]*', targets[0]):
            raise ValueError('VMI guest device mapping unavailable')
        ref = k.ResourceRef('subresources.kubevirt.io', 'v1', 'virtualmachineinstances', ns,
                            vmi['metadata']['name'], 'filesystemlist')
        filesystems = self.client.get(ref).get('items', [])
        pattern = re.compile(r'^' + re.escape(targets[0]) + r'(?:p?\d+)?$')
        candidates = [fs for fs in filesystems if pattern.fullmatch(fs.get('diskName', ''))]
        if len(candidates) != 1:
            raise ValueError('guest filesystem cannot be uniquely mapped to this PVC')
        fs = candidates[0]
        return self._sample({'used': fs.get('usedBytes'), 'capacity': fs.get('totalBytes'),
                             'timestamp': self.clock(), 'vm': vmi['metadata']['name'],
                             'vm_uid': vmi['metadata'].get('uid'),
                             'source_freshness_verified': False,
                             'guest_mapping_current': True,
                             'guest_filesystem': fs.get('fileSystemType'),
                             'guest_mount': fs.get('mountPoint'), 'guest_device': fs.get('diskName')})

    def _validate_capacity(self, pvc, sample):
        capacity = quantity_bytes(pvc.get('status', {}).get('capacity', {}).get('storage', '0'))
        rounding = self.cfg['capacity_rounding'].get(pvc['spec'].get('storageClassName'))
        limit = capacity * 1.05
        if rounding:
            unit = quantity_bytes(rounding)
            if unit > quantity_bytes('1Gi'):
                raise ValueError('capacity rounding allowance cannot exceed 1Gi')
            limit = ((capacity + unit - 1) // unit) * unit
        if not sample.get('vm') and sample['capacity'] > limit:
            raise ValueError('metric filesystem capacity exceeds PVC capacity; volume identity is not trustworthy')

    def _preflight(self, pvc, target, sample, quotas):
        meta, spec, status = pvc['metadata'], pvc['spec'], pvc.get('status', {})
        self._validate_capacity(pvc, sample)
        if status.get('phase') != 'Bound' or meta.get('deletionTimestamp'):
            raise ValueError('PVC must be Bound and not terminating')
        if spec.get('volumeMode', 'Filesystem') != 'Filesystem' or spec.get('accessModes') != ['ReadWriteOnce']:
            raise ValueError('automatic profile supports Filesystem/RWO only; offline or RWX review required')
        sc = spec.get('storageClassName')
        if sc not in self.cfg['allowed_storage_classes']:
            raise ValueError('StorageClass is not explicitly approved for expansion')
        storage_class = self.client.get(k.ResourceRef('storage.k8s.io', 'v1', 'storageclasses', name=sc))
        if storage_class.get('allowVolumeExpansion') is not True:
            raise ValueError('StorageClass does not allow volume expansion')
        current = quantity_bytes(spec['resources']['requests']['storage'])
        if quantity_bytes(status.get('capacity', {}).get('storage', '0')) < current or self._resizing(pvc):
            raise ValueError('an existing PVC resize is in progress; do not patch again')
        increment = quantity_bytes(target) - current
        for quota in quotas:
            hard, used = quota.get('status', {}).get('hard', {}), quota.get('status', {}).get('used', {})
            for key, limit in hard.items():
                if key == 'requests.storage' or key == f'{sc}.storageclass.storage.k8s.io/requests.storage':
                    if key not in used:
                        raise ValueError('storage quota usage unavailable')
                    used_bytes = 0 if str(used[key]) == '0' else quantity_bytes(used[key])
                    if used_bytes + increment > quantity_bytes(limit):
                        raise ValueError('storage quota has insufficient expansion headroom')
        if sample.get('vm'):
            kvs = self.client.list(KUBEVIRTS)
            if len(kvs) != 1:
                raise ValueError('KubeVirt online expansion capability is ambiguous')
            dev = kvs[0].get('spec', {}).get('configuration', {}).get('developerConfiguration', {})
            if 'ExpandDisks' not in dev.get('featureGates', []) or 'ExpandDisks' in dev.get('disabledFeatureGates', []):
                raise ValueError('ExpandDisks not explicitly verified; version-specific human review required')

    @staticmethod
    def _resizing(pvc):
        active = {'Resizing', 'FileSystemResizePending', 'ControllerResizeError', 'NodeResizeError'}
        return any(c.get('type') in active and c.get('status') != 'False'
                   for c in pvc.get('status', {}).get('conditions', []))

    def _record(self, pvc, outcome, detail, target='', sample=None):
        meta = pvc['metadata']
        original = pvc['spec']['resources']['requests']['storage']
        try:
            original = json.loads(meta.get('annotations', {}).get(OPERATION, '{}')).get('original', original)
        except (ValueError, AttributeError):
            pass
        result = {'namespace': meta['namespace'], 'pvc': meta['name'], 'uid': meta['uid'],
                  'original': original,
                  'outcome': outcome, 'detail': detail, 'target': target,
                  'requested': pvc['spec']['resources']['requests']['storage'],
                  'capacity': pvc.get('status', {}).get('capacity', {}).get('storage'),
                  'checked_at': self.clock(), 'utilization_percent': (sample or {}).get('utilization'),
                  'vm': (sample or {}).get('vm'), 'guest_mount': (sample or {}).get('guest_mount'),
                  'guest_device': (sample or {}).get('guest_device'),
                  'guest_filesystem': (sample or {}).get('guest_filesystem'),
                  'guest_mapping_current': (sample or {}).get('guest_mapping_current', False),
                  'datavolume_spec_note': 'DataVolume is never patched; reconcile expected size drift in the owning configuration.' if (sample or {}).get('vm') else ''}
        self.state['records'].append(result)
        self.state['records'] = self.state['records'][-200:]
        if outcome not in ('expansion_pending',):
            digest = hashlib.sha256(json.dumps([meta['uid'], outcome, target, detail]).encode()).hexdigest()
            delivery = self.state['deliveries'].get(digest)
            if not delivery or self.clock() - delivery['created'] >= self.cfg['notification_dedupe_seconds']:
                self.state['deliveries'][digest] = {'record': result, 'created': self.clock(), 'sinks': {}}
        self.memory.save()
        return result

    def _deliver(self):
        # Retry each sink independently; never rerun an expansion to retry email.
        for key, entry in list(self.state['deliveries'].items()):
            record = entry['record']
            event = 'healed' if record['outcome'] == 'healed' else 'heal_failed' if record['outcome'] == 'failed' else 'escalated'
            if not self.notifier.wants(event):
                continue
            pairs = [(label, record.get(field)) for label, field in (
                ('Namespace', 'namespace'), ('PVC', 'pvc'), ('Outcome', 'outcome'),
                ('Utilization %', 'utilization_percent'), ('Original size', 'original'), ('Requested size', 'requested'),
                ('Target size', 'target'), ('Reported capacity', 'capacity'), ('VM', 'vm'),
                ('Guest mount', 'guest_mount'), ('Guest device', 'guest_device'),
                ('Guest filesystem', 'guest_filesystem')) if record.get(field) is not None]
            message = Message(event, f"Storage auto-heal: {record['outcome']} - {record['namespace']}/{record['pvc']}",
                              [Section('kv', 'Storage incident', pairs), Section('text', 'Evidence / action', record['detail']),
                               Section('text', 'DataVolume', record['datavolume_spec_note']),
                               Section('steps', 'Read-only checks', [f"kubectl get pvc {record['pvc']} -n {record['namespace']} -o yaml",
                                   f"kubectl get events -n {record['namespace']} --field-selector involvedObject.name={record['pvc']} --sort-by=.lastTimestamp"])],
                              'high' if event != 'healed' else 'info', {'storage': record})
            if record.get('vm'):
                message.sections.append(Section('steps', 'Admin / VM owner follow-up (manual only)', guest_steps(record)))
            for sink in self.notifier.sinks:
                if hasattr(self.notifier, 'allows_sink') and not self.notifier.allows_sink(message, sink.name):
                    continue
                status = entry['sinks'].setdefault(sink.name, {'attempts': 0, 'ok': False, 'last': 0})
                if status['ok'] or status['attempts'] >= self.cfg['notification_max_attempts']:
                    continue
                if status['attempts'] and self.clock() - status['last'] < self.cfg['notification_retry_seconds']:
                    continue
                status['attempts'] += 1
                status['last'] = self.clock()
                try:
                    status['ok'] = bool(sink.send(message))
                except Exception:
                    status['ok'] = False
            if self.clock() - entry['created'] > max(86400, self.cfg['notification_dedupe_seconds']):
                del self.state['deliveries'][key]
        self.memory.save()

    def _finish(self, pvc, operation, outcome):
        # Failure here leaves the durable pending lock, which is conservative.
        meta = pvc['metadata']
        body = {'metadata': {'uid': meta['uid'], 'resourceVersion': meta['resourceVersion'],
                            'annotations': {OPERATION: json.dumps({**operation, 'outcome': outcome}, separators=(',', ':'))}}}
        self.client.patch(k.ResourceRef('', 'v1', 'persistentvolumeclaims', meta['namespace'], meta['name']), body)

    def _pending(self, pvc, operation, samples, vmis, writes_allowed):
        target, started = operation['target'], operation['started']
        if operation.get('uid') != pvc['metadata']['uid']:
            return self._record(pvc, 'blocked', 'operation UID mismatch; human reconciliation required')
        manual_followup = operation.get('outcome') in ('guest_growth_needed', 'guest_verification_needed')
        if operation.get('outcome') not in ('expansion_requested', 'expansion_pending') and not manual_followup:
            if operation.get('outcome') == 'healed' and self.clock() - started >= self.cfg['cooldown_seconds']:
                return None
            return self._record(pvc, 'blocked', 'prior expansion is locked or in cooldown; human reconciliation required', target)
        capacity = quantity_bytes(pvc.get('status', {}).get('capacity', {}).get('storage', '0'))
        sample = None
        if capacity >= quantity_bytes(target) and not self._resizing(pvc):
            try:
                sample = self._guest(pvc, vmis) or self._sample(samples.get((pvc['metadata']['namespace'], pvc['metadata']['name'])))
                self._validate_capacity(pvc, sample)
            except (ValueError, TypeError, KeyError, k.KubeError):
                sample = None
            if operation.get('vm') and (not sample or sample.get('vm') != operation['vm']
                    or (operation.get('vm_uid') and sample.get('vm_uid') != operation['vm_uid'])):
                sample = {key: operation.get(key) for key in
                          ('vm', 'vm_uid', 'guest_device', 'guest_mount', 'guest_filesystem')}
                sample['guest_mapping_current'] = False
                outcome, detail = 'guest_growth_needed', 'PVC expanded and capacity verified; current guest mapping/usage is unavailable or the VMI was reassigned. Admin must verify the attached VM and supply guest resize steps. No further PVC expansion authorized.'
            elif sample and sample.get('vm') and not sample.get('source_freshness_verified'):
                outcome = 'guest_verification_needed' if sample['utilization'] < self.cfg['threshold_percent'] else 'guest_growth_needed'
                detail = 'PVC expanded and capacity verified; guest-agent response has no source timestamp to prove recovery. Admin must inspect the current guest device/filesystem and share approved steps with the VM owner. No further PVC expansion authorized.'
            elif sample and sample['timestamp'] >= started and sample['utilization'] < self.cfg['threshold_percent']:
                outcome, detail = 'healed', 'PVC capacity and fresh utilization verified below threshold; no guest commands or reboot performed'
            elif sample and sample.get('vm'):
                outcome, detail = 'guest_growth_needed', 'PVC expanded, but guest filesystem remains above threshold; approved guest growth or human intervention required; do not resize PVC again'
            elif self.clock() - started <= self.cfg['verification_seconds']:
                return self._record(pvc, 'expansion_pending', 'capacity increased; awaiting fresh filesystem utilization', target)
            else:
                outcome, detail = 'failed', 'PVC capacity increased, but filesystem recovery is unverified or remains above threshold'
        elif self.clock() - started > self.cfg['verification_seconds']:
            outcome, detail = 'failed', 'resize verification exceeded budget; observe outstanding resize, never re-patch or reboot automatically'
        else:
            return self._record(pvc, 'expansion_pending', 'waiting for capacity and resize conditions to clear', target)
        meta = pvc['metadata']
        identity = {'namespace': meta['namespace'], 'name': meta['name']}
        completion_allowed = (identity in self.cfg['targets'] and meta.get('labels', {}).get(OPT_IN) == 'true'
                              and meta.get('labels', {}).get('sre-autoheal.nvidia.com/managed') != 'false')
        if self.policy:
            completion_allowed = (completion_allowed and self.policy.namespace_in_scope(meta['namespace'])
                                  and self.policy.labels_allow_remediation(meta.get('labels', {}))
                                  and 'expand_pvc' not in self.policy.cfg.get('disabled_actions', []))
        if writes_allowed and completion_allowed and not manual_followup:
            if sample and sample.get('vm') and sample.get('guest_mapping_current'):
                operation = {**operation, **{key: sample.get(key) for key in
                    ('vm', 'vm_uid', 'guest_device', 'guest_mount', 'guest_filesystem')}}
            self._finish(pvc, operation, outcome)
        if sample is None and operation.get('vm'):
            sample = {key: operation.get(key) for key in
                      ('vm', 'vm_uid', 'guest_device', 'guest_mount', 'guest_filesystem')}
            sample['guest_mapping_current'] = False
        return self._record(pvc, outcome, detail, target, sample)

    def run_cycle(self, act=True, writes_allowed=True):
        try:
            return self._run_cycle(act=act, writes_allowed=writes_allowed)
        except Exception:
            for observation in self.state['observations'].values():
                observation.pop('above_since', None)
                observation.pop('last_observed', None)
            self.memory.save()
            raise

    def _run_cycle(self, act=True, writes_allowed=True):
        if not self.cfg['enabled']:
            return []
        if self.cfg['mode'] not in ('recommendation', 'automatic'):
            raise ValueError('storage mode must be recommendation or automatic')
        if not 80 <= float(self.cfg['threshold_percent']) <= 90:
            raise ValueError('storage threshold must be between 80 and 90 percent')
        automatic = self.cfg['mode'] == 'automatic' and act and writes_allowed
        if self.policy:
            automatic = automatic and not self.policy.cfg.get('paused') and not self.policy.cfg.get('dry_run') and self.policy.cfg.get('mode', 'observe') in ('safe', 'assisted')
        self.expansions = 0
        records = []
        self._deliver()
        try:
            samples = self.metrics()
        except Exception:
            # Never persist provider response bodies, URLs or credentials.
            samples = {}
        if not self.namespaces:
            raise ValueError('storage monitoring requires explicit scoped namespaces')
        for namespace in self.namespaces:
            pvcs = self.client.list(k.ResourceRef('', 'v1', 'persistentvolumeclaims', namespace))
            # Optional API, but a discovered KubeVirt API with failed inventory
            # must not cause VM disks to fall through to kubelet usage.
            vmis = self.client.list(k.ResourceRef('kubevirt.io', 'v1', 'virtualmachineinstances', namespace)) if self.client.has_api('kubevirt.io', 'v1') else []
            quotas = self.client.list(k.ResourceRef('', 'v1', 'resourcequotas', namespace))
            for listed in pvcs:
                meta = listed['metadata']
                pvc = self.client.get(k.ResourceRef('', 'v1', 'persistentvolumeclaims', namespace, meta['name']))
                meta = pvc['metadata']
                observation = self.state['observations'].setdefault(meta['uid'], {})
                try:
                    raw = meta.get('annotations', {}).get(OPERATION)
                    if raw:
                        operation = json.loads(raw)
                        record = self._pending(pvc, operation, samples, vmis, automatic)
                        if record:
                            records.append(record)
                            continue
                    sample = self._guest(pvc, vmis) or self._sample(samples.get((namespace, meta['name'])))
                    created = meta.get('creationTimestamp')
                    if created:
                        from datetime import datetime
                        if sample['timestamp'] < datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp():
                            raise ValueError('metric predates current PVC UID')
                except (ValueError, TypeError, KeyError, k.KubeError):
                    observation.pop('above_since', None)
                    records.append(self._record(pvc, 'unknown', 'fresh utilization, VM mapping or operation state unavailable; no mutation'))
                    continue
                previous = observation.get('last_observed')
                if previous is None or self.clock() - previous > self.cfg['metrics']['max_age_seconds']:
                    observation.pop('above_since', None)
                observation['last_observed'] = self.clock()
                if sample['utilization'] < self.cfg['threshold_percent']:
                    observation.pop('above_since', None)
                    continue
                if observation.get('failed_submission'):
                    records.append(self._record(pvc, 'blocked', 'prior submission failed or was uncertain; reconcile PVC operation and persisted incident before enabling another attempt'))
                    continue
                # A missing cycle/source resets this grace in the branch above.
                observation.setdefault('above_since', self.clock())
                if self.clock() - observation['above_since'] < max(0, self.cfg['sustain_seconds']):
                    continue
                target = ''
                try:
                    target = growth_target(pvc['spec']['resources']['requests']['storage'], self.cfg['growth_percent'], self.cfg['max_size'])
                    self._preflight(pvc, target, sample, quotas)
                    if not automatic:
                        records.append(self._record(pvc, 'recommended', '85% policy threshold sustained; expansion recommendation only; global read-only gates take precedence', target, sample))
                        continue
                    identity = {'namespace': namespace, 'name': meta['name']}
                    if identity not in self.cfg['targets'] or meta.get('labels', {}).get(OPT_IN) != 'true':
                        raise ValueError('automatic expansion requires exact configured PVC target and storage opt-in label')
                    if meta.get('labels', {}).get('sre-autoheal.nvidia.com/managed') == 'false':
                        raise ValueError('PVC has the global opt-out label')
                    if self.policy:
                        if not self.policy.namespace_in_scope(namespace) or not self.policy.labels_allow_remediation(meta.get('labels', {})):
                            raise ValueError('global scope/label gate denied expansion')
                        if 'expand_pvc' in self.policy.cfg.get('disabled_actions', []):
                            raise ValueError('expand_pvc is disabled by global policy')
                        if self.policy._actions_this_cycle >= self.policy.cfg.get('max_actions_per_cycle', 5) or self.policy._hourly_count() >= self.policy.cfg.get('max_actions_per_hour', 20):
                            raise ValueError('global action budget exhausted')
                    if self.expansions >= self.cfg['max_expansions_per_cycle']:
                        raise ValueError('storage expansion cycle budget exhausted')
                    operation = {'uid': meta['uid'], 'started': self.clock(), 'target': target,
                                 'original': pvc['spec']['resources']['requests']['storage'], 'outcome': 'expansion_requested'}
                    if sample.get('vm'):
                        operation.update({key: sample.get(key) for key in
                                          ('vm', 'vm_uid', 'guest_device', 'guest_mount', 'guest_filesystem')})
                    # Save evidence before irreversible expansion; annotation is
                    # the durable cross-release lock, committed with the size.
                    backend = getattr(self.memory, 'backend', None)
                    if isinstance(backend, NullBackend):
                        raise ValueError('automatic expansion requires persistent incident memory')
                    try:
                        if backend is not None:
                            backend.save(self.memory.data)
                        else:
                            self.memory.save()
                    except Exception:
                        raise ValueError('incident memory could not be persisted; expansion refused') from None
                    body = {'metadata': {'uid': meta['uid'], 'resourceVersion': meta['resourceVersion'],
                                         'annotations': {OPERATION: json.dumps(operation, separators=(',', ':'))}},
                            'spec': {'resources': {'requests': {'storage': target}}}}
                    self.client.patch(k.ResourceRef('', 'v1', 'persistentvolumeclaims', namespace, meta['name']), body)
                    self.expansions += 1
                    if self.policy:
                        self.policy.record_action()
                        self.memory.data['action_times'] = self.policy._action_times
                    records.append(self._record(pvc, 'expansion_requested', 'atomic UID/resourceVersion-guarded PVC expansion submitted; verification pending; no guest mutation', target, sample))
                except ValueError as exc:
                    records.append(self._record(pvc, 'blocked', str(exc), target, sample))
                except k.KubeError as exc:
                    observation['failed_submission'] = {'at': self.clock(), 'target': target, 'status': exc.status}
                    records.append(self._record(pvc, 'failed', f'Kubernetes refused or could not confirm expansion (HTTP {exc.status}); re-read PVC operation before any retry', target, sample))
        self._deliver()
        return records
